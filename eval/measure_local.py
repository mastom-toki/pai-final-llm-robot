"""ローカルPC(CPU/iGPU)でのOllama推論の速度とメモリを、実際の計画生成プロンプトで測る。

使い方: python -X utf8 eval/measure_local.py --model gemma4:12b-it-q4_K_M [--host http://127.0.0.1:11434]
標準ライブラリ + PyYAML。メモリは Windows の GlobalMemoryStatusEx と Get-Process で取得する。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
import bench_models as B  # noqa: E402
import validator as V  # noqa: E402


class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_gb():
    s = MEMSTAT()
    s.dwLength = ctypes.sizeof(MEMSTAT)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.ullAvailPhys / 2**30


PS = ("Get-Process | Where-Object { $_.ProcessName -match 'ollama|llama' } | "
      "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessName,$_.Id,[int]($_.WorkingSet64/1MB) }")


def ollama_procs():
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", PS], capture_output=True, text=True,
                         timeout=30).stdout.strip().splitlines()
    rows = []
    for ln in out:
        p = ln.split("|")
        if len(p) == 3:
            rows.append((p[0], int(p[1]), int(p[2])))
    return rows


class Sampler(threading.Thread):
    """呼び出し中の ollama 系プロセス合計と空きメモリの最小値/最大値を記録する。"""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_ev = threading.Event()
        self.max_proc_mb = 0
        self.min_free_gb = 999.0

    def run(self):
        while not self.stop_ev.is_set():
            try:
                self.max_proc_mb = max(self.max_proc_mb, sum(r[2] for r in ollama_procs()))
            except Exception:  # noqa: BLE001
                pass
            self.min_free_gb = min(self.min_free_gb, free_gb())
            self.stop_ev.wait(0.7)


def post(host, path, body, timeout=900):
    req = urllib.request.Request(host + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call(host, model, msgs, schema, temperature=0.3, seed=1):
    t0 = time.time()
    body = {"model": model, "messages": msgs, "stream": False, "format": schema, "think": False,
            "options": {"temperature": temperature, "seed": seed, "num_ctx": 4096}, "keep_alive": "10m"}
    try:
        out = post(host, "/api/chat", body)
    except urllib.error.HTTPError as e:
        if "think" in e.read().decode(errors="ignore"):
            body.pop("think")
            out = post(host, "/api/chat", body)
        else:
            raise
    wall = time.time() - t0
    ns = 1e9
    return {
        "wall_s": round(wall, 1),
        "load_s": round(out.get("load_duration", 0) / ns, 1),
        "prompt_tokens": out.get("prompt_eval_count"),
        "prompt_eval_s": round(out.get("prompt_eval_duration", 0) / ns, 1),
        "out_tokens": out.get("eval_count"),
        "decode_s": round(out.get("eval_duration", 0) / ns, 1),
        "decode_tok_s": round(out.get("eval_count", 0) / (out.get("eval_duration", 1) / ns), 1),
        "content": out.get("message", {}).get("content", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "local_measure.json"))
    args = ap.parse_args()

    lm = V.load_landmarks(os.path.join(ROOT, "landmarks.yaml"))
    ids = [o["id"] for o in lm["objects"]] + [w["id"] for w in lm["waypoints"]]
    schema = B.build_schema(ids)
    desc = "\n".join([f"- {o['id']}: {o['color']}の{o['kind']}" for o in lm["objects"]] +
                     [f"- {w['id']}: 経由点" for w in lm["waypoints"]])
    system = B.SYSTEM_PROMPT.format(ids=desc)

    # ベースライン(モデルをアンロード)
    try:
        post(args.host, "/api/generate", {"model": args.model, "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(3)
    base = {"free_gb": round(free_gb(), 2), "ollama_procs_mb": sum(r[2] for r in ollama_procs())}
    print("baseline:", base, flush=True)

    sampler = Sampler()
    sampler.start()
    results = []

    def run(label, text, extra=None):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": text}] + (extra or [])
        r = call(args.host, args.model, msgs, schema)
        r["label"] = label
        r["text"] = text
        results.append(r)
        print(f"[{label}] wall={r['wall_s']}s load={r['load_s']}s prompt={r['prompt_tokens']}tok/{r['prompt_eval_s']}s "
              f"out={r['out_tokens']}tok/{r['decode_s']}s ({r['decode_tok_s']} tok/s)", flush=True)
        return r

    run("cold(load込み)", "原点に戻って")
    after_load = {"free_gb": round(free_gb(), 2), "ollama_procs_mb": sum(r[2] for r in ollama_procs())}
    ps = post(args.host, "/api/ps", {}, 30) if False else json.loads(urllib.request.urlopen(args.host + "/api/ps", timeout=30).read())
    print("after load:", after_load, "ps:", [(m["name"], m.get("size"), m.get("size_vram")) for m in ps.get("models", [])], flush=True)

    run("単純(1ステップ)", "赤い箱の前まで行って止まって")
    run("単純(同一入力2回目)", "赤い箱の前まで行って止まって")
    r_dir = run("迂回が要る(初回)", "青い円柱の前まで行って")
    # 再計画: 直進の計画をValidatorに通し、拒否理由を返す
    try:
        plan = json.loads(r_dir["content"])
        res = V.validate(plan, lm)
        if not res.ok:
            extra = [{"role": "assistant", "content": r_dir["content"]}, {"role": "user", "content": B.feedback_text(res)}]
            run("迂回が要る(再計画)", "青い円柱の前まで行って", extra)
        else:
            print("(初回で通ったため再計画なし)", flush=True)
    except Exception as e:  # noqa: BLE001
        print("replan skipped:", e, flush=True)
    run("長い複合", "赤い箱に近づいて3秒待ち、青い円柱を向いて、緑の立方体まで行って原点に戻って")
    run("曖昧(clarify)", "もう少し前に")

    sampler.stop_ev.set()
    sampler.join(timeout=5)
    ps2 = json.loads(urllib.request.urlopen(args.host + "/api/ps", timeout=30).read())

    warm = [r for r in results[1:]]
    summary = {
        "model": args.model, "host": args.host,
        "baseline": base, "after_load": after_load,
        "peak_ollama_procs_mb": sampler.max_proc_mb, "min_free_gb_during": round(sampler.min_free_gb, 2),
        "ps": [{"name": m["name"], "size": m.get("size"), "size_vram": m.get("size_vram")} for m in ps2.get("models", [])],
        "cold_wall_s": results[0]["wall_s"], "cold_load_s": results[0]["load_s"],
        "warm_wall_s_median": round(statistics.median(r["wall_s"] for r in warm), 1),
        "warm_wall_s_max": max(r["wall_s"] for r in warm),
        "decode_tok_s_median": round(statistics.median(r["decode_tok_s"] for r in warm), 1),
        "prompt_tokens_first": results[1]["prompt_tokens"],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "calls": results}, f, ensure_ascii=False, indent=1)
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)

    try:
        post(args.host, "/api/generate", {"model": args.model, "keep_alive": 0}, timeout=60)  # 解放
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
