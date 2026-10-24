"""Colab用ノートブックを生成する: 評価一式をbase64で埋め込み、Ollamaを入れて v3/v4 を heldout2 で比較する。
使い方: python colab/build_notebook.py  → colab/pai_prompt_compare.ipynb
"""
import base64
import io
import json
import os
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FILES = ["src/validator.py", "schema/plan.schema.json", "landmarks.yaml", "eval/bench_models.py",
         "eval/cases.yaml", "eval/cases_heldout.yaml", "eval/cases_heldout2.yaml"]


def code(src):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": src.splitlines(True)}


def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(True)}


buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in FILES:
        z.write(os.path.join(ROOT, f), f)
b64 = base64.b64encode(buf.getvalue()).decode()

cells = [
    md("# プロンプト比較 v3 vs v4 (gemma4:12b-it-q4_K_M) — 未使用の評価集合 heldout2\n"
       "**ランタイムは GPU(T4) にして上から順に実行。** heldout2 は今回が初使用。結果を見てプロンプトを調整しない。"),
    code("!nvidia-smi --query-gpu=name,memory.total --format=csv\n"
         "import subprocess\n"
         "assert subprocess.run(['nvidia-smi'], capture_output=True).returncode == 0, 'GPUランタイムではありません'"),
    code("import base64, os, zipfile, io\n"
         f"B64 = \"{b64}\"\n"
         "os.makedirs('/content/pai-final', exist_ok=True)\n"
         "zipfile.ZipFile(io.BytesIO(base64.b64decode(B64))).extractall('/content/pai-final')\n"
         "%cd /content/pai-final\n"
         "!ls eval"),
    code("!apt-get -qq install -y zstd pciutils lshw > /dev/null 2>&1\n"
         "!curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -3\n"
         "import subprocess, time, urllib.request, os\n"
         "env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11435', OLLAMA_KEEP_ALIVE='2m', OLLAMA_MAX_LOADED_MODELS='1')\n"
         "srv = subprocess.Popen(['ollama', 'serve'], env=env, stdout=open('/content/ollama.log', 'w'), stderr=subprocess.STDOUT)\n"
         "for _ in range(60):\n"
         "    try:\n"
         "        print(urllib.request.urlopen('http://127.0.0.1:11435/api/version', timeout=2).read().decode()); break\n"
         "    except Exception: time.sleep(1)"),
    code("import os\n"
         "os.environ['OLLAMA_HOST'] = '127.0.0.1:11435'\n"
         "!ollama pull gemma4:12b-it-q4_K_M 2>&1 | tail -2\n"
         "!ollama list"),
    code("import json, subprocess, urllib.request\n"
         "req = urllib.request.Request('http://127.0.0.1:11435/api/generate', headers={'Content-Type': 'application/json'},\n"
         "    data=json.dumps({'model': 'gemma4:12b-it-q4_K_M', 'prompt': 'hi', 'stream': False, 'options': {'num_predict': 8}, 'keep_alive': '2m'}).encode())\n"
         "json.loads(urllib.request.urlopen(req, timeout=900).read())\n"
         "used = int(subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True).stdout.split()[0])\n"
         "print('GPU used MiB:', used)\n"
         "assert used > 4000, 'OllamaがGPUを使っていない(CPU実行)。ここで止める'\n"
         "print('GPU ok')"),
    code("# v3(評価済み)と v4(短縮) を heldout2 で比較。各 seed 1,2、temperature 0.3\n"
         "M = 'gemma4:12b-it-q4_K_M'\n"
         "!python3 eval/bench_models.py --model $M --cases eval/cases_heldout2.yaml --out eval/results --tag h2-v3 --prompt v3 --seeds 1,2 --temperature 0.3\n"
         "!python3 eval/bench_models.py --model $M --cases eval/cases_heldout2.yaml --out eval/results --tag h2-v4 --prompt v4 --seeds 1,2 --temperature 0.3\n"
         "print('PROMPT_COMPARE_FINISHED')"),
    code("import json, glob\n"
         "for f in sorted(glob.glob('eval/results/*.h2-v*.json')):\n"
         "    d = json.load(open(f))\n"
         "    a = d['aggregate']\n"
         "    print(a['tag'], 'correct/seed', a['correct_final_per_seed'], 'ok_correct/seed', a['ok_final_correct_per_seed'], 'unsafe', a['unsafe_pass_total'])\n"
         "    for cid, cr in d['case_rate'].items():\n"
         "        if cr['correct'] < cr['of']:\n"
         "            print('   ', cid, f\"{cr['correct']}/{cr['of']}\", cr['got'], cr['replans'])\n"
         "print('PROMPT_COMPARE_REPORT_DONE')"),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = os.path.join(ROOT, "colab", "pai_prompt_compare.ipynb")
json.dump(nb, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", out, len(b64), "base64 chars")
