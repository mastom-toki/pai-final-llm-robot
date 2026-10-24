import json
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "sim"))
from pai_core import planner  # noqa: E402

CTX = planner.build_context()


def iter_while_item(lines):
    """「- id: ...」の行が続く間だけ返す(idの一覧部分)。"""
    for ln in lines:
        if not ln.startswith("- "):
            return
        yield ln


def mv(t, d=1.0):
    return {"action": "move_to", "target": t, "stop_distance_m": d}


def ok(*steps):
    return json.dumps({"status": "ok", "steps": list(steps)})


class Stub:
    """chat_fn の代わり。決まった応答を順に返し、受け取ったメッセージを記録する。"""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, msgs, schema):
        self.calls.append([dict(m) for m in msgs])
        return self.responses.pop(0), 0.1


class PlannerTest(unittest.TestCase):
    def run_plan(self, stub, text="x", start=(0.0, 0.0, 0.0), max_replans=2):
        logs = []
        res = planner.plan_with_replan(text, CTX, start, stub, max_replans, log=logs.append)
        return res, logs

    def test_direct_path_is_replanned_via_waypoint(self):
        stub = Stub(ok(mv("blue_cylinder")), ok(mv("wp_north", 0.0), mv("blue_cylinder")))
        res, logs = self.run_plan(stub)
        self.assertEqual(res["final"], "ok")
        self.assertEqual(len(res["attempts"]), 2)
        feedback = stub.calls[1][-1]["content"]
        self.assertIn("FORBIDDEN_ZONE", feedback)
        self.assertEqual(stub.calls[1][-2]["role"], "assistant")
        self.assertTrue(any("再計画" in ln for ln in logs))

    def test_out_of_range_is_blocked_without_replanning(self):
        # 指示そのものを変えないと直らない違反は、黙って直させず実行しない
        stub = Stub(ok(mv("red_box", 0.05)))
        res, _ = self.run_plan(stub)
        self.assertEqual(res["final"], "blocked")
        self.assertEqual(len(res["attempts"]), 1)
        self.assertFalse(res["replannable"])
        self.assertEqual(res["issues"][0][0], "RANGE")

    def test_replan_gives_up_after_max_and_is_blocked(self):
        direct = ok(mv("blue_cylinder"))
        stub = Stub(direct, direct, direct)
        res, _ = self.run_plan(stub, max_replans=2)
        self.assertEqual(res["final"], "blocked")
        self.assertEqual(len(res["attempts"]), 3)
        self.assertTrue(res["replannable"])

    def test_clarify_and_reject_pass_through(self):
        res, _ = self.run_plan(Stub(json.dumps({"status": "clarify", "question": "どれ？"})))
        self.assertEqual(res["final"], "clarify")
        res, _ = self.run_plan(Stub(json.dumps({"status": "reject", "reason": "危険"})))
        self.assertEqual(res["final"], "reject")

    def test_bad_outputs_are_errors(self):
        res, _ = self.run_plan(Stub("これはJSONではない"))
        self.assertEqual(res["final"], "error")
        res, _ = self.run_plan(Stub(ok(mv("yellow_ball"))))  # スキーマ外のtarget
        self.assertEqual(res["final"], "error")

    def test_start_pose_is_used_for_validation(self):
        # (2,3.5) 付近(wp_north)からなら青い円柱へ直進してもゾーンを横切らない
        res, _ = self.run_plan(Stub(ok(mv("blue_cylinder"))), start=(2.0, 3.5, 0.0))
        self.assertEqual(res["final"], "ok")
        res, _ = self.run_plan(Stub(ok(mv("blue_cylinder")), ok(mv("blue_cylinder")), ok(mv("blue_cylinder"))),
                               start=(0.0, 0.0, 0.0))
        self.assertEqual(res["final"], "blocked")

    def test_prompt_comes_from_the_evaluated_version(self):
        import bench_models as B
        self.assertIn("statusの規則", B.SYSTEM_PROMPT)
        self.assertNotIn("黄色い球", B.SYSTEM_PROMPT)  # v3: テスト集合の語は入っていない
        self.assertIn("wp_north", CTX.system)
        # 座標はLLMに渡さない: id一覧の部分に物体・経由点の座標値が現れない
        lines = CTX.system.split("使えるid:")[1].lstrip("\n").splitlines()
        id_list = "\n".join(ln for ln in iter_while_item(lines))
        for item in CTX.lm["objects"] + CTX.lm["waypoints"]:
            for v in (item["x"], item["y"]):
                if v:  # 0 は他の数字と区別できないので除く
                    self.assertNotIn(str(v), id_list, item["id"])


if __name__ == "__main__":
    unittest.main()
