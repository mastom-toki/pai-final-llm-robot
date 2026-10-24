import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import validator as v  # noqa: E402

LM = v.load_landmarks(os.path.join(os.path.dirname(__file__), "..", "landmarks.yaml"))


def mv(target, d=1.0):
    return {"action": "move_to", "target": target, "stop_distance_m": d}


def ok_plan(*steps):
    return {"status": "ok", "steps": list(steps)}


def codes(res):
    return [i.code for i in res.issues]


class GeometryTest(unittest.TestCase):
    def test_crossing_and_touching(self):
        sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
        self.assertTrue(v.segment_hits_polygon((-1, 1), (3, 1), sq))   # 貫通
        self.assertTrue(v.segment_hits_polygon((1, 1), (5, 5), sq))    # 内側から出る
        self.assertFalse(v.segment_hits_polygon((-1, 3), (3, 3), sq))  # 外を通過
        self.assertTrue(v.segment_hits_polygon((-1, 0), (3, 0), sq))   # 辺に沿う(接触)


class ValidatorTest(unittest.TestCase):
    def test_simple_ok(self):
        r = v.validate(ok_plan(mv("red_box", 1.0)), LM)
        self.assertTrue(r.ok, r.issues)
        self.assertGreater(r.total_distance_m, 0)

    def test_direct_to_blue_cylinder_hits_zone(self):
        r = v.validate(ok_plan(mv("blue_cylinder", 1.0)), LM)
        self.assertFalse(r.ok)
        self.assertIn("FORBIDDEN_ZONE", codes(r))
        self.assertEqual(r.issues[0].step, 1)

    def test_detour_via_waypoint_is_ok(self):
        r = v.validate(ok_plan(mv("wp_north", 0.0), mv("blue_cylinder", 1.0)), LM)
        self.assertTrue(r.ok, r.issues)

    def test_unknown_target(self):
        r = v.validate(ok_plan(mv("yellow_ball", 1.0)), LM)
        self.assertIn("UNKNOWN_TARGET", codes(r))

    def test_stop_distance_out_of_range(self):
        r = v.validate(ok_plan(mv("green_cube", 0.05)), LM)
        self.assertIn("RANGE", codes(r))

    def test_step_limit(self):
        r = v.validate(ok_plan(*[{"action": "stop"}] * 9), LM)
        self.assertIn("STEP_LIMIT", codes(r))

    def test_wall_margin(self):
        lm = {**LM, "objects": LM["objects"] + [
            {"id": "wall_box", "kind": "box", "color": "red", "x": 5.8, "y": 0.0}]}
        # wall_box の手前0.4mで止まっても x=5.4 は margin(5.5) 内。目標を壁際(x=5.95)にして超過させる
        lm["objects"][-1]["x"] = 5.95
        r = v.validate(ok_plan(mv("wall_box", 0.4)), lm)
        self.assertIn("WALL_MARGIN", codes(r))

    def test_distance_limit(self):
        steps = []
        for _ in range(4):  # 原点<->green_cube を往復(約6.7m×)
            steps += [mv("green_cube", 0.4), mv("wp_origin", 0.0)]
        r = v.validate(ok_plan(*steps), LM)  # 8ステップ(上限ちょうど)で距離だけ超過
        self.assertNotIn("STEP_LIMIT", codes(r))
        self.assertIn("DISTANCE_LIMIT", codes(r))

    def test_angle_and_wait_range(self):
        r = v.validate(ok_plan({"action": "rotate", "angle_deg": 270},
                               {"action": "wait", "seconds": 99}), LM)
        self.assertEqual(codes(r).count("RANGE"), 2)

    def test_clarify_and_reject_shapes(self):
        self.assertTrue(v.validate({"status": "clarify", "question": "どれ？"}, LM).ok)
        self.assertTrue(v.validate({"status": "reject", "reason": "立入禁止"}, LM).ok)
        self.assertIn("BAD_PLAN", codes(v.validate({"status": "clarify"}, LM)))
        self.assertIn("BAD_PLAN", codes(v.validate({"status": "??"}, LM)))

    def test_rotate_to_face_then_move(self):
        r = v.validate(ok_plan({"action": "rotate_to_face", "target": "blue_cylinder"},
                               mv("red_box", 1.0)), LM)
        self.assertTrue(r.ok, r.issues)


if __name__ == "__main__":
    unittest.main()
