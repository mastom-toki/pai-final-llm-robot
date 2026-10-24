# モデル選定: ChatGPT回答の要約と裏取り (2026-10-23)

出典: ChatGPT(Web検索あり, High)への依頼 `chatgpt-model-selection-request.md` の回答。回答は暫定評価で、Ollama 0.40.8での実測ではない。ChatGPTが挙げた個別の出典(GitHub issue等)は未再確認。

## 推奨
| 順位 | タグ | 配布サイズ(裏取り済) | 位置づけ |
|---|---|---|---|
| 1 | `qwen3.5:9b-q4_K_M` | 6.55GB | 第一候補。日本語と速度のバランス |
| 2 | `gemma4:12b-it-q4_K_M` | 8.02GB | 再計画・長い複合指示で差が出たら切替 |
| 3 | `qwen3.5:4b-q8_0` | 5.16GB | VRAM/遅延優先時 |
- 代替: `qwen3.5:4b-q4_K_M`(3.32GB)、`gemma4:12b-it-qat`(7.15GB)。除外: `gemma4:12b-it-q8_0`(13GB)。
- 裏取り: 上記タグは registry.ollama.ai のマニフェストで実在とサイズを確認(HTTP 200)。4K時の実VRAMは未測定(配布サイズ＋KV/バッファ)。
- 日本語スコア(Nejumi)は reasoning有効時の値で、本タスク(think:false+量子化)の正答率ではない。速度(220/152 tok/s)はllama.cpp単独ベンチで、Ollama+入力付き+GPU共有時の保証ではない。

## 構造化出力の注意(ChatGPT調査。要再確認)
- `format` にJSON Schemaを渡す方式は公式対応。`anyOf`+`const`+`enum` の組合せがOllama 0.40.8で完全に強制されるかは未確認 → **生成後にも必ず再検証**(我々のValidatorがその役)。
- enum/constと他制約の併用で制約が無視される報告あり(llama.cpp, 2026-10-18)。`enum`・`const` は独立した定義にし、同階層に `pattern` 等を重ねない。生成スキーマは構造+enumのみという現設計と整合。
- Qwen3.5の `think:false`+`format` 不具合は2026-07に解消確認と報告。`think:false` で開始して適合率を実測。
- `tools` ではなくトップレベル `format` を使う。

## 設計への示唆(採用判断はこちら)
1. スキーマ・プロンプト・検証器を固定してからモデル比較する(サイズより設計が先)。
2. clarify/reject/ok の判定規則を固定: clarify=対象が一意でない/角度不足、reject=対象不在/明示的な禁止行為、ok=確定(最終stepにstop)。
3. 再計画は、LLMに経由点を自由に考えさせず「許可された経由点と接続関係」を渡す。さらに堅くするなら経路探索を決定論(A*等)にして、LLMは「どの物体へ・順番」だけ決める案もある(安全性・再現性重視)。現設計は「Validatorが直線×ゾーンを検査 → 理由コード返却 → wp経由で再計画」。
4. 形式が正しくても危険な計画が通るのが最悪のシナリオ → Validator＋独立した停止条件。

## 次の手順
- 3モデルを pai-ollama へ pull(合計約20GB。承認後)し、`eval/cases.yaml` 20件でスキーマ適合率・正答率・遅延を測定。
- ChatGPTが提示した評価スクリプト(`robot_ollama_benchmark.py`)は未ダウンロード。自前のValidator/評価セットに合わせて作る方針(ダウンロードは承認制)。
