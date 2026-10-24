"""ホスト(計画器 ask.py)とコンテナ(executor_node)をファイルでつなぐ。

LLM(Ollama)はWindows側、Gazebo/ROS2はDockerコンテナ内にあり、リポジトリを同じフォルダとして共有する。
ネットワークを開けずに済む(OllamaをLAN公開しない)ための方式。すべて JSON、書き込みは原子的。

  run/plan_inbox.json   計画器 → executor  {"id": ..., "plan": {...}}  (executorが取り込んで .taken にリネーム)
  run/pose.json         executor → 計画器  {"x","y","deg","t"}  (0.5秒ごと)
  run/exec_status.jsonl executor → 計画器  1行1イベント(追記のみ)
"""
from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def run_dir() -> str:
    d = os.environ.get("PAI_RUN_DIR") or os.path.join(ROOT, "run")
    os.makedirs(d, exist_ok=True)
    return d


def _p(name: str) -> str:
    return os.path.join(run_dir(), name)


def atomic_write(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def post_plan(plan: dict, plan_id: str) -> None:
    atomic_write(_p("plan_inbox.json"), {"id": plan_id, "plan": plan})


def inbox_waiting() -> bool:
    """executor側: 受信箱に計画が置かれているか(物理停止中でも確認するため、読み込まずに存在だけ見る)。"""
    return os.path.exists(_p("plan_inbox.json"))


def take_plan() -> dict | None:
    """executor側: 新しい計画があれば取り込み、.taken にリネームして返す。"""
    path = _p("plan_inbox.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            item = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    os.replace(path, _p("plan_inbox.taken.json"))
    return item


def write_pose(x: float, y: float, deg: float) -> None:
    atomic_write(_p("pose.json"), {"x": x, "y": y, "deg": deg, "t": time.time()})


def read_pose(max_age_s: float = 10.0) -> tuple | None:
    try:
        with open(_p("pose.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if time.time() - d.get("t", 0) > max_age_s:
        return None
    return d["x"], d["y"], d["deg"]


def append_status(event: dict) -> None:
    with open(_p("exec_status.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def status_offset() -> int:
    path = _p("exec_status.jsonl")
    return os.path.getsize(path) if os.path.exists(path) else 0


def read_status_since(offset: int) -> tuple[list[dict], int]:
    path = _p("exec_status.jsonl")
    if not os.path.exists(path):
        return [], offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    # 最後の改行までを完全な行として扱う
    cut = data.rfind(b"\n") + 1
    events = []
    for ln in data[:cut].decode("utf-8", errors="ignore").splitlines():
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return events, offset + cut
