"""Gazebo Classic に world を立ち上げ、差動二輪ロボットをスポーンする。

使い方(コンテナ内):
  source /opt/ros/humble/setup.bash
  python3 sim/tools/gen_world.py
  ros2 launch sim/launch/sim.launch.py            # GUIあり(収録用)
  ros2 launch sim/launch/sim.launch.py gui:=false # GUIなし(確認用)
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)


def generate_launch_description():
    gazebo_ros = get_package_share_directory("gazebo_ros")
    world = os.path.join(SIM, "worlds", "pai_world.world")
    urdf = os.path.join(SIM, "urdf", "diffbot.urdf")
    with open(urdf, encoding="utf-8") as f:
        robot_description = f.read()

    return LaunchDescription([
        DeclareLaunchArgument("gui", default_value="true"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(gazebo_ros, "launch", "gzserver.launch.py")),
            launch_arguments={"world": world, "verbose": "false"}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(gazebo_ros, "launch", "gzclient.launch.py")),
            condition=IfCondition(LaunchConfiguration("gui"))),
        Node(package="robot_state_publisher", executable="robot_state_publisher",
             parameters=[{"robot_description": robot_description, "use_sim_time": True}]),
        Node(package="gazebo_ros", executable="spawn_entity.py", output="screen",
             arguments=["-entity", "diffbot", "-file", urdf, "-x", "0", "-y", "0", "-z", "0.02"]),
    ])
