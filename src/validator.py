"""Plan Validator: LLM が出した計画を実行前に決定論的に検証する。

生成スキーマは構造とenumだけを保証する。範囲・意味・安全はここで検証する。
理由コード: UNKNOWN_TARGET / RANGE / STEP_LIMIT / FORBIDDEN_ZONE / WALL_MARGIN
            / DISTANCE_LIMIT / TIME_LIMIT / BAD_PLAN
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import yaml

LINEAR_SPEED_MPS = 0.3   # 時間見積り用(Executorの速度上限と揃える)
ANGULAR_SPEED_DPS = 45.0
WALL_HALF_SIZE_M = 6.0


@dataclass
class Issue:
    code: str
    step: int | None  # 1始まり。計画全体の問題は None
    detail: str


@dataclass
class Result:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    end_pose: tuple[float, float, float] | None = None  # x, y, heading_deg
    total_distance_m: float = 0.0
    total_time_s: float = 0.0
    trace: list = field(default_factory=list)  # 各stepの後の姿勢 {step, action, x, y, hdg, wait}


def load_landmarks(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _positions(lm: dict) -> dict[str, tuple[float, float, bool]]:
    """id -> (x, y, is_waypoint)"""
    out = {}
    for o in lm.get("objects", []):
        out[o["id"]] = (float(o["x"]), float(o["y"]), False)
    for w in lm.get("waypoints", []):
        out[w["id"]] = (float(w["x"]), float(w["y"]), True)
    return out


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p) -> bool:
    return (min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9)


def segments_intersect(p1, p2, q1, q2) -> bool:
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 * d2 < 0 and d3 * d4 < 0:
        return True
    eps = 1e-12
    if abs(d1) < eps and _on_segment(q1, q2, p1): return True
    if abs(d2) < eps and _on_segment(q1, q2, p2): return True
    if abs(d3) < eps and _on_segment(p1, p2, q1): return True
    if abs(d4) < eps and _on_segment(p1, p2, q2): return True
    return False


def point_in_polygon(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def segment_hits_polygon(a, b, poly) -> bool:
    if point_in_polygon(a, poly) or point_in_polygon(b, poly):
        return True
    n = len(poly)
    return any(segments_intersect(a, b, poly[i], poly[(i + 1) % n]) for i in range(n))


def _in_range(v, lo_hi) -> bool:
    return lo_hi[0] <= v <= lo_hi[1]


def validate(plan: dict, lm: dict, start=(0.0, 0.0, 0.0)) -> Result:
    """plan を検証する。status が ok 以外はステップ検証なしで形だけ確認する。"""
    res = Result(ok=True)
    lim = lm["limits"]
    pos = _positions(lm)
    zones = [[tuple(p) for p in z["polygon"]] for z in lm.get("forbidden_zones", [])]

    def bad(code, step, detail):
        res.ok = False
        res.issues.append(Issue(code, step, detail))

    status = plan.get("status")
    if status in ("clarify", "reject"):
        if status == "clarify" and not plan.get("question"):
            bad("BAD_PLAN", None, "clarify には question が必要")
        if status == "reject" and not plan.get("reason"):
            bad("BAD_PLAN", None, "reject には reason が必要")
        return res
    if status != "ok":
        bad("BAD_PLAN", None, f"status が不正: {status!r}")
        return res

    steps = plan.get("steps") or []
    if not steps:
        bad("BAD_PLAN", None, "steps が空")
        return res
    if len(steps) > lim["max_steps"]:
        bad("STEP_LIMIT", None, f"{len(steps)} > {lim['max_steps']}")

    x, y, hdg = start
    margin = WALL_HALF_SIZE_M - lim["wall_margin_m"]
    dist = 0.0
    time_s = 0.0

    for i, s in enumerate(steps, start=1):
        act = s.get("action")
        if act == "move_to":
            t = s.get("target")
            if t not in pos:
                bad("UNKNOWN_TARGET", i, f"target={t!r}")
                continue
            tx, ty, is_wp = pos[t]
            d_stop = float(s.get("stop_distance_m", 0.0))
            if not is_wp and not _in_range(d_stop, lim["stop_distance_m"]):
                bad("RANGE", i, f"stop_distance_m={d_stop} (許容 {lim['stop_distance_m']})")
                continue
            d_full = math.hypot(tx - x, ty - y)
            if is_wp or d_full < 1e-9:
                gx, gy = tx, ty
            else:
                k = max(d_full - d_stop, 0.0) / d_full  # 目標の手前 d_stop で止まる
                gx, gy = x + (tx - x) * k, y + (ty - y) * k
            for zi, poly in enumerate(zones):
                if segment_hits_polygon((x, y), (gx, gy), poly):
                    bad("FORBIDDEN_ZONE", i,
                        f"({x:.2f},{y:.2f})->({gx:.2f},{gy:.2f}) が {lm['forbidden_zones'][zi]['id']} と交差")
                    break
            if abs(gx) > margin or abs(gy) > margin:
                bad("WALL_MARGIN", i, f"停止点({gx:.2f},{gy:.2f}) が壁から {lim['wall_margin_m']}m 未満")
            seg = math.hypot(gx - x, gy - y)
            if seg > 1e-9:
                hdg = math.degrees(math.atan2(gy - y, gx - x))
            dist += seg
            time_s += seg / LINEAR_SPEED_MPS
            x, y = gx, gy
        elif act == "rotate_to_face":
            t = s.get("target")
            if t not in pos:
                bad("UNKNOWN_TARGET", i, f"target={t!r}")
                continue
            tx, ty, _ = pos[t]
            new_h = math.degrees(math.atan2(ty - y, tx - x))
            d = abs((new_h - hdg + 180) % 360 - 180)
            time_s += d / ANGULAR_SPEED_DPS
            hdg = new_h
        elif act == "rotate":
            a = float(s.get("angle_deg", 0.0))
            if not _in_range(a, lim["angle_deg"]):
                bad("RANGE", i, f"angle_deg={a}")
                continue
            hdg = (hdg + a + 180) % 360 - 180
            time_s += abs(a) / ANGULAR_SPEED_DPS
        elif act == "wait":
            w = float(s.get("seconds", 0.0))
            if not _in_range(w, lim["wait_seconds"]):
                bad("RANGE", i, f"seconds={w}")
                continue
            time_s += w
        elif act == "stop":
            pass
        else:
            bad("BAD_PLAN", i, f"未知の action: {act!r}")
        res.trace.append({"step": i, "action": act, "x": x, "y": y, "hdg": hdg,
                          "wait": s.get("seconds") if act == "wait" else None})

    if dist > lim["max_total_distance_m"]:
        bad("DISTANCE_LIMIT", None, f"{dist:.1f}m > {lim['max_total_distance_m']}m")
    if time_s > lim["max_total_time_s"]:
        bad("TIME_LIMIT", None, f"{time_s:.0f}s > {lim['max_total_time_s']}s")

    res.end_pose = (x, y, hdg)
    res.total_distance_m = dist
    res.total_time_s = time_s
    return res
