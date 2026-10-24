"""実機(gemma)連携テスト: ask.py を順に実行しながら、メモリを1秒ごとに記録する(ホスト側で実行)。

安全装置: 空きメモリが LOW_GB を下回る状態が LOW_SECS 秒続いたら、Ollama のモデルを解放して中断する
(他の作業を巻き込んで固まらせないため)。

使い方: python -X utf8 sim/scripts/live_test.py [--host http://127.0.0.1:11434] "指示1" "指示2" ...
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
LOW_GB, LOW_SECS = 0.35, 8


class MEM(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem():
    m = MEM()
    m.dwLength = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    gb = 2 ** 30
    return m.ullAvailPhys / gb, (m.ullTotalPageFile - m.ullAvailPageFile) / gb


def unload(host, model):
    try:
        req = urllib.request.Request(host + "/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:  # noqa: BLE001
        pass


class Watch(threading.Thread):
    def __init__(self, host, model):
        super().__init__(daemon=True)
        self.host, self.model = host, model
        self.stop_ev = threading.Event()
        self.aborted = False
        self.min_free = 999.0
        self.max_commit = 0.0
        self.low_since = None
        self.proc = None

    def run(self):
        while not self.stop_ev.is_set():
            free, commit = mem()
            self.min_free = min(self.min_free, free)
            self.max_commit = max(self.max_commit, commit)
            if free < LOW_GB:
                self.low_since = self.low_since or time.time()
                if time.time() - self.low_since >= LOW_SECS and not self.aborted:
                    self.aborted = True
                    print(f"!! 空き {free:.2f}GB が {LOW_SECS}秒続いたため、モデルを解放して中断します", flush=True)
                    unload(self.host, self.model)
                    if self.proc and self.proc.poll() is None:
                        self.proc.terminate()
            else:
                self.low_since = None
            self.stop_ev.wait(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("texts", nargs="+")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="gemma4:12b-it-q4_K_M")
    ap.add_argument("--timeout", type=float, default=420.0)
    a = ap.parse_args()

    free0, commit0 = mem()
    print(f"開始時: 空き {free0:.2f}GB / コミット {commit0:.1f}GB", flush=True)
    w = Watch(a.host, a.model)
    w.start()
    rows = []
    for text in a.texts:
        if w.aborted:
            break
        t0 = time.time()
        cmd = [sys.executable, "-X", "utf8", os.path.join(ROOT, "sim", "nodes", "ask.py"), text,
               "--host", a.host, "--model", a.model, "--timeout", "240"]
        print(f"\n===== {text}", flush=True)
        w.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        try:
            out, _ = w.proc.communicate(timeout=a.timeout)
        except subprocess.TimeoutExpired:
            w.proc.kill()
            out = "(timeout)"
        print(out, flush=True)
        rows.append({"text": text, "wall_s": round(time.time() - t0, 1), "exit": w.proc.returncode})
        print(f"-- {rows[-1]['wall_s']}s (exit {w.proc.returncode}) | 空き最小 {w.min_free:.2f}GB", flush=True)
    w.stop_ev.set()
    w.join(timeout=3)
    unload(a.host, a.model)
    print("\nSUMMARY", json.dumps({"start_free_gb": round(free0, 2), "min_free_gb": round(w.min_free, 2),
                                    "max_commit_gb": round(w.max_commit, 1), "aborted": w.aborted, "runs": rows},
                                   ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
