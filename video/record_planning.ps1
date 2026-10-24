# 計画シーンの収録(Windows側)。LLMが計画を作る様子(HUD)だけを、専用の端末ウィンドウから録る。
# ウィンドウ単体を録るので、通知・タスクバー・他のアプリは映らない。端末にパスは出ない。
# 実行はしない(--no-exec)。計画は logs/ask_log.jsonl に残り、実行シーンで --replay により再利用する。
# 使い方: powershell -File video\record_planning.ps1 -Name S2_plan -Text "青い円柱の前まで行って" [-Secs 240] [-Prompt v3]
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [Parameter(Mandatory = $true)][string]$Text,
  [int]$Secs = 240,
  [string]$Prompt = "v4",
  [switch]$Replay   # 動作確認用: LLMを呼ばず、記録済みの計画を使う
)
$root = Split-Path $PSScriptRoot -Parent
$raw = Join-Path $PSScriptRoot "raw"
New-Item -ItemType Directory -Force $raw | Out-Null
$out = Join-Path $raw "$Name.mp4"
$env:PAI_PROMPT = $Prompt
$ask = Join-Path $root "sim\nodes\ask.py"
$mode = ""; if ($Replay) { $mode = "--replay" }
$inner = "title PAI-HUD & mode con: cols=110 lines=26 & chcp 65001 >nul & prompt $G & python -X utf8 `"$ask`" `"$Text`" --no-exec --start 0,0,0 $mode & timeout /t 5 >nul"
$p = Start-Process conhost.exe -ArgumentList "cmd.exe /c $inner" -PassThru
# HUDウィンドウが現れるまで待つ(最大20秒)
for ($i = 0; $i -lt 40; $i++) {
  if (Get-Process | Where-Object { $_.MainWindowTitle -eq "PAI-HUD" }) { break }
  Start-Sleep -Milliseconds 500
}
# ウィンドウが閉じたら gdigrab が止まる。念のため -t で上限。断片化MP4なので途中で止まっても再生できる。
$ffargs = @("-y", "-loglevel", "error", "-f", "gdigrab", "-framerate", "10", "-i", "title=PAI-HUD", "-t", "$Secs",
  "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "frag_keyframe+empty_moov", $out)
& ffmpeg @ffargs
"saved $out"
