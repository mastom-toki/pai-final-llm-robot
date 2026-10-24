"""メモリ安全装置(ホスト側で並走)。空きが LOW_GB 未満の状態が LOW_SECS 秒続いたら、Ollama のモデルを解放する。
他の作業(Codexなど)を巻き込んで固まらせないための保険。Ctrl+C か、--minutes で終了。
使い方: python -X utf8 sim/scripts/mem_guard.py [--minutes 20]
"""
import argparse
import ctypes
import json
import time
import urllib.request

LOW_GB, LOW_SECS = 0.35, 8


class MEM(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def avail_gb():
    m = MEM()
    m.dwLength = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30


def unload_all(host):
    try:
        names = [m["name"] for m in json.loads(urllib.request.urlopen(host + "/api/ps", timeout=10).read())["models"]]
        for n in names:
            req = urllib.request.Request(host + "/api/generate", data=json.dumps({"model": n, "keep_alive": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
        return names
    except Exception as e:  # noqa: BLE001
        return [f"error: {e}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--minutes", type=float, default=20.0)
    a = ap.parse_args()
    t_end = time.time() + a.minutes * 60
    low_since, min_free = None, 999.0
    print(f"mem_guard 開始(空き<{LOW_GB}GBが{LOW_SECS}秒続いたらモデルを解放)", flush=True)
    while time.time() < t_end:
        f = avail_gb()
        min_free = min(min_free, f)
        if f < LOW_GB:
            low_since = low_since or time.time()
            if time.time() - low_since >= LOW_SECS:
                print(f"!! 空き {f:.2f}GB → モデル解放: {unload_all(a.host)}", flush=True)
                low_since = None
        else:
            low_since = None
        time.sleep(1.0)
    print(f"mem_guard 終了。空き最小 {min_free:.2f}GB", flush=True)


if __name__ == "__main__":
    main()
