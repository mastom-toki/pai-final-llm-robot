"""指示(日本語) → ローカルLLM → JSON計画 → Validator → (必要なら再計画) をまとめた計画器。

プロンプト・スキーマ・チャット呼び出しは eval/bench_models.py(評価で使った版 v3)をそのまま使う。
評価と本番で文面がずれないよう、ここでは複製しない。ROS非依存。

再計画の方針(ベンチより保守的):
  Validator の指摘が FORBIDDEN_ZONE / WALL_MARGIN だけなら、理由を返して再計画させる(経由点での迂回など)。
  RANGE / UNKNOWN_TARGET / STEP_LIMIT などは「指示そのものを変えないと直らない」ので再計画せず blocked にする
  (黙って別の指示に差し替えて実行しないため)。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import bench_models as B  # noqa: E402
import validator as V  # noqa: E402

REPLANNABLE = {"FORBIDDEN_ZONE", "WALL_MARGIN"}


@dataclass
class Context:
    lm: dict
    ids: list
    schema: dict
    system: str


def build_context(landmarks_path: str | None = None, prompt: str | None = None) -> Context:
    lm = V.load_landmarks(landmarks_path or os.path.join(ROOT, "landmarks.yaml"))
    ids = [o["id"] for o in lm["objects"]] + [w["id"] for w in lm["waypoints"]]
    desc = "\n".join([f"- {o['id']}: {o['color']}の{o['kind']}" for o in lm["objects"]] +
                     [f"- {w['id']}: 経由点" for w in lm["waypoints"]])
    version = prompt or os.environ.get("PAI_PROMPT", "v4")
    return Context(lm, ids, B.build_schema(ids), B.PROMPTS[version].format(ids=desc))


def make_chat_fn(host: str, model: str, temperature: float = 0.3, seed: int = 1):
    """(messages, schema) -> (content, wall_seconds)"""
    def fn(msgs, schema):
        out = B.chat(host, model, msgs, schema, temperature=temperature, seed=seed)
        return out.get("message", {}).get("content", ""), out.get("_wall_s", 0.0)
    return fn


def plan_with_replan(text: str, ctx: Context, start: tuple, chat_fn, max_replans: int = 2, log=print) -> dict:
    """start = (x, y, heading_deg)。戻り値 final: ok / clarify / reject / blocked / error"""
    msgs = [{"role": "system", "content": ctx.system}, {"role": "user", "content": text}]
    attempts: list[dict] = []
    for attempt in range(max_replans + 1):
        try:
            content, wall = chat_fn(msgs, ctx.schema)
        except Exception as e:  # noqa: BLE001
            return {"final": "error", "error": f"LLM呼び出しに失敗: {e}", "attempts": attempts}
        a = {"n": attempt + 1, "wall_s": round(wall, 1), "raw": content}
        attempts.append(a)
        try:
            plan = json.loads(content)
        except json.JSONDecodeError:
            return {"final": "error", "error": "LLMの出力がJSONではない", "attempts": attempts}
        if not B.conforms(plan, set(ctx.ids)):
            return {"final": "error", "error": "LLMの出力がスキーマに適合しない", "attempts": attempts}

        st = plan["status"]
        n_steps = len(plan.get("steps", []))
        log(f"LLM({a['wall_s']}s) → status={st}" + (f" steps={n_steps}" if st == "ok" else ""))
        if st in ("clarify", "reject"):
            return {"final": st, "plan": plan, "attempts": attempts}

        res = V.validate(plan, ctx.lm, start=start)
        a["issues"] = [(i.code, i.step, i.detail) for i in res.issues]
        if res.ok:
            log(f"Validator: OK (移動 {res.total_distance_m:.1f}m, 推定 {res.total_time_s:.0f}s)")
            return {"final": "ok", "plan": plan, "attempts": attempts,
                    "distance_m": res.total_distance_m, "time_s": res.total_time_s}

        codes = {i.code for i in res.issues}
        for i in res.issues:
            log(f"Validator: NG {i.code}" + (f" step{i.step}" if i.step else "") + f" {i.detail}")
        if codes <= REPLANNABLE and attempt < max_replans:
            log(f"再計画 {attempt + 1}/{max_replans}: 理由を返して修正させる")
            msgs += [{"role": "assistant", "content": content},
                     {"role": "user", "content": B.feedback_text(res)}]
            continue
        return {"final": "blocked", "plan": plan, "attempts": attempts, "issues": a["issues"],
                "replannable": codes <= REPLANNABLE}
    return {"final": "blocked", "attempts": attempts}  # 到達しない想定
