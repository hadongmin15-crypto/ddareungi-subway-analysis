"""PPT용 그래프 png 저장 — notebooks/figures.ipynb 셀 코드를 그대로 실행하고 plt.show() 대신 저장 (dpi 200)."""
# %% [6-0] 설정
import json
import os
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks' / 'figures.ipynb'
FIGURES = ROOT / 'outputs' / 'figures'
FIGURES.mkdir(parents=True, exist_ok=True)
DPI = 200
NAMES = {'1': '00_bike_monthly', '2-1': '01_map_seoul', '2-2': '01_map_zoom', '3': '02_overview',
         '4': '03_trip_types', '5': '04_hyp1_scatter', '6': '05_hyp1_bar', '7': '06_hyp2_hourly',
         '8': '07_top10', '9': '08_hyp2_share_bar', '10': '09_hyp2_scatter', '11': '10_robustness_rho',
         '12': '11_hyp1_dist', '13': '12_hyp2_dist'}

# %% [6-1] 노트북 셀을 차례로 실행하며 그래프 저장
os.chdir(ROOT)
cells = [''.join(c['source']) for c in json.loads(NOTEBOOK.read_text(encoding='utf-8'))['cells']
         if c['cell_type'] == 'code']
namespace = {}
for src in cells:
    tag = re.match(r'# \[([\d-]+)\]', src).group(1)
    if tag in NAMES:
        out = FIGURES / f'{NAMES[tag]}.png'
        src = src.replace('plt.show()', f"fig.savefig(r'{out}', dpi={DPI}, facecolor='white'); plt.close('all')")
    exec(compile(src, f'cell[{tag}]', 'exec'), namespace)
    if tag in NAMES:
        print(f'저장: [{tag}] → {out.name}')
