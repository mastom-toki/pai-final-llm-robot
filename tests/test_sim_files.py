import os
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "sim"))
sys.path.insert(0, os.path.join(ROOT, "sim", "tools"))
import gen_world  # noqa: E402
import validator as V  # noqa: E402
from pai_core import bridge  # noqa: E402

LM = V.load_landmarks(os.path.join(ROOT, "landmarks.yaml"))


def pose_of(model):
    x, y, z = (float(v) for v in model.find("pose").text.split()[:3])
    return x, y, z


class WorldTest(unittest.TestCase):
    def setUp(self):
        self.root = ET.fromstring(gen_world.generate(LM).split("?>", 1)[1])
        self.models = {m.get("name"): m for m in self.root.iter("model")}

    def test_objects_and_waypoints_match_landmarks(self):
        for o in LM["objects"]:
            x, y, z = pose_of(self.models[o["id"]])
            self.assertAlmostEqual(x, o["x"])
            self.assertAlmostEqual(y, o["y"])
            self.assertGreater(z, 0.0)
        for w in LM["waypoints"]:
            x, y, _ = pose_of(self.models[w["id"]])
            self.assertAlmostEqual(x, w["x"])
            self.assertAlmostEqual(y, w["y"])

    def test_zone_center_size_and_no_collision(self):
        z = LM["forbidden_zones"][0]
        xs = [p[0] for p in z["polygon"]]
        ys = [p[1] for p in z["polygon"]]
        m = self.models[z["id"]]
        x, y, _ = pose_of(m)
        self.assertAlmostEqual(x, (min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(y, (min(ys) + max(ys)) / 2)
        size = [float(v) for v in m.find(".//visual//size").text.split()]
        self.assertAlmostEqual(size[0], max(xs) - min(xs))
        self.assertAlmostEqual(size[1], max(ys) - min(ys))
        self.assertIsNone(m.find(".//collision"))  # 床の目印(ロボットは物理的には入れてしまう→Validatorが守る)

    def test_wall_inner_faces_are_at_validator_limit(self):
        half = V.WALL_HALF_SIZE_M
        n = self.models["wall_n"]
        _, y, _ = pose_of(n)
        thick = float(n.find(".//collision//size").text.split()[1])
        self.assertAlmostEqual(y - thick / 2, half)
        e = self.models["wall_e"]
        x, _, _ = pose_of(e)
        thick = float(e.find(".//collision//size").text.split()[0])
        self.assertAlmostEqual(x - thick / 2, half)

    def test_state_plugin_present_for_failure_injection(self):
        names = [p.get("filename") for p in self.root.iter("plugin")]
        self.assertIn("libgazebo_ros_state.so", names)


class UrdfTest(unittest.TestCase):
    def setUp(self):
        self.r = ET.parse(os.path.join(ROOT, "sim", "urdf", "diffbot.urdf")).getroot()
        self.joints = {j.get("name"): j for j in self.r.iter("joint")}

    @staticmethod
    def z_of(joint):
        return float(joint.find("origin").get("xyz").split()[2])

    @staticmethod
    def y_of(joint):
        return float(joint.find("origin").get("xyz").split()[1])

    def test_geometry_is_consistent_with_plugin(self):
        plug = next(p for p in self.r.iter("plugin") if p.get("name") == "diff_drive")
        sep = float(plug.find("wheel_separation").text)
        dia = float(plug.find("wheel_diameter").text)
        lw, rw = self.joints["left_wheel_joint"], self.joints["right_wheel_joint"]
        self.assertAlmostEqual(self.y_of(lw) - self.y_of(rw), sep)
        radius = float(self.r.find(".//link[@name='left_wheel']//cylinder").get("radius"))
        self.assertAlmostEqual(2 * radius, dia)
        self.assertEqual(plug.find("odometry_source").text, "1")

    def test_wheels_and_casters_touch_the_ground(self):
        base_z = self.z_of(self.joints["footprint_joint"])
        radius = float(self.r.find(".//link[@name='left_wheel']//cylinder").get("radius"))
        self.assertAlmostEqual(base_z + self.z_of(self.joints["left_wheel_joint"]) - radius, 0.0)
        c_r = float(self.r.find(".//link[@name='front_caster']//sphere").get("radius"))
        self.assertAlmostEqual(base_z + self.z_of(self.joints["front_caster_joint"]) - c_r, 0.0)
        self.assertAlmostEqual(base_z + self.z_of(self.joints["rear_caster_joint"]) - c_r, 0.0)

    def test_parts(self):
        self.assertEqual({j.get("type") for j in (self.joints["left_wheel_joint"], self.joints["right_wheel_joint"])},
                         {"continuous"})
        sensors = [s.get("type") for s in self.r.iter("sensor")]
        self.assertIn("camera", sensors)

    def test_inertia_is_physically_valid(self):
        for link in self.r.iter("link"):
            inertial = link.find("inertial")
            if inertial is None:
                continue
            i = inertial.find("inertia")
            ixx, iyy, izz = (float(i.get(k)) for k in ("ixx", "iyy", "izz"))
            # 三角不等式 ixx+iyy>=izz など
            self.assertGreaterEqual(ixx + iyy + 1e-12, izz, link.get("name"))
            self.assertGreaterEqual(ixx + izz + 1e-12, iyy, link.get("name"))
            self.assertGreaterEqual(iyy + izz + 1e-12, ixx, link.get("name"))


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PAI_RUN_DIR"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("PAI_RUN_DIR", None)
        self.tmp.cleanup()

    def test_plan_roundtrip_is_taken_once(self):
        plan = {"status": "ok", "steps": [{"action": "stop"}]}
        bridge.post_plan(plan, "abc")
        item = bridge.take_plan()
        self.assertEqual(item, {"id": "abc", "plan": plan})
        self.assertIsNone(bridge.take_plan())

    def test_inbox_waiting_does_not_consume(self):
        self.assertFalse(bridge.inbox_waiting())
        bridge.post_plan({"status": "ok", "steps": [{"action": "stop"}]}, "x")
        self.assertTrue(bridge.inbox_waiting())
        self.assertTrue(bridge.inbox_waiting())  # 読むだけでは消えない
        bridge.take_plan()
        self.assertFalse(bridge.inbox_waiting())

    def test_pose_roundtrip_and_staleness(self):
        self.assertIsNone(bridge.read_pose())
        bridge.write_pose(1.0, -2.0, 90.0)
        self.assertEqual(bridge.read_pose(), (1.0, -2.0, 90.0))
        self.assertIsNone(bridge.read_pose(max_age_s=-1))

    def test_status_follow_ignores_partial_line(self):
        off = bridge.status_offset()
        bridge.append_status({"event": "a"})
        with open(os.path.join(self.tmp.name, "exec_status.jsonl"), "ab") as f:
            f.write(b'{"event": "b"')  # 改行前(書き込み途中)
        events, off2 = bridge.read_status_since(off)
        self.assertEqual([e["event"] for e in events], ["a"])
        with open(os.path.join(self.tmp.name, "exec_status.jsonl"), "ab") as f:
            f.write(b'}\n')
        events, _ = bridge.read_status_since(off2)
        self.assertEqual([e["event"] for e in events], ["b"])


if __name__ == "__main__":
    unittest.main()
