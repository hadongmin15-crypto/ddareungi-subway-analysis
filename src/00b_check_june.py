"""0단계 7번: 새로 넣은 6월 파일 4개 가볍게 점검 (대여이력은 앞부분·끝부분만 읽음).

- 인코딩, 컬럼명이 0단계 매핑표(00_trip_column_map.csv)와 같은지
- 2026 지하철 끝 빈 칸 여부
- 날짜 범위
"""
import io
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 30)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TABLES = ROOT / 'outputs' / 'tables'

PRIVATE_COLS = ['생년', '성별', '이용자종류']
HEAD_BYTES = 200_000
TAIL_BYTES = 20_000


def section(title):
    print('\n' + '=' * 90 + f'\n{title}\n' + '=' * 90)


def detect_encoding(path):
    with open(path, 'rb') as fh:
        raw = fh.read(HEAD_BYTES)
    raw = raw[: raw.rfind(b'\n')]
    try:
        raw.decode('utf-8-sig')
        return 'utf-8-sig'
    except UnicodeDecodeError:
        raw.decode('cp949')
        return 'cp949'


def read_tail(path, enc, columns, nbytes=TAIL_BYTES):
    """파일 끝 nbytes만 읽어 마지막 행들을 DataFrame으로."""
    with open(path, 'rb') as fh:
        fh.seek(max(path.stat().st_size - nbytes, 0))
        raw = fh.read()
    raw = raw[raw.find(b'\n') + 1:]  # 잘린 첫 줄 버림
    return pd.read_csv(io.StringIO(raw.decode(enc)), header=None, names=columns, dtype=str,
                       na_values=['\\N', ''], index_col=False)


column_map = pd.read_csv(TABLES / '00_trip_column_map.csv', encoding='utf-8-sig')


def expected_cols(year):
    col = 'col_2019' if year == 2019 else 'col_2026'
    return [c for v in column_map[col] for c in v.split(' / ') if c != '(없음)']


# ---------------------------------------------------------------------------
# 따릉이 대여이력 6월
# ---------------------------------------------------------------------------
section('따릉이 대여이력 6월 (앞 5행 + 끝 약 20KB)')

for year, fname in ((2019, '서울특별시 공공자전거 대여이력 정보_1906.csv'),
                    (2026, '서울특별시 공공자전거 대여이력 정보_2606.csv')):
    f = DATA / 'bike_trips' / str(year) / fname
    enc = detect_encoding(f)
    cols = list(pd.read_csv(f, encoding=enc, nrows=0).columns)
    exp = expected_cols(year)
    print(f'\n● {fname}  ({f.stat().st_size / 1024**2:,.1f} MB), 인코딩: {enc}')
    print(f'  컬럼 {len(cols)}개: {cols}')
    print(f'  매핑표에 없는 컬럼: {sorted(set(cols) - set(exp))} / 매핑표에 있는데 빠진 컬럼: {sorted(set(exp) - set(cols))}')

    use = [c for c in cols if c not in PRIVATE_COLS]
    head = pd.read_csv(f, encoding=enc, nrows=5, dtype=str, usecols=use, na_values=['\\N', ''])
    tail = read_tail(f, enc, cols)[use]
    print('  앞 5행')
    print('  ' + head.to_string(index=False).replace('\n', '\n  '))
    print('  끝 5행')
    print('  ' + tail.tail(5).to_string(index=False).replace('\n', '\n  '))
    print(f'  끝부분 {len(tail)}행 중 칸 수가 헤더와 다른 행: {(tail[cols[-1]].isna() & tail["반납대여소번호"].notna()).sum()}개 (판정 기준: 마지막 열 결측 중 미반납이 아닌 행) / 반납 대여소 결측(미반납): {tail["반납대여소번호"].isna().sum()}개')
    for c in ('대여일시', '반납일시'):
        dates = pd.to_datetime(pd.concat([head[c], tail[c]]), errors='coerce')
        print(f'  {c} (앞·끝 행 기준): {dates.min()} ~ {dates.max()}, 변환 실패 {dates.isna().sum()}개')

# ---------------------------------------------------------------------------
# 지하철 승하차 6월 (1MB 남짓이라 전체 읽음)
# ---------------------------------------------------------------------------
section('지하철 승하차 6월')

ref_cols = list(pd.read_csv(DATA / 'subway' / 'CARD_SUBWAY_MONTH_201905.csv', encoding='utf-8-sig', nrows=0).columns)
for fname in ('CARD_SUBWAY_MONTH_201906.csv', 'CARD_SUBWAY_MONTH_202606.csv'):
    f = DATA / 'subway' / fname
    enc = detect_encoding(f)
    with open(f, encoding=enc) as fh:
        first_lines = [next(fh).rstrip('\n') for _ in range(3)]
    n_header = len(first_lines[0].split(','))
    n_data = len(first_lines[1].split(','))
    print(f'\n● {fname}  ({f.stat().st_size / 1024**2:,.1f} MB), 인코딩: {enc}')
    print(f'  원문 앞 3줄: {first_lines}')
    print(f'  헤더 칸 수 {n_header} / 데이터 칸 수 {n_data} → 끝 빈 칸 {"있음" if n_data > n_header else "없음"}')

    df = pd.read_csv(f, encoding=enc, usecols=range(6), dtype={'사용일자': str})
    print(f'  컬럼: {list(df.columns)} (2019-05와 같음: {list(df.columns) == ref_cols})')
    print('  ' + df.head(5).to_string(index=False).replace('\n', '\n  '))
    print(f'  {len(df):,}행, 사용일자 {df.사용일자.min()} ~ {df.사용일자.max()} ({df.사용일자.nunique()}일), '
          f'노선 {df.노선명.nunique()}개, 역명 {df.역명.nunique()}개')
    print(f'  결측: {df.isna().sum().to_dict()}')
    print(f'  노선명: {sorted(df.노선명.unique())}')
