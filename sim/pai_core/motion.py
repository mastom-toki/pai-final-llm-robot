"""計画(steps)を cmd_vel に落とす制御ロジック。ROS非依存の純Python(単体テスト可能)。

Validator(src/validator.py)と同じ意味論で動く:
  move_to  : 目標の手前 stop_distance_m で止まる(経由点は目標そのもの)。進行方向を向いて直進する。
  rotate_to_face / rotate / wait / stop
速度上限は Validator の見積り定数(0.3 m/s, 45 deg/s)と揃える。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

V_MAX = 0.30                    # m/s
W_MAX = math.radians(45.0)      # rad/s
POS_TOL = 0.04                  # m
ANG_TOL = math.radians(2.0)     # rad
W_MIN = 0.12                    # rad/s (回転が止まらないための下限)


def norm(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Pose:
    x: float
    y: float
    yaw: float  # rad


@dataclass
class Cmd:
    v: float = 0.0
    w: float = 0.0


def _turn_cmd(err: float) -> Cmd:
    w = clamp(1.5 * err, -W_MAX, W_MAX)
    if abs(w) < W_MIN:
        w = math.copysign(W_MIN, err)
    return Cmd(0.0, w)


class PlanRunner:
    """1つの計画を順に実行する状態機械。update(pose, now) を一定周期で呼ぶ。"""

    def __init__(self, plan: dict, positions: dict, now: float):
        # positions: id -> (x, y, is_waypoint)  (validator._positions と同じ形)
        self.steps = plan["steps"]
        self.pos = positions
        self.i = -1
        self.done = False
        self.failed: str | None = None
        self._step_done = True
        self._t0 = now
        self._timeout = 0.0
        self._goal = (0.0, 0.0)
        self._phase = ""
        self._yaw_goal = 0.0

    # --- 公開API ---
    @property
    def step_no(self) -> int:
        return self.i + 1

    def update(self, pose: Pose, now: float) -> tuple[Cmd, list[dict]]:
        events: list[dict] = []
        if self.done:
            return Cmd(), events
        if self._step_done:
            self._advance(pose, now, events)
            if self.done:
                return Cmd(), events
        if now - self._t0 > self._timeout:
            self._fail(f"timeout at step {self.step_no}", events)
            return Cmd(), events

        s = self.steps[self.i]
        act = s["action"]
        cmd = Cmd()
        if act == "move_to":
            cmd, fin = self._tick_move(pose)
            if fin:
                self._finish_step(events)
        elif act == "rotate_to_face":
            tx, ty, _ = self.pos[s["target"]]
            cmd, fin = self._tick_turn(norm(math.atan2(ty - pose.y, tx - pose.x) - pose.yaw))
            if fin:
                self._finish_step(events)
        elif act == "rotate":
            cmd, fin = self._tick_turn(norm(self._yaw_goal - pose.yaw))
            if fin:
                self._finish_step(events)
        elif act == "wait":
            if now - self._t0 >= float(s["seconds"]):
                self._finish_step(events)
        elif act == "stop":
            self._finish_step(events)
        return cmd, events

    def abort(self, reason: str) -> list[dict]:
        events: list[dict] = []
        self._fail(reason, events)
        return events

    # --- 内部 ---
    def _advance(self, pose: Pose, now: float, events: list[dict]) -> None:
        self.i += 1
        self._step_done = False
        if self.i >= len(self.steps):
            self.done = True
            events.append({"event": "finished"})
            return
        s = self.steps[self.i]
        act = s["action"]
        self._t0 = now
        self._phase = ""
        if act == "move_to":
            tx, ty, is_wp = self.pos[s["target"]]
            d_stop = float(s.get("stop_distance_m", 0.0))
            d_full = math.hypot(tx - pose.x, ty - pose.y)
            if is_wp or d_full < 1e-9:
                self._goal = (tx, ty)
            else:
                k = max(d_full - d_stop, 0.0) / d_full
                self._goal = (pose.x + (tx - pose.x) * k, pose.y + (ty - pose.y) * k)
            dist = math.hypot(self._goal[0] - pose.x, self._goal[1] - pose.y)
            self._timeout = dist / 0.08 + 20.0
            self._phase = "turn"
        elif act == "rotate":
            self._yaw_goal = norm(pose.yaw + math.radians(float(s["angle_deg"])))
            self._timeout = abs(float(s["angle_deg"])) / 11.0 + 10.0
        elif act == "rotate_to_face":
            self._timeout = 180.0 / 11.0 + 10.0
        elif act == "wait":
            self._timeout = float(s["seconds"]) + 5.0
        else:
            self._timeout = 5.0
        events.append({"event": "step_start", "step": self.step_no, "action": act,
                       "target": s.get("target")})

    def _finish_step(self, events: list[dict]) -> None:
        self._step_done = True
        events.append({"event": "step_done", "step": self.step_no})

    def _fail(self, reason: str, events: list[dict]) -> None:
        self.done = True
        self.failed = reason
        events.append({"event": "failed", "reason": reason, "step": self.step_no})

    def _tick_turn(self, err: float) -> tuple[Cmd, bool]:
        if abs(err) < ANG_TOL:
            return Cmd(), True
        return _turn_cmd(err), False

    def _tick_move(self, pose: Pose) -> tuple[Cmd, bool]:
        gx, gy = self._goal
        dist = math.hypot(gx - pose.x, gy - pose.y)
        if dist < POS_TOL:
            return Cmd(), True
        head = norm(math.atan2(gy - pose.y, gx - pose.x) - pose.yaw)
        if self._phase == "turn":
            if abs(head) < ANG_TOL * 1.5:
                self._phase = "drive"
            else:
                return _turn_cmd(head), False
        # drive
        if abs(head) > math.radians(25.0):
            self._phase = "turn"
            return Cmd(), False
        v = min(V_MAX, max(0.06, 0.8 * dist))
        w = clamp(2.0 * head, -W_MAX, W_MAX)
        return Cmd(v, w), False
