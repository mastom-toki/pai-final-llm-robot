#!/usr/bin/env python3
"""日本語の指示 → ローカルLLM → 検証(必要なら再計画) → 実行(executorへ) を1コマンドで行う。

ROS不要の純Python。Windows側(Ollamaと同じ側)で動かし、コンテナ内の executor とは run/ のファイルで連携する。
画面にはHUD風のログ(指示・LLMの応答時間・Validatorの判定・実行状況)を出す。収録でそのまま映す。

使い方:
  python -X utf8 sim/nodes/ask.py "赤い箱の前まで行って止まって"
  python -X utf8 sim/nodes/ask.py "青い円柱の前まで行って" --no-exec     # 計画と検証だけ(実行しない)
  python -X utf8 sim/nodes/ask.py "..." --start 0,0,0                   # executor無しで起点を指定
"""
import argparse
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "sim"))

from pai_core import bridge, planner  # noqa: E402


def hud(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def replay_plan(text: str) -> str:
    """logs/ask_log.jsonl から、同じ指示で最後に成功(final=ok)した計画をJSON文字列で返す。"""
    path = os.path.join(ROOT, "logs", "ask_log.jsonl")
    best = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if e.get("text") == text and e.get("final") == "ok":
                    best = e["plan"]
    if best is None:
        raise SystemExit(f"ログに成功した計画がありません: {text!r}(先にLLMで計画を作ってください)")
    return json.dumps(best, ensure_ascii=False)


def follow(offset: int, plan_id: str, timeout_s: float) -> str:
    """executor の状態を追い、finished / failed / rejected のどれかで返す。"""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        events, offset = bridge.read_status_since(offset)
        for ev in events:
            if ev.get("id") != plan_id:
                continue
            name = ev.get("event")
            extra = {k: v for k, v in ev.items() if k not in ("event", "id", "t")}
            hud(f"実行: {name} {extra if extra else ''}")
            if name in ("finished", "failed", "rejected"):
                return name
        time.sleep(0.3)
    return "timeout"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--model", default="gemma4:12b-it-q4_K_M")
    ap.add_argument("--max-replans", type=int, default=2)
    ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("--start", help="x,y,deg(未指定なら run/pose.json、なければ 0,0,0)")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--plan-json", help="LLMを使わず、この計画JSONを検証して実行する(動作確認用)")
    ap.add_argument("--replay", action="store_true",
                    help="logs/ask_log.jsonl にある同じ指示の最新の成功計画を使う(LLMは呼ばない。実行シーンの収録用)")
    a = ap.parse_args()
    if a.replay:
        a.plan_json = replay_plan(a.text)
        hud("(記録済みのLLM計画を再利用: LLMの推論は別収録)")

    if a.start:
        start = tuple(float(v) for v in a.start.split(","))
    else:
        start = bridge.read_pose(max_age_s=10.0)
        if start is None:
            hud("警告: executorの姿勢(run/pose.json)が読めないため、起点を (0,0,0) とみなす")
            start = (0.0, 0.0, 0.0)
    hud(f"指示: {a.text}  (起点 x={start[0]:.2f} y={start[1]:.2f} 向き={start[2]:.0f}°)")

    ctx = planner.build_context()
    if a.plan_json:
        fixed = a.plan_json
        res = planner.plan_with_replan(a.text, ctx, start, lambda msgs, schema: (fixed, 0.0), 0,
                                       log=lambda m: hud(m.replace("LLM(0.0s) →", "計画(記録済み) →")))
    else:
        chat_fn = planner.make_chat_fn(a.host, a.model)
        res = planner.plan_with_replan(a.text, ctx, start, chat_fn, a.max_replans, log=hud)

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "ask_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "text": a.text, "start": start, **res}, ensure_ascii=False) + "\n")

    final = res["final"]
    if final == "clarify":
        hud(f"聞き返し: {res['plan']['question']}")
        return 0
    if final == "reject":
        hud(f"拒否: {res['plan']['reason']}")
        return 0
    if final == "blocked":
        hud("実行しない(Validatorが止めた): " + "; ".join(f"{c} {d}" for c, _, d in res.get("issues", [])))
        return 2
    if final == "error":
        hud(f"エラー: {res['error']}")
        return 1

    steps = " → ".join(
        s["action"] + (f"({s['target']})" if "target" in s else "") for s in res["plan"]["steps"])
    hud(f"計画: {steps}")
    if a.no_exec:
        hud("--no-exec のため実行しない")
        return 0

    plan_id = uuid.uuid4().hex[:8]
    offset = bridge.status_offset()
    bridge.post_plan(res["plan"], plan_id)
    hud(f"executorへ送信 (id={plan_id})")
    result = follow(offset, plan_id, a.timeout)
    hud(f"結果: {result}")
    return 0 if result == "finished" else 3


if __name__ == "__main__":
    sys.exit(main())
