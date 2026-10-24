# 言葉で指示すると、検証を通った計画だけ実行するロボット

Physical AI 応用編1 最終課題。日本語の指示をローカルLLM(gemma4:12b, Ollama)が JSON の行動計画にし、**決定論的な Validator が実行前に検証**し、通ったものだけを Gazebo Classic + ROS2 Humble の差動二輪ロボットが実行する。

```
日本語の指示 → ローカルLLM → JSON計画 → Validator → Executor(ROS2/Gazebo)
                    ▲            │NG(理由コード)
                    └─ 再計画(最大2回)
```

## 工夫点
1. 外部APIなし。ローカル推論(CPUでも動作)。
2. スキーマ制約付き生成 + **意味・安全の検証**。スキーマ上は正しいが危険な計画(禁止ゾーンを横切る、壁に近すぎる、距離超過など)を実行前に止める。禁止ゾーンの座標はLLMに渡さない。
3. FORBIDDEN_ZONE / WALL_MARGIN は理由コードを返して再計画(経由点で迂回)。指示そのものを変えないと直らない違反(RANGE等)は、黙って直さず実行しない。曖昧な指示は聞き返す(clarify)、危険な指示は拒否(reject)。
4. Executor も実行直前に現在位置から再検証する。
5. 定量評価: 未使用の指示20件(通常12・曖昧4・危険4)で最終正答 19/20、危険計画の誤通過 0(v4プロンプト)。

## 構成
| パス | 内容 |
|---|---|
| `landmarks.yaml` | 物体・経由点・禁止ゾーン・上限値(ワールドとValidatorの唯一の出典) |
| `src/validator.py` | Validator |
| `schema/` | 生成用JSONスキーマ |
| `sim/` | URDF・ワールド生成・ROS2ノード(executor, ask)・ホスト↔コンテナ連携 |
| `eval/` | 評価スクリプトと評価集合、結果 |
| `tests/` | 単体テスト |
| `docs/`, `DESIGN.md` | 設計・測定・評価の記録 |
| `video/` | 動画の編集スクリプト(収録素材は含まない) |

## 動かし方(概要)
- 単体テスト: `python -m unittest discover -s tests`
- 評価: `python eval/bench_models.py --model gemma4:12b-it-q4_K_M --cases eval/cases_heldout2.yaml --prompt v4`(Ollama が必要)
- シミュレーション: 講義用 ROS2 Humble Docker イメージ内で `sim/scripts/start_sim.sh`、ホストで `python sim/nodes/ask.py "青い円柱の前まで行って"`。詳細は `sim/README.md`。

## 限界(正直に)
- 評価は n=20、3シードの結果はほぼ同一(実質単一サンプル)。評価集合 heldout2 はプロンプト v3/v4 の選択に使ったため、完全な未使用ではない。
- 「さっきの場所に戻って」のような意味が空な計画は、有効なidを使うので Validator では防げない。
- LLM 1回は CPU で約40〜115秒。動画では待機を省略し字幕で明記した。
