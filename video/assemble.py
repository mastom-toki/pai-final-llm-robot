"""収録素材とカードを、字幕つきで1本の動画(1920x1080, 30fps, MP4)に組み立てる。

使い方: python -X utf8 video/assemble.py [--edit video/edit_list.json] [--out video/out/final.mp4]

edit_list.json は項目の配列。
  {"card": "cards/01_title.png", "secs": 8, "caption": "字幕"}
  {"clip": "raw/S2_exec.mp4", "ss": 3, "to": 50, "speed": 2.0, "caption": "実行(2倍速)"}
倍速(speed>1)の区間には、字幕に「◯倍速」が自動で付く(提出要件: 倍速は明記)。
同じ素材の別区間を並べれば、待機を詰める(カット)ことができる。カットした箇所は字幕で明記すること。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "C\\:/Windows/Fonts/meiryo.ttc"   # drawtext 用(コロンをエスケープ)
VF_BASE = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x12161e,fps=30,format=yuv420p"


def drawtext(textfile: str, fontsize: int = 38) -> str:
    return (f"drawtext=fontfile='{FONT}':textfile='{textfile.replace(chr(92), '/').replace(':', chr(92) + ':')}':"
            f"fontsize={fontsize}:fontcolor=white:box=1:boxcolor=0x000000B0:boxborderw=18:x=(w-text_w)/2:y=h-120")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + " ".join(cmd) + "\n" + r.stderr[-1500:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", default=os.path.join(HERE, "edit_list.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "out", "final.mp4"))
    a = ap.parse_args()
    items = json.load(open(a.edit, encoding="utf-8"))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pai_video_")
    segs = []
    for i, it in enumerate(items):
        seg = os.path.join(tmp, f"seg{i:03d}.mp4")
        cap = it.get("caption", "")
        speed = float(it.get("speed", 1.0))
        if speed > 1.0:
            cap = (cap + "  " if cap else "") + f"（{speed:g}倍速）"
        vf = VF_BASE
        if cap:
            tf = os.path.join(tmp, f"cap{i:03d}.txt")
            open(tf, "w", encoding="utf-8").write(cap)
            vf += "," + drawtext(tf, int(it.get("fontsize", 38)))
        if "card" in it:
            src = os.path.join(HERE, it["card"])
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", str(it.get("secs", 5)), "-i", src,
                 "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", seg])
        else:
            src = os.path.join(HERE, it["clip"])
            cmd = ["ffmpeg", "-y", "-loglevel", "error"]
            if "ss" in it:
                cmd += ["-ss", str(it["ss"])]
            if "to" in it:
                cmd += ["-to", str(it["to"])]
            cmd += ["-i", src, "-vf", (f"setpts=PTS/{speed}," if speed != 1.0 else "") + vf,
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", seg]
            run(cmd)
        segs.append(seg)
        print(f"[{i + 1}/{len(items)}] {it.get('card') or it.get('clip')} {('(' + cap + ')') if cap else ''}")
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write("file '" + s.replace("\\", "/") + "'\n")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", a.out])
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out],
                         capture_output=True, text=True).stdout.strip()
    print(f"wrote {a.out}  ({float(dur):.1f}s)")


if __name__ == "__main__":
    main()
