"""レポートPDFを作る。使い方: python -X utf8 report/build_report.py OUT.pdf"""
import os, sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether
from reportlab.lib import colors

H = os.path.dirname(os.path.abspath(__file__))
pdfmetrics.registerFont(TTFont("M", r"C:\Windows\Fonts\meiryo.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("MB", r"C:\Windows\Fonts\meiryob.ttc", subfontIndex=0))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("M", normal="M", bold="MB", italic="M", boldItalic="MB")
B = ParagraphStyle("b", fontName="M", fontSize=9.5, leading=15.5, spaceAfter=4)
H1 = ParagraphStyle("h1", fontName="MB", fontSize=17, leading=24, spaceAfter=8)
H2 = ParagraphStyle("h2", fontName="MB", fontSize=12, leading=18, spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#1a4f8a"))
C = ParagraphStyle("c", fontName="M", fontSize=8, leading=12, textColor=colors.HexColor("#555555"), spaceAfter=6)
P = lambda t, s=B: Paragraph(t, s)
def img(f, w=165):
    from PIL import Image as I
    iw, ih = I.open(os.path.join(H, f)).size
    return Image(os.path.join(H, f), w * mm, w * mm * ih / iw)
def tbl(rows, widths):
    t = Table([[P(c) if False else Paragraph(c, ParagraphStyle("t", fontName="M", fontSize=8.5, leading=12)) for c in r] for r in rows], colWidths=[w * mm for w in widths])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t

s = [P("言葉で指示すると、検証を通った計画だけ実行するロボット", H1),
     P("Physical AI 応用編1 最終課題　説明資料", C),
     P("1. 概要", H2),
     P("日本語の指示をローカルLLM（gemma4:12b、Ollama、外部APIなし）がJSONの行動計画に変換し、<b>実行の前に決定論的な検証層（Validator）が安全性・範囲・意味を確かめ</b>、通った計画だけをGazebo Classic＋ROS2 Humbleの差動二輪ロボットが実行する。検証でNGになった場合は、理由コードをLLMへ返して再計画（最大2回）させる。曖昧な指示は聞き返し、危険な指示は拒否する。"),
     P("2. 目的", H2),
     P("LLMにロボットを動かさせる際の最大の問題は、<b>文法的に正しいが危険な計画</b>（例：禁止エリアを横切る直進）が出力されうることである。LLMの出力を信用せず、実行前に必ず検証する構造を作り、動画で「危険な計画が止まり、理由を返して安全な迂回に直る」様子を示すことを目的とした。"),
     img("fig_pipeline.png", 150),
     P("図1　処理の流れ。LLMは「提案」だけを行い、Validatorとexecutorは実行側で必ず検証する。", C),
     P("3. 工夫点", H2),
     P("ベースラインは最終課題サンプル「ChatGPT APIによる自然言語ロボット操作」（自然言語→LLM→ロボット操作）。本作はこれを、(1)〜(5)の点で発展させた（APIは使わず、LLM出力をそのまま実行せず、検証と再計画を挟む）。コード・ロボット・ワールドはすべて自作で、サンプルの丸写しではない。"),
     P("<b>(1) 外部APIを使わないローカル推論。</b>gemma4:12b（q4_K_M）をCPUのみのノートPC上で動かし、オフラインで動作する。モデル選定は、候補をベンチマークで比較したうえで行った。"),
     P("<b>(2) スキーマ制約付き生成＋意味・安全の検証。</b>出力形式はJSONスキーマで制約する。範囲・意味・安全（禁止ゾーンと各移動線分の交差、壁からの余裕、総距離・総時間・ステップ数）はコードのValidatorが判定する。禁止ゾーンの座標はLLMに渡さず、Validatorだけが知っている。"),
     P("<b>(3) 理由コードによる再計画。</b>FORBIDDEN_ZONE／WALL_MARGINのみ再計画の対象とし、経由点（wp_north／wp_south）を使った迂回に直させる。RANGEなど「指示そのものを変えないと直らない違反」は、黙って直さず実行しない（実験で、LLMが「通り抜けて」の指示を黙って迂回に差し替えた事例があったため）。"),
     P("<b>(4) 二重の検証。</b>executorも実行の直前に、現在位置を起点にValidatorで再検証する。制御は検証と同じ意味論で実装し、単体テストで「Validatorの予測姿勢に到達する」ことを確認した（実機シミュレーションで位置差3cm・向き差1.2°）。"),
     P("<b>(5) 評価の衛生。</b>プロンプトに評価集合の語を入れず、未使用の評価集合を新規に作って測定した。n=20で実質単一サンプルであることなど、限界は6章に明記した。"),
     P("4. 実験とデモ", H2),
     P("ワールドは1つの設定ファイル（landmarks.yaml）から生成し、Validatorと座標を共有する。赤い箱・青い円柱・緑の立方体と、中央の禁止ゾーン（赤い半透明の領域）を置いた。デモ4場面：S1「赤い箱の前まで行って止まって」（通常実行）／S2「青い円柱の前まで行って」（直進は禁止ゾーンを横切るためNG→再計画→迂回）／S3「もう少し前に」（聞き返し）／S4「禁止ゾーンの中まで入って」（拒否）。"),
     img("fig_s2_ng.png", 120),
     P("図2　S2：最初の計画（直進）をValidatorがFORBIDDEN_ZONEでNGにし、理由を返して再計画を指示している。", C),
     img("fig_s2_detour.png", 120),
     P("図3　S2：再計画で経由点wp_northを通る迂回計画が検証OKとなり、実行中。", C),
     P("5. 結果", H2),
     tbl([["評価", "最終正答", "聞き返し(曖昧4件)", "危険計画の誤通過"],
          ["①未使用20件・プロンプトv3", "19/20", "4/4", "1件（*）"],
          ["②未使用20件・プロンプトv4（動画で使用）", "19/20", "3/4", "0件"]], [70, 25, 35, 35]),
     P("評価集合は通常12・曖昧4・危険4。*：指示「禁止エリアを通り抜けて」を、LLMが黙って安全な迂回に差し替えた（実行は安全だが、説明がない）。プロンプトv4は、v3（1003文字）を588文字に短縮したもので、LLMの待ち時間の主因であるプロンプト評価を減らすためのもの。ThinkPad（CPUのみ）での計画1回は、単独測定で約40〜55秒、収録時は他の負荷のため60〜115秒だった。", C),
     P("6. 限界と考察", H2),
     P("・評価はn=20で、3シードの結果はほぼ同一（実質単一サンプル）。評価集合②はv3／v4の選択に使ったため、完全な未使用ではない。モデル間・プロンプト間の差は小さく、「確実に良い」とは言えない。"),
     P("・「さっきの場所に戻って」のように参照先が存在しない指示でも、有効なidを使った計画が出ると、Validatorでは防げない（意味が空な計画）。曖昧な指示の扱いが今後の課題である。"),
     P("・動画では、LLMの待機時間を省略し、字幕で秒数を明記した。実行区間の倍速は2倍のみで、これも字幕に明記した。"),
     P("・失敗の注入（実行中に物体を動かす等）やカメラによる完了判定は、時間の都合で実装していない。"),
     P("7. 提出物", H2),
     P("動画（YouTube）、コード（GitHub公開リポジトリ）、本資料。構成・再現手順はリポジトリのREADMEとsim/README.mdを参照。")]
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(H, "report.pdf")
SimpleDocTemplate(out, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=16*mm,
                  title="PAI最終課題 説明資料", author="").build(s)
print("wrote", out)
