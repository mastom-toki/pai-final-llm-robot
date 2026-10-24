#!/usr/bin/env bash
# コンテナ内で実行: start_sim.sh で起動したものを止める。
cd /pai-final
for f in run/executor.pid run/gazebo.pid; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
  rm -f "$f"
done
pkill -f gzserver 2>/dev/null || true
pkill -f gzclient 2>/dev/null || true
echo stopped
