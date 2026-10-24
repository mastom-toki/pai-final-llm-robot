#!/usr/bin/env bash
# 実行シーンの収録(コンテナ内で実行)。コンテナの画面(Gazebo GUI + HUD端末)だけを録る。
# 通知・タスクバー・個人情報は映らない。LLMは呼ばず、記録済みの計画(ask_log.jsonl)を再利用する(--replay)。
# 例: bash /pai-final/video/record_exec.sh S2_detour "青い円柱の前まで行って" replay   # 記録済みの計画を再利用(LLMなし)
#     bash /pai-final/video/record_exec.sh S2_live   "青い円柱の前まで行って" live     # 本物のLLM(Windows側のOllama)で計画→実行まで一続き
# live では、メモリ不足でWindowsが固まらないよう、ホスト側で sim/scripts/mem_guard.py を並走させること。
set -e
NAME=$1
TEXT=$2
MODE=${3:-replay}
export DISPLAY=:0
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8   # 日本語のHUDが文字化けしないように
source /opt/ros/humble/setup.bash
mkdir -p /pai-final/video/raw
OUT=/pai-final/video/raw/${NAME}.mp4
# 既存の録画は上書きしない(退避する)
[ -f "$OUT" ] && mv "$OUT" "${OUT%.mp4}.bak-$(date +%H%M%S).mp4"

# 毎回、シミュレーターを再起動してロボットを原点から始める
bash /pai-final/sim/scripts/stop_sim.sh >/dev/null 2>&1 || true
sleep 2
bash /pai-final/sim/scripts/start_sim.sh true >/dev/null
sleep 3

ffmpeg -y -loglevel error -f x11grab -framerate 20 -video_size 1920x1080 -i :0 \
  -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p "$OUT" &
FF=$!
sleep 1

if [ "$MODE" = "live" ]; then
  ASK="python3 /pai-final/sim/nodes/ask.py '$TEXT' --host http://host.docker.internal:11434 --timeout 300"
else
  ASK="python3 /pai-final/sim/nodes/ask.py '$TEXT' --replay --timeout 240"
fi

# HUDを手前に固定する(Gazeboの窓に隠れないように。コンテナを作り直した場合は wmctrl を入れ直す)
which wmctrl >/dev/null 2>&1 || (apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq wmctrl >/dev/null 2>&1) || true

xterm -u8 -geometry 118x16+0+745 -fa "DejaVu Sans Mono,Noto Sans Mono CJK JP" -fs 13 -bg black -fg "#e8e8e8" -T "HUD"   -e bash -lc "source /opt/ros/humble/setup.bash; $ASK; sleep 4" &
XT=$!
sleep 2
( while kill -0 $XT 2>/dev/null; do wmctrl -r HUD -b add,above 2>/dev/null; wmctrl -a HUD 2>/dev/null; sleep 3; done ) &
wait $XT

kill -INT $FF
wait $FF 2>/dev/null || true
echo "saved $OUT"
