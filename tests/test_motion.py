import math
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "sim"))
import validator as V  # noqa: E402
from pai_core.motion import V_MAX, W_MAX, Pose, PlanRunner, norm  # noqa: E402

LM = V.load_landmarks(os.path.join(ROOT, "landmarks.yaml"))
POS = V._positions(LM)


def mv(t, d=1.0):
    return {"action": "move_to", "target": t, "stop_distance_m": d}


def face(t):
    return {"action": "rotate_to_face", "target": t}


def simulate(steps, pose, dt=0.05, tmax=900.0, frozen=False):
    """理想のユニサイクル(加速制限なし)で PlanRunner を動かす。"""
    runner = PlanRunner({"status": "ok", "steps": steps}, POS, 0.0)
    t, events, maxv, maxw = 0.0, [], 0.0, 0.0
    while not runner.done and t < tmax:
        cmd, ev = runner.update(pose, t)
        events += ev
        maxv, maxw = max(maxv, abs(cmd.v)), max(maxw, abs(cmd.w))
        if not frozen:
            pose.x += cmd.v * math.cos(pose.yaw) * dt
            pose.y += cmd.v * math.sin(pose.yaw) * dt
            pose.yaw = norm(pose.yaw + cmd.w * dt)
        t += dt
    return runner, events, t, maxv, maxw


PLANS = {
    "近づく": [mv("red_box")],
    "距離2m": [mv("green_cube", 2.0)],
    "迂回": [face("blue_cylinder"), mv("wp_north", 0.0), mv("blue_cylinder")],
    "右90度": [{"action": "rotate", "angle_deg": -90}],
    "後ろを向く": [{"action": "rotate", "angle_deg": 180}],
    "待って近づく": [{"action": "wait", "seconds": 2}, mv("green_cube", 0.5)],
    "複合": [mv("red_box"), {"action": "wait", "seconds": 1}, face("blue_cylinder"),
             mv("wp_south", 0.0), mv("green_cube"), mv("wp_origin", 0.0)],
}


class MotionTest(unittest.TestCase):
    def test_reaches_what_validator_predicts(self):
        for name, steps in PLANS.items():
            with self.subTest(name):
                plan = {"status": "ok", "steps": steps}
                pred = V.validate(plan, LM)
                self.assertTrue(pred.ok, pred.issues)
                pose = Pose(0.0, 0.0, 0.0)
                runner, events, t, maxv, maxw = simulate(steps, pose)
                self.assertIsNone(runner.failed, runner.failed)
                self.assertEqual(events[-1], {"event": "finished"})
                ex, ey, eh = pred.end_pose
                self.assertLess(math.hypot(pose.x - ex, pose.y - ey), 0.08, (pose, pred.end_pose))
                dh = abs(norm(pose.yaw - math.radians(eh)))
                self.assertLess(math.degrees(dh), 6.0, (math.degrees(pose.yaw), eh))
                self.assertLessEqual(maxv, V_MAX + 1e-9)
                self.assertLessEqual(maxw, W_MAX + 1e-9)
                done = [e for e in events if e["event"] == "step_done"]
                self.assertEqual(len(done), len(steps))

    def test_time_is_within_validator_estimate_margin(self):
        steps = PLANS["複合"]
        pred = V.validate({"status": "ok", "steps": steps}, LM)
        _, _, t, _, _ = simulate(steps, Pose(0.0, 0.0, 0.0))
        # 実行時間は見積りの 1.5 倍以内(P制御の減速・再旋回ぶん)
        self.assertLess(t, pred.total_time_s * 1.5 + 5.0, (t, pred.total_time_s))

    def test_starts_from_a_non_origin_pose(self):
        # 2手目の計画は現在姿勢から実行する(前の計画の終点が起点)
        pose = Pose(-3.0 + 1.0, 2.5 - 1.0, math.radians(37))
        steps = [mv("green_cube", 1.0)]
        pred = V.validate({"status": "ok", "steps": steps}, LM, start=(pose.x, pose.y, 37.0))
        self.assertTrue(pred.ok, pred.issues)
        runner, _, _, _, _ = simulate(steps, pose)
        self.assertIsNone(runner.failed)
        self.assertLess(math.hypot(pose.x - pred.end_pose[0], pose.y - pred.end_pose[1]), 0.08)

    def test_timeout_when_robot_cannot_move(self):
        pose = Pose(0.0, 0.0, 0.0)
        runner, events, _, _, _ = simulate([mv("red_box")], pose, tmax=200.0, frozen=True)
        self.assertTrue(runner.done)
        self.assertIn("timeout", runner.failed or "")
        self.assertEqual(events[-1]["event"], "failed")

    def test_abort_stops_runner(self):
        runner = PlanRunner({"status": "ok", "steps": [mv("red_box")]}, POS, 0.0)
        runner.update(Pose(0.0, 0.0, 0.0), 0.0)
        ev = runner.abort("estop")
        self.assertTrue(runner.done)
        self.assertEqual(ev[-1]["event"], "failed")
        cmd, _ = runner.update(Pose(0.0, 0.0, 0.0), 0.1)
        self.assertEqual((cmd.v, cmd.w), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
