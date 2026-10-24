#!/usr/bin/env python3
"""landmarks.yaml から Gazebo Classic の world(SDF 1.6)を生成する。

座標の二重管理を避けるため、世界の物体・経由点・立入禁止ゾーン・壁はすべて landmarks.yaml が唯一の出典。
使い方: python3 sim/tools/gen_world.py [--landmarks landmarks.yaml] [--out sim/worlds/pai_world.world]
"""
from __future__ import annotations

import argparse
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

WALL_HALF = 6.0       # Validator の WALL_HALF_SIZE_M と同じ(壁の内側の面)
WALL_T = 0.10         # 壁の厚み
WALL_H = 0.50
MATERIAL = {"red": "Gazebo/Red", "blue": "Gazebo/Blue", "green": "Gazebo/Green"}


def _material(name: str) -> str:
    return (f"<material><script><uri>file://media/materials/scripts/gazebo.material</uri>"
            f"<name>{name}</name></script></material>")


def _static_model(name, x, y, z, sx, sy, sz, mat, collision=True) -> str:
    col = f"<collision name='c'><geometry><box><size>{sx} {sy} {sz}</size></box></geometry></collision>" if collision else ""
    return (f"<model name='{name}'><static>true</static><pose>{x} {y} {z} 0 0 0</pose><link name='l'>{col}"
            f"<visual name='v'><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>{_material(mat)}</visual>"
            f"</link></model>")


def _object_model(o: dict) -> str:
    kind, m = o["kind"], 10.0
    mat = MATERIAL.get(o["color"], "Gazebo/Grey")
    if kind == "cylinder":
        r, h = 0.25, 0.5
        geom = f"<cylinder><radius>{r}</radius><length>{h}</length></cylinder>"
        ixx = m / 12 * (3 * r * r + h * h)
        izz = 0.5 * m * r * r
        inertia = f"<ixx>{ixx:.4f}</ixx><iyy>{ixx:.4f}</iyy><izz>{izz:.4f}</izz>"
        z = h / 2
    else:  # box / cube
        s = 0.4
        geom = f"<box><size>{s} {s} {s}</size></box>"
        i = m / 6 * s * s
        inertia = f"<ixx>{i:.4f}</ixx><iyy>{i:.4f}</iyy><izz>{i:.4f}</izz>"
        z = s / 2
    return (f"<model name='{o['id']}'><pose>{o['x']} {o['y']} {z} 0 0 0</pose><link name='l'>"
            f"<inertial><mass>{m}</mass><inertia>{inertia}</inertia></inertial>"
            f"<collision name='c'><geometry>{geom}</geometry></collision>"
            f"<visual name='v'><geometry>{geom}</geometry>{_material(mat)}</visual></link></model>")


def _waypoint_model(w: dict) -> str:
    return (f"<model name='{w['id']}'><static>true</static><pose>{w['x']} {w['y']} 0.005 0 0 0</pose><link name='l'>"
            f"<visual name='v'><geometry><cylinder><radius>0.15</radius><length>0.01</length></cylinder></geometry>"
            f"{_material('Gazebo/Yellow')}</visual></link></model>")


def _zone_model(z: dict) -> str:
    xs = [p[0] for p in z["polygon"]]
    ys = [p[1] for p in z["polygon"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if len(z["polygon"]) != 4 or any(p[0] not in (x0, x1) or p[1] not in (y0, y1) for p in z["polygon"]):
        raise ValueError("forbidden_zones は軸平行の長方形のみ対応")
    return _static_model(z["id"], (x0 + x1) / 2, (y0 + y1) / 2, 0.005, round(x1 - x0, 4), round(y1 - y0, 4), 0.01,
                         "Gazebo/RedTransparent", collision=False)


def generate(lm: dict) -> str:
    parts = []
    # 壁(内側の面が ±WALL_HALF になるように置く)
    c = WALL_HALF + WALL_T / 2
    length = 2 * WALL_HALF + 2 * WALL_T
    for name, x, y, sx, sy in (("wall_n", 0, c, length, WALL_T), ("wall_s", 0, -c, length, WALL_T),
                               ("wall_e", c, 0, WALL_T, length), ("wall_w", -c, 0, WALL_T, length)):
        parts.append(_static_model(name, x, y, WALL_H / 2, sx, sy, WALL_H, "Gazebo/Grey"))
    parts += [_object_model(o) for o in lm["objects"]]
    parts += [_waypoint_model(w) for w in lm["waypoints"]]
    parts += [_zone_model(z) for z in lm.get("forbidden_zones", [])]
    body = "\n    ".join(parts)
    return f"""<?xml version="1.0"?>
<!-- 自動生成: sim/tools/gen_world.py (landmarks.yaml が出典。直接編集しない) -->
<sdf version="1.6">
  <world name="pai_world">
    <include><uri>model://sun</uri></include>
    <include><uri>model://ground_plane</uri></include>
    <physics type="ode">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>
    <plugin name="gazebo_ros_state" filename="libgazebo_ros_state.so">
      <ros><namespace>/gazebo</namespace></ros>
      <update_rate>1.0</update_rate>
    </plugin>
    <gui><camera name="user_camera"><pose>0 -11 10 0 0.8 1.5708</pose></camera></gui>
    {body}
  </world>
</sdf>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landmarks", default=os.path.join(ROOT, "landmarks.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "sim", "worlds", "pai_world.world"))
    a = ap.parse_args()
    with open(a.landmarks, encoding="utf-8") as f:
        lm = yaml.safe_load(f)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(generate(lm))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
