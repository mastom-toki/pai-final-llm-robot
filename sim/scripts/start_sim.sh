#!/usr/bin/env bash
# コンテナ内で実行: world生成 → Gazebo → executor を起動する。ログは /pai-final/logs。
# 使い方: bash /pai-final/sim/scripts/start_sim.sh [true|false]   (引数はGazebo GUIの有無。既定 true)
set -e
source /opt/ros/humble/setup.bash
export DISPLAY=${DISPLAY:-:0}
cd /pai-final
mkdir -p logs run
python3 sim/tools/gen_world.py
GUI=${1:-true}
nohup ros2 launch sim/launch/sim.launch.py gui:=$GUI > logs/gazebo.log 2>&1 &
echo $! > run/gazebo.pid
# ロボットがスポーンして /odom が出るまで待つ(最大3分)
for i in $(seq 1 90); do
  if ros2 topic list 2>/dev/null | grep -q '^/odom$'; then break; fi
  sleep 2
done
nohup python3 sim/nodes/executor_node.py --ros-args -p use_sim_time:=true > logs/executor.log 2>&1 &
echo $! > run/executor.pid
sleep 3
echo "started (gui=$GUI). topics:"
ros2 topic list
