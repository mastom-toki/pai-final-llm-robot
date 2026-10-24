#!/usr/bin/env python3
"""実行ノード(コンテナ内、ROS2 Humble)。

  - /odom(世界座標)を購読し、計画(steps)を /cmd_vel に落として実行する(pai_core.motion.PlanRunner)。
  - 計画は run/plan_inbox.json で受け取る(ホストの ask.py が書く)。実行前に Validator で必ず再検証する
    (LLMも計画器も信用しない: 現在姿勢を起点に検証し、NGなら実行せず rejected を返す)。
  - 状態は run/pose.json(0.5秒ごと)と run/exec_status.jsonl に書く。
  - /estop(std_msgs/Bool)で即停止。odomが1秒途絶えたら停止。

  - 待機中(計画を実行していない間)は Gazebo の物理を一時停止してCPUを空ける(LLMの推論を速くするため)。
    PAI_PAUSE_IDLE=0 で無効。タイマーは実時間(wall-clock)で動かす(物理停止中は /clock が止まるため)。

起動: python3 sim/nodes/executor_node.py --ros-args -p use_sim_time:=true
"""
import math
import os
import sys
import time

ROOT = os.environ.get("PAI_ROOT") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "sim"))

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.clock import Clock, ClockType  # noqa: E402
from rclpy.node import Node  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402
from std_srvs.srv import Empty  # noqa: E402

import validator as V  # noqa: E402
from pai_core import bridge  # noqa: E402
from pai_core.motion import Cmd, PlanRunner, Pose  # noqa: E402


def yaw_from_quat(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class Executor(Node):
    def __init__(self):
        super().__init__("pai_executor")
        self.lm = V.load_landmarks(os.path.join(ROOT, "landmarks.yaml"))
        self.positions = V._positions(self.lm)
        self.pose = None
        self.last_odom = 0.0
        self.runner = None
        self.plan_id = None
        self.pub = self.create_publisher(Twist, "cmd_vel", 10)
        self.create_subscription(Odometry, "odom", self.on_odom, 10)
        self.create_subscription(Bool, "estop", self.on_estop, 10)
        # 物理停止中は /clock が止まる → タイマーは実時間で回す(制御の時刻 now() は従来どおり sim time)
        wall = Clock(clock_type=ClockType.SYSTEM_TIME)
        self.create_timer(0.05, self.tick, clock=wall)           # 20Hz
        self.create_timer(0.5, self.housekeeping, clock=wall)    # pose.json / 受信箱 / 一時停止の判断
        self.pause_idle = os.environ.get("PAI_PAUSE_IDLE", "1") != "0"
        self.pause_cli = self.create_client(Empty, "/pause_physics")
        self.unpause_cli = self.create_client(Empty, "/unpause_physics")
        self.paused = False
        self.idle_since = time.time()
        self.get_logger().info(f"executor ready (ROOT={ROOT}, run={bridge.run_dir()})")

    def now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    # --- 入力 ---
    def on_odom(self, msg: Odometry):
        p = msg.pose.pose
        self.pose = Pose(p.position.x, p.position.y, yaw_from_quat(p.orientation))
        self.last_odom = self.now()

    def on_estop(self, msg: Bool):
        if msg.data and self.runner is not None:
            self.emit_all(self.runner.abort("estop"))
            self.stop_runner()

    # --- 出力 ---
    def emit(self, ev: dict):
        ev = dict(ev, id=self.plan_id, t=round(time.time(), 2))
        if self.pose is not None:
            ev["pose"] = [round(self.pose.x, 2), round(self.pose.y, 2), round(math.degrees(self.pose.yaw), 1)]
        bridge.append_status(ev)
        self.get_logger().info(str(ev))

    def emit_all(self, events):
        for ev in events:
            self.emit(ev)

    def publish_cmd(self, cmd: Cmd):
        m = Twist()
        m.linear.x = float(cmd.v)
        m.angular.z = float(cmd.w)
        self.pub.publish(m)

    def stop_runner(self):
        self.runner = None
        self.publish_cmd(Cmd())
        self.idle_since = time.time()

    def set_paused(self, pause: bool):
        """Gazebo の物理を止める/再開する(応答は待たない)。"""
        if pause == self.paused:
            return
        cli = self.pause_cli if pause else self.unpause_cli
        if not cli.service_is_ready():
            return
        cli.call_async(Empty.Request())
        self.paused = pause
        self.get_logger().info("physics " + ("paused (idle)" if pause else "resumed"))

    # --- 周期処理 ---
    def tick(self):
        if self.runner is None or self.pose is None:
            return
        now = self.now()
        if now - self.last_odom > 1.0:
            self.emit_all(self.runner.abort("odom途絶(1秒)"))
            self.stop_runner()
            return
        cmd, events = self.runner.update(self.pose, now)
        self.publish_cmd(cmd)
        self.emit_all(events)
        if self.runner.done:
            self.stop_runner()

    def housekeeping(self):
        if self.pose is not None:
            bridge.write_pose(self.pose.x, self.pose.y, math.degrees(self.pose.yaw))
        # 計画が届いていれば、物理が止まっていても必ず再開する(止まったまま詰まるのを防ぐ)
        if self.paused and bridge.inbox_waiting():
            self.set_paused(False)
            self.idle_since = time.time()
        # 待機が2秒続いたら物理を一時停止(最終姿勢を見せる間は動かしたまま)。
        # 最初の /odom を受け取る前は止めない(止めると odom が来ず、計画を受け取れなくなる)
        if (self.pause_idle and self.runner is None and not self.paused and self.pose is not None
                and time.time() - self.idle_since > 2.0):
            self.set_paused(True)
        if self.runner is not None or self.pose is None:
            return
        item = bridge.take_plan()
        if item is None:
            return
        self.set_paused(False)  # 計画が来たら物理を再開(検証NGでもそのまま。次の待機で再度止まる)
        self.idle_since = time.time()
        self.plan_id = item.get("id")
        plan = item.get("plan", {})
        start = (self.pose.x, self.pose.y, math.degrees(self.pose.yaw))
        res = V.validate(plan, self.lm, start=start)
        if plan.get("status") != "ok" or not res.ok:
            self.emit({"event": "rejected", "codes": [i.code for i in res.issues] or ["NOT_OK_PLAN"]})
            return
        self.runner = PlanRunner(plan, self.positions, self.now())
        self.emit({"event": "plan_received", "steps": len(plan["steps"])})


def main():
    rclpy.init()
    node = Executor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.publish_cmd(Cmd())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
