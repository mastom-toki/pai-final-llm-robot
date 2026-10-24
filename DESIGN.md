# PAI応用編1 最終課題 設計案 (v1, Opusレビュー反映)

> 公開リポジトリに載せる前提。氏名・所属・メール・実パスを書かない。

## 1. 題材
**「言葉で指示すると、検証を通った計画だけをロボットが実行し、失敗したら立て直す」ローカルLLM駆動の移動ロボット（Gazebo / ROS2 Humble）**

流れ: 指示(日本語) → Planner(ローカルLLM, 制約付き生成) → JSON計画 → Validator(決定論) → Executor(ROS2) → Verifier → 失敗なら再計画(最大2回)。
LLMは「提案」だけ。Validator と Executor はLLMを信用しない側。

### 工夫点(サンプル「ChatGPT APIによる自然言語ロボット操作」との差分)
1. 外部APIなし。ローカル推論でオフライン動作。
2. スキーマ制約付き生成 ＋ 意味・安全検証。**スキーマ上は正しいが危険な計画**(立入禁止ゾーンを横切る直線など)をValidatorが実行前に止め、理由コードをLLMへ返して迂回で再計画させる。
3. 知覚による完了判定と、観測に基づく再計画。
4. 定量評価(オフライン20件＋オンライン、アブレーション)。
- 実用性の筋: 通信が限られる環境で、搭載側だけで安全に自律タスクを行う。

## 2. ワールドと移動方式
- `landmarks.yaml` に物体・経由点(wp_*)・立入禁止ゾーン・上限値を定義。LLMには id/kind/color だけ渡し、座標は渡さない。
- 移動は **odomで直線区間ごとに進む go-to**(Nav2は使わない)。経路が事前に決まるので、Validatorが線分とゾーン多角形の交差で決定論的に判定できる。
- 障害(ゾーン)を挟む物体(blue_cylinder)は、直線では NG → `wp_north`/`wp_south` 経由の迂回計画を作る必要がある。これが閉ループの見せ場。

## 3. スキーマ(2層)
- **生成用 `schema/plan.schema.json`**: 構造とenumだけ。`status` と各stepは `anyOf`＋`const`。範囲や項目間の関係は入れない(ソルバが `if/then`・`minimum` を無視しても壊れない)。target enum は landmarks から実行時に差し替え。
- **検証 = Validator(コード)**: 範囲・意味・安全は全部ここ。`expect` はLLMに出させず、action から導く(例: move_to なら「targetが視野にあり stop_distance±許容差」)。
- action: `move_to{target,stop_distance_m}` / `rotate_to_face{target}` / `rotate{angle_deg}` / `wait{seconds}` / `stop`。target は物体 or 経由点の id。
- 生成ランタイム選定後、**`if/then` 等に頼った違反出力を1回わざと試し、強制されるかを確認**する。

## 4. Validator
1. 構文: 生成スキーマ適合(通常は生成時点で満たす)。
2. 意味: target存在、範囲(`limits`)、到達可能性、ステップ数。
3. 安全: 各 move_to の直線区間 × forbidden_zones、停止点の壁マージン、総距離・総時間。
- NG時は理由コード(`FORBIDDEN_ZONE`/`UNKNOWN_TARGET`/`STEP_LIMIT`/`WALL_MARGIN`/`DISTANCE_LIMIT`/`RANGE`)＋該当step を返す。

## 5. 閉ループ(失敗の作り方を設計に入れる)
- 再計画の入力: 失敗理由(コード)、実行済みstep、Verifierが観測した物体位置。
- 実行時の失敗: ①Gazeboのサービスで物体を動かす ②`landmarks.yaml` の座標をわざとずらす。失敗後は **観測位置でランドマーク推定座標を更新してから再計画**(更新しないと同じ座標へ向かい同じ失敗を繰り返す)。
- Verifier: まず色セグメンテーション＋深度。余力があれば物体検出モデルに差し替え。

## 6. 段階(保険は「この設計の最小版」。10/26必達は段階1)
| 段階 | 内容 | 目標 |
|---|---|---|
| 1 | 指示→LLM→JSON→Validator(構文・意味)→直線go-to→成功動画1本。完了判定はGazeboの真の座標でよい | **10/26** |
| 2 | clarify / reject の場面 | 10/27 |
| 3 | オフライン評価の表(Gazebo不要: 指示→Planner→Validatorのみ) | 10/27 |
| 4 | カメラVerifier・失敗注入・再計画 | 10/28 |
| 5 | シミュレータ上のアブレーション(オンライン、本数を絞り自動リセット) | 10/28 |

段階1〜3だけでも「検証層で危険な計画を止める」という工夫点は書ける。

## 7. 評価
- **オフライン**(`eval/cases.yaml` 20件: 通常12/曖昧3/危険3/複合2): スキーマ適合率、Validator通過率、危険計画の見逃し数。試行回数を増やせる。
- **オンライン**: タスク成功率、再計画回数。アブレーション=①Validatorなし ②再計画なし ③フル。
- モデル・温度・シードを固定し、再現手順をREADMEへ。

## 8. 動画(1〜3分、倍速は明記)
概要図 → 成功例 → 危険指示のreject → 失敗→再計画 → 評価表 → まとめ。画面に「指示文・LLMが出したJSON・Validator判定」を重ねる。収録はコンテナ内の仮想ディスプレイをffmpegで直接録る(通知・パスの映り込み防止。可否は起動確認時に確認)。

## 9. 実行環境と運用
- 実行: IronClaw(WSL2, Docker, RTX 5090)。GPUは他セッションと共有。
- **リポジトリの正本はIronClawのホスト側ディレクトリ**(コンテナへマウント)。ThinkPad側の `pai-final` は設計・下書きのみ。二重管理しない。
- LLMランタイムはコンテナで動かす(sudo不要、nvidiaランタイム確認済み)。VRAM上限を設定し他セッションと共存。
- 5:00 JST確認は `nvidia-smi --query-compute-apps=pid,used_memory --format=csv` で他プロセスの有無を見る。
- 起動確認で確かめる前提: Gazeboの種類、使える移動ロボット(なければTurtleBot3)、カメラ/深度トピック、物体を動かすサービス。欠けたら設計を直す。

### 起動確認の結果(10/23 05:0x JST, IronClaw)
- コンテナ: `pai-final`(ROS2 Humble, noVNC `:6080`, 仮想ディスプレイ `:0` 1920x1080) / `pai-ollama`(Ollama 0.40.8, `127.0.0.1:11435`, RTX 5090認識, KEEP_ALIVE=2m, 同時ロード1)。
- Gazebo は **Classic**(`gazebo`/`gzserver`、`gazebo_ros`)。新Gazebo(`ign`/`gz`)も同梱。gzserver 起動と `/spawn_entity`・`/delete_entity` は確認済み。`libgazebo_ros_state.so` は存在するが `set_entity_state` サービスはワールドSDFでの設定が要る(要確認)。
- **TurtleBot3 は未同梱**。ROSのaptリポジトリ署名鍵がイメージ内で期限切れ(`EXPKEYSIG`)のため `apt install ros-humble-turtlebot3-*` は不可。鍵の更新はせず、**自前の差動二輪ロボット(URDF/SDF、gazebo_ros_diff_drive＋カメラ/深度プラグイン)**で進める案(リポジトリ自己完結で再現性も高い)。
- ffmpeg `x11grab` で `:0` の録画に成功(通知・パスの映り込みなし)。Nav2 / cv_bridge / OpenCV 4.5.4 / PyYAML は同梱。`jsonschema`/`shapely` は未導入(Validatorは標準ライブラリ+PyYAMLのみで実装)。
- Validator(`src/validator.py`)と単体テスト12件が通過(ローカル・コンテナ両方)。テストでワールド設計の不備(赤い箱が直線でゾーンを横切る)を発見し、`red_box` を (-3.0, 2.5) へ移動。

## 10. スケジュール
- 10/23 05:00 JST〜: GPU空き確認 → pull(ROS2+LLMランタイムを1回の承認にまとめる) → 起動確認。
- 〜10/26: 段階1。〜10/28: 段階2〜5。10/29: 動画・README・レポートPDF・個人情報の最終チェック。10/30 14:00: 提出。

## 11. 未決
GitHubアカウント(別途指示)、omnicampusアカウントID、LLMモデル(Web調査はChatGPT)、再提出の可否(提出口で確認)。

## 12. 実装の状況 (2026-10-24, sim/)
- 実行環境: ThinkPad + Docker Desktop(講義用イメージ)。IronClaw は使わない。LLM は ThinkPad の Ollama(CPU。計画1回 約40秒、`docs/local-cpu-measure-2026-10-24.md`)。動画は待ち時間を倍速(明記)で混ぜる。
- **ホスト↔コンテナはファイル連携**(`sim/pai_core/bridge.py`): OllamaをLAN公開せずに済む。`ask.py`(ホスト) が `run/plan_inbox.json` へ書き、コンテナ内 `executor_node.py` が取り込んで実行、`run/pose.json` と `run/exec_status.jsonl` で状態を返す。
- executor は実行前に **現在姿勢を起点に Validator で再検証**する(計画器もLLMも信用しない)。
- 再計画の方針(ベンチより保守的): FORBIDDEN_ZONE / WALL_MARGIN だけ再計画。RANGE・UNKNOWN_TARGET など「指示を変えないと直らない」違反は黙って直さず実行しない(h19の経験)。
- 制御(`sim/pai_core/motion.py`)は Validator と同じ意味論で、単体テストで「Validatorの予測姿勢に到達する」ことを確認済み。
- world は `landmarks.yaml` から `sim/tools/gen_world.py` で生成(座標の唯一の出典)。
- 単体テスト 35件が通過。**Gazebo上の実挙動を確認済み**(スポーン、cmd_vel追従、カメラ10Hz、set_entity_state、迂回の完走、executorの再検証)。到達姿勢はValidatorの予測と位置3cm・向き1.2°差。詳細は sim/README.md。
- **実機gemma連携を確認済み**(`docs/live-test-2026-10-24.md`): 迂回の再計画・聞き返し・原点復帰を完走。メモリは、待機アプリの物理メモリ退避で収まる(退避なしだと空き0.04GBで中断)。LLM 1回が 92〜167秒と遅く、収録は計画区間と実行区間を分けて編集する前提。
- **未確認**: 収録、カメラを使う検証(段階4)、失敗の注入、LLM待ちの短縮。

## 13. 待機を減らす改善と収録 (2026-10-24 夕)
- executor: 待機中は Gazebo の物理を一時停止(最初の /odom を受けるまでは止めない。計画が届けば必ず再開)。タイマーは実時間(wall-clock)。
- プロンプト短縮 v4(1003→588文字): 未使用の `heldout2` で v3 18/17 → v4 19/19(誤通過0)。v4 を既定に(`docs/prompt-v4-2026-10-24.md`)。
- LLM待ち(ライブ、GUIあり、v4+物理停止): **87.2秒 / 再計画 69.4秒**(以前は v3 で 167秒 / 96秒)。単独測定(55秒 / 32秒)にはまだ届かない。残りの要因はメモリ圧迫(空き約5GB)とCPU競合とみられる。
- 計画シーンもコンテナ内で録れる: Docker Desktop の `host.docker.internal` でコンテナからWindowsのOllamaに届く(ファイル連携は併用)。収録の段取りは `video/storyboard.md`。
