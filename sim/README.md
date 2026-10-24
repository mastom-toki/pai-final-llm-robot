# sim — 差動二輪ロボット(Gazebo Classic)と実行系

言葉の指示 → ローカルLLM(gemma4:12b) → JSON計画 → Validator → 実行(Gazebo)。構成は `../DESIGN.md` を参照。

## 構成
```
sim/
  pai_core/   ROS非依存の純Python: motion.py(制御) / planner.py(計画+再計画) / bridge.py(ホスト↔コンテナ連携)
  tools/gen_world.py   landmarks.yaml → worlds/pai_world.world を生成(座標の唯一の出典は landmarks.yaml)
  urdf/diffbot.urdf    差動二輪(本体0.40x0.24x0.10m、車輪r=0.05m・間隔0.30m、前方カメラ)
  launch/sim.launch.py Gazebo + ロボットのスポーン
  nodes/executor_node.py  コンテナ内: /odom→/cmd_vel で計画を実行(実行前にValidatorで再検証)
  nodes/ask.py            ホスト側: 指示→計画→検証→実行依頼→進捗表示(HUD)
```
`ask.py`(Ollamaのある側)と `executor_node.py`(コンテナ内)は、同じフォルダを共有して `run/` のJSONファイルで連携する。
OllamaをLAN公開しないための方式(コンテナからホストのOllamaへネットワークで届かせない)。

## 実行手順(Docker Desktop + 講義用イメージ)
ホスト(Windows)で、このリポジトリのフォルダに移動してから:
```powershell
docker run -d --name pai-sim -p 6080:80 --shm-size=1g -v "${PWD}:/pai-final" airobotbook/ros2-desktop-ai-robot-book-humble:latest
```
ブラウザで `http://localhost:6080`(noVNC のデスクトップ)を開き、コンテナ内のターミナルを2つ開く。

(手動で起動する場合。`start_sim.sh` でも同じ)
ターミナル1(Gazebo):
```bash
source /opt/ros/humble/setup.bash
cd /pai-final && python3 sim/tools/gen_world.py
ros2 launch sim/launch/sim.launch.py            # GUIなしで確認するなら gui:=false
```
ターミナル2(executor):
```bash
source /opt/ros/humble/setup.bash
python3 /pai-final/sim/nodes/executor_node.py --ros-args -p use_sim_time:=true
```
ホスト(Windows)側(Ollama で gemma4:12b-it-q4_K_M を動かしておく):
```powershell
python -X utf8 sim/nodes/ask.py "赤い箱の前まで行って止まって"
python -X utf8 sim/nodes/ask.py "青い円柱の前まで行って"        # 直進はゾーンを横切る→再計画で迂回
python -X utf8 sim/nodes/ask.py "もう少し前に"                  # 聞き返し
```
計画だけ見たいとき(executor無し): `--no-exec --start 0,0,0`。

## 動作確認の状態 (2026-10-24, Docker Desktop 4.96.3 + 講義用イメージ)
- 単体テスト(`python -X utf8 -m unittest discover -s tests`, 35件)通過。
- **Gazebo上で確認済み**: world生成→起動、ロボットのスポーン(原点)、`/odom`・`/cmd_vel`、カメラ `/front_camera/image_raw`(約10Hz、GUIなしでも描画)、
  `/gazebo/set_entity_state`・`get_entity_state`(失敗の注入に使える)、`/gazebo/model_states` に全モデル。
- **実行の実測**: 手書き計画「赤い箱の1.0m手前へ→青い円柱を向く」の到達姿勢は (-2.21, 1.84, -13.2°)。Validatorの予測 (-2.23, 1.86, -14.4°) と、位置3cm・向き1.2°差。
  迂回計画(`wp_north`経由で青い円柱へ)も完走(終点は円柱から1.03m)。executor単体の再検証も動作(直進計画を直接送ると `FORBIDDEN_ZONE` で rejected)。
  実行時間は見積りの約1.5倍(13s→21s)。
- **実機gemma連携(`docs/live-test-2026-10-24.md`)**: 4指示を完走(再計画での迂回、聞き返し、原点復帰)。ただしこのPC単独では空きメモリが足りず(空き4.4GB→0.04GBで中断)、待機アプリの物理メモリを退避して完走。LLM 1回が 92〜167秒(単独測定の約2〜3倍)。
- **未確認**: 収録(GUIあり + ffmpeg x11grab)、カメラ画像を使う検証(段階4)、失敗の注入、LLM待ちの短縮(物理の一時停止・プロンプト短縮)。

## 起動・停止(コンテナ内)
```bash
bash /pai-final/sim/scripts/start_sim.sh false   # false=GUIなし / true=GUIあり(収録)
bash /pai-final/sim/scripts/stop_sim.sh
```
手書きの計画で動作確認: `python -X utf8 sim/nodes/ask.py "確認" --plan-json '{"status":"ok","steps":[...]}'`

## 収録・動画
`video/storyboard.md` を参照(収録 `video/record_exec.sh`、カード `video/make_cards.py`、編集 `video/assemble.py`)。
コンテナから Windows の Ollama へは `--host http://host.docker.internal:11434` で届く(`record_exec.sh ... live` が使う)。
LLMを使うときは、ホスト側で `python -X utf8 sim/scripts/mem_guard.py` を並走させるとメモリ不足の保険になる。

## 注意
- `run/`(実行時のファイル)と `logs/` は公開しない(`.gitignore` 済み)。
- 公開リポジトリに載せる前に、氏名・アカウント名・実パスが含まれていないか確認する(`docs/` の作業記録を含む)。
