#!/usr/bin/env bash
# S1〜S4 を順に収録する(ホスト側で実行。Docker Desktop とコンテナ pai-sim が起動済みであること)。
# 各シーンの前にメモリを退避し、メモリ安全装置(mem_guard)を並走させる。
cd "$(dirname "$0")/.."
python -X utf8 sim/scripts/mem_guard.py --minutes 60 > run/mem_guard.log 2>&1 &
GUARD=$!
SCENES=(
  "S1_basic|赤い箱の前まで行って止まって"
  "S2_detour|青い円柱の前まで行って"
  "S3_clarify|もう少し前に"
  "S4_reject|禁止ゾーンの中まで入って"
)
for s in "${SCENES[@]}"; do
  name="${s%%|*}"; text="${s#*|}"
  echo "=== $name: $text ($(date +%T))"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File sim/scripts/trim_idle_apps.ps1 2>&1 | tr -d '\0' | grep -E "after free"
  powershell.exe -NoProfile -Command "\$env:PATH += ';C:\Program Files\Docker\Docker\resources\bin'; docker exec pai-sim bash /pai-final/video/record_exec.sh $name '$text' live 2>&1 | tail -1" | tr -d '\0'
done
kill $GUARD 2>/dev/null
echo "ALL_SCENES_DONE $(date +%T)"
