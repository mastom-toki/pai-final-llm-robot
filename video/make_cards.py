"""動画に挟む静止画カード(タイトル・構成図・結果・まとめ)を PIL で作る。1920x1080。
氏名・所属・メール・アカウント名・実パスは載せない。
使い方: python -X utf8 video/make_cards.py [--results "19/20" ...]   → video/cards/*.png
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cards")
W, H = 1920, 1080
FONT = r"C:\Windows\Fonts\meiryo.ttc"
FONT_B = r"C:\Windows\Fonts\meiryob.ttc"
BG, FG, SUB, ACC, OK, NG = (18, 22, 30), (240, 244, 250), (160, 172, 190), (90, 170, 255), (90, 200, 130), (240, 110, 100)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def center(d, y, text, f, fill=FG):
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def box(d, x, y, w, h, text, sub=None, color=ACC):
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, outline=color, width=4, fill=(26, 32, 44))
    f = font(34, True)
    tw = d.textlength(text, font=f)
    d.text((x + (w - tw) / 2, y + (h / 2 - 30 if sub else h / 2 - 22)), text, font=f, fill=FG)
    if sub:
        fs = font(24)
        sw = d.textlength(sub, font=fs)
        d.text((x + (w - sw) / 2, y + h / 2 + 12), sub, font=fs, fill=SUB)


def arrow(d, x1, y1, x2, y2, color=SUB):
    d.line([x1, y1, x2, y2], fill=color, width=5)
    d.polygon([(x2, y2), (x2 - 18, y2 - 11), (x2 - 18, y2 + 11)] if x2 > x1 else
              [(x2, y2), (x2 - 11, y2 + 18), (x2 + 11, y2 + 18)], fill=color)


def title():
    img, d = canvas()
    center(d, 330, "言葉で指示すると、", font(78, True))
    center(d, 430, "検証を通った計画だけ実行するロボット", font(78, True), ACC)
    center(d, 590, "ローカルLLM (gemma4:12b) + 検証層 (Validator) + Gazebo", font(40), SUB)
    center(d, 660, "Physical AI 応用編1 最終課題", font(36), SUB)
    center(d, 900, "※ LLM推論の待ち時間は省略し、字幕で明記しています", font(30), (200, 190, 120))
    img.save(os.path.join(OUT, "01_title.png"))


def pipeline():
    img, d = canvas()
    center(d, 70, "しくみ：LLMは「提案」だけ。実行の前に必ず検証する", font(52, True))
    y, h, w = 360, 170, 300
    xs = [60, 430, 800, 1170, 1540]
    labels = [("日本語の指示", "例「青い円柱の前まで」"), ("ローカルLLM", "gemma4:12b / CPU"),
              ("JSON計画", "action と target だけ"), ("Validator", "ゾーン・範囲・壁・距離"),
              ("ロボット", "Gazebo / ROS2")]
    colors = [ACC, ACC, ACC, OK, ACC]
    for x, (a, b), c in zip(xs, labels, colors):
        box(d, x, y, w, h, a, b, c)
    for i in range(4):
        arrow(d, xs[i] + w + 6, y + h / 2, xs[i + 1] - 6, y + h / 2)
    # 再計画ループ(Validator → LLM)
    d.line([xs[3] + w / 2, y + h + 6, xs[3] + w / 2, y + h + 110, xs[1] + w / 2, y + h + 110, xs[1] + w / 2, y + h + 8],
           fill=NG, width=5)
    d.polygon([(xs[1] + w / 2, y + h + 6), (xs[1] + w / 2 - 11, y + h + 24), (xs[1] + w / 2 + 11, y + h + 24)], fill=NG)
    center(d, y + h + 125, "NG なら理由コードを返して再計画（例：禁止ゾーンを横切る → 経由点で迂回）", font(34), NG)
    center(d, 820, "禁止ゾーンの場所はLLMに教えない。Validatorだけが知っていて、危険な計画を実行前に止める。", font(34), SUB)
    center(d, 880, "executor も実行の直前に、現在の位置からもう一度検証する。", font(34), SUB)
    img.save(os.path.join(OUT, "02_pipeline.png"))


def results(rows, foot=None):
    img, d = canvas()
    center(d, 70, "評価：未使用の指示20件（通常12・曖昧4・危険4）", font(52, True))
    f, fb = font(36), font(36, True)
    y = 230
    for label, val, ok in rows:
        d.text((150, y), label, font=f, fill=FG)
        d.text((1130, y), val, font=fb, fill=OK if ok else NG)
        y += 78
    if foot:
        center(d, 790, foot, font(28), (200, 190, 120))
    center(d, 900, "n=20・実質単一サンプル（3シードの結果はほぼ同一）。評価集合は初回使用で、見てから調整していない。", font(28), SUB)
    img.save(os.path.join(OUT, "03_results.png"))


def ending():
    img, d = canvas()
    center(d, 250, "まとめ", font(70, True))
    lines = ["・LLMの提案は、検証を通ったものだけ実行する（禁止ゾーンを横切る計画は実行されない）",
             "・失敗は理由を返して再計画。指示そのものを変える違反は、黙って直さず実行しない",
             "・計画1回は約40秒〜（CPU推論）。動画では待機を省略し、字幕で明記",
             "・限界：意味のない計画は検証層だけでは防げない（曖昧な指示の扱いが課題）"]
    y = 420
    for ln in lines:
        d.text((260, y), ln, font=font(38), fill=FG)
        y += 90
    center(d, 900, "コード・レポートは提出物を参照", font(32), SUB)
    img.save(os.path.join(OUT, "04_ending.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", nargs="*", default=None, help='"ラベル|値" を並べる(結果カード用)')
    ap.add_argument("--foot", default=None)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    title()
    pipeline()
    rows = []
    for r in (a.rows or ["最終正答（20件）|（測定後に入力）"]):
        label, _, val = r.partition("|")
        rows.append((label, val, True))
    results(rows, a.foot)
    ending()
    print("cards:", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
