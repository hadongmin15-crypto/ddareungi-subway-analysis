"""0단계: 파일 점검.

1. 폴더별 파일 목록·크기·인코딩·컬럼·앞 5행
2. 2019/2026 대여이력 컬럼 비교 → 공통 컬럼 매핑표
3. 대여소 번호 체계(숫자 번호 / ST- ID) → 매칭 키 결정
4. 2019 대여이력 대여소 중 위치를 못 찾는 비율 (대여소 수·대여 건수 기준)
5. 2019/2026 승하차 역명 표기 비교
6. 따릉이 월별 하루 평균 대여건수 (2019·2026 1~6월) 그래프
"""
import calendar
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 30)
pd.set_option('display.max_rows', 200)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TABLES = ROOT / 'outputs' / 'tables'
FIGURES = ROOT / 'outputs' / 'figures'
TABLES.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)

COLOR = {2019: '#2a78d6', 2026: '#eb6834'}


def section(title):
    print('\n' + '=' * 90 + f'\n{title}\n' + '=' * 90)


def detect_encoding(path, nbytes=200_000):
    """utf-8-sig로 앞부분이 깨끗이 읽히면 utf-8-sig, 아니면 cp949."""
    raw = path.read_bytes()[:nbytes] if path.stat().st_size < 50_000_000 else open(path, 'rb').read(nbytes)
    raw = raw[: raw.rfind(b'\n')]  # 다바이트 문자 중간 절단 방지
    try:
        raw.decode('utf-8-sig')
        return 'utf-8-sig'
    except UnicodeDecodeError:
        raw.decode('cp949')
        return 'cp949'


# ---------------------------------------------------------------------------
# 1. 파일 목록·인코딩·컬럼·앞 5행
# ---------------------------------------------------------------------------
section('1. 파일 목록 / 크기 / 인코딩 / 컬럼 / 앞 5행')

PRIVATE_COLS = {'생년', '성별', '이용자종류'}
encodings = {}
for folder in sorted(p for p in DATA.rglob('*') if p.is_dir() and p.name != 'cache'):
    files = sorted(p for p in folder.iterdir() if p.is_file())
    print(f'\n[{folder.relative_to(ROOT)}] 파일 {len(files)}개')
    for f in files:
        size_mb = f.stat().st_size / 1024**2
        print(f'\n  ● {f.name}  ({size_mb:,.1f} MB)')
        if f.suffix == '.csv':
            enc = detect_encoding(f)
            encodings[f] = enc
            head = pd.read_csv(f, encoding=enc, nrows=5, dtype=str, header=None if 'bike_stations' in str(f) else 'infer')
            head = head.drop(columns=[c for c in head.columns if c in PRIVATE_COLS])
            print(f'    인코딩: {enc}')
            print(f'    컬럼: {list(head.columns)}')
            print(head.to_string(index=False).replace('\n', '\n    '))
        elif f.suffix == '.xlsx':
            for sheet in pd.ExcelFile(f).sheet_names:
                head = pd.read_excel(f, sheet_name=sheet, header=None, nrows=8)
                print(f'    시트 [{sheet}] (헤더 포함 앞 8행)')
                print(head.to_string(index=False).replace('\n', '\n    '))

# ---------------------------------------------------------------------------
# 2. 대여이력 컬럼 비교 → 공통 컬럼 매핑표
# ---------------------------------------------------------------------------
section('2. 대여이력 컬럼 비교 (2019 vs 2026)')

trip_files = {
    2019: sorted((DATA / 'bike_trips' / '2019').glob('*.csv')),
    2026: sorted((DATA / 'bike_trips' / '2026').glob('*.csv')),
}
trip_cols = {}
for year, files in trip_files.items():
    for f in files:
        cols = list(pd.read_csv(f, encoding=encodings[f], nrows=0).columns)
        trip_cols[f.name] = cols
        print(f'{f.name}: {cols}')

cols19 = trip_cols[trip_files[2019][0].name]
cols26 = trip_cols[trip_files[2026][0].name]
for year, files in trip_files.items():
    base = cols19 if year == 2019 else cols26
    for f in files:
        assert trip_cols[f.name] == base, f'{f.name} 컬럼이 같은 해 다른 파일과 다름'
print(f'\n2019에만 있는 컬럼: {sorted(set(cols19) - set(cols26))}')
print(f'2026에만 있는 컬럼: {sorted(set(cols26) - set(cols19))}')

column_map = pd.DataFrame([
    ('rent_time', '대여일시', '대여일시', '사용'),
    ('rent_station_no', '대여 대여소번호', '대여 대여소번호', '사용 (매칭 키)'),
    ('rent_station_name', '대여 대여소명', '대여 대여소명', '확인용'),
    ('rent_station_id', '대여대여소ID', '대여대여소ID', '확인용'),
    ('return_time', '반납일시', '반납일시', '사용'),
    ('return_station_no', '반납대여소번호', '반납대여소번호', '사용 (매칭 키)'),
    ('return_station_name', '반납대여소명', '반납대여소명', '확인용'),
    ('return_station_id', '반납대여소ID', '반납대여소ID', '확인용'),
    ('duration_min', '이용시간(분)', '이용시간(분)', '사용'),
    ('distance_m', '이용거리(M)', '이용거리(M)', '참고'),
    ('-', '자전거번호', '자전거번호', '미사용'),
    ('-', '대여거치대', '대여거치대', '미사용'),
    ('-', '반납거치대', '반납거치대', '미사용'),
    ('-', '생년 / 성별 / 이용자종류', '생년 / 성별 / 이용자종류', '읽지 않음 (개인정보)'),
    ('-', '자전거구분', '(없음)', '미사용'),
], columns=['std_name', 'col_2019', 'col_2026', 'use'])
for _, r in column_map.iterrows():
    for c in r.col_2019.split(' / '):
        assert c == '(없음)' or c in cols19, c
    for c in r.col_2026.split(' / '):
        assert c == '(없음)' or c in cols26, c
column_map.to_csv(TABLES / '00_trip_column_map.csv', index=False, encoding='utf-8-sig')
print('\n공통 컬럼 매핑표')
print(column_map.to_string(index=False))

# ---------------------------------------------------------------------------
# 3. 대여소 번호 체계 — 대여이력 전체를 대여소 컬럼만 읽어 집계
# ---------------------------------------------------------------------------
section('3. 대여소 번호 체계 (숫자 번호 / ST- ID)')

STATION_COLS = {
    'rent': ['대여 대여소번호', '대여 대여소명', '대여대여소ID'],
    'return': ['반납대여소번호', '반납대여소명', '반납대여소ID'],
}
usecols = STATION_COLS['rent'] + STATION_COLS['return']

station_counts = []  # (year, side, no, name, id, n)
trip_rows = {}
for year, files in trip_files.items():
    for f in files:
        n_rows = 0
        for chunk in pd.read_csv(f, encoding=encodings[f], usecols=usecols, dtype=str,
                                 na_values=['\\N', ''], chunksize=2_000_000):
            n_rows += len(chunk)
            for side, (c_no, c_name, c_id) in STATION_COLS.items():
                g = chunk.groupby([c_no, c_name, c_id], dropna=False).size().reset_index(name='n')
                g.columns = ['no', 'name', 'id', 'n']
                g['year'], g['side'] = year, side
                station_counts.append(g)
        trip_rows[f.name] = n_rows
        print(f'{f.name}: {n_rows:,}행')

sc = pd.concat(station_counts).groupby(['year', 'side', 'no', 'name', 'id'], dropna=False)['n'].sum().reset_index()
sc.to_csv(TABLES / '00_trip_station_counts.csv', index=False, encoding='utf-8-sig')

print('\n번호 형식 예시:', sc['no'].dropna().unique()[:8].tolist())
print('ID 형식 예시:', sc['id'].dropna().unique()[:8].tolist())
sc['no_int'] = pd.to_numeric(sc['no'], errors='coerce')
bad_no = sc[sc['no'].notna() & sc['no_int'].isna()]
print(f'숫자로 변환 안 되는 번호: {bad_no["no"].unique().tolist()}')
print('\n결측(번호 없음) 건수:')
print(sc[sc['no'].isna()].groupby(['year', 'side'])['n'].sum().to_string())

# 같은 해 안에서 번호 ↔ ID 1:1 인지
pairs = sc.dropna(subset=['no_int', 'id']).groupby(['year', 'no_int', 'id'])['n'].sum().reset_index()
for year in (2019, 2026):
    p = pairs[pairs.year == year]
    multi_id = p.groupby('no_int')['id'].nunique()
    multi_no = p.groupby('id')['no_int'].nunique()
    print(f'\n[{year}] 번호 {p.no_int.nunique():,}개, ID {p.id.nunique():,}개 | '
          f'ID 2개 이상인 번호 {(multi_id > 1).sum()}개, 번호 2개 이상인 ID {(multi_no > 1).sum()}개')

# 2019 ↔ 2026 사이 같은 번호가 같은 ID·같은 이름인지
id_by_year = pairs.sort_values('n').groupby(['year', 'no_int'])['id'].last().unstack('year')
both = id_by_year.dropna()
print(f'\n두 해 모두 등장한 번호 {len(both):,}개 중 ID가 다른 번호: {(both[2019] != both[2026]).sum()}개')
name_by_year = (sc.dropna(subset=['no_int', 'name']).groupby(['year', 'no_int', 'name'])['n'].sum()
                .reset_index().sort_values('n').groupby(['year', 'no_int'])['name'].last().unstack('year').dropna())
diff_name = name_by_year[name_by_year[2019] != name_by_year[2026]]
print(f'두 해 모두 등장한 번호 중 대표 이름이 다른 번호: {len(diff_name)}개 (예시 15개)')
print(diff_name.head(15).to_string())

# ---------------------------------------------------------------------------
# 4. 대여소 위치 파일 매칭
# ---------------------------------------------------------------------------
section('4. 2019 대여이력 대여소 중 위치를 못 찾는 비율')


def load_station_location(path):
    """헤더가 여러 줄인 위치 파일 → 번호·이름·자치구·위도·경도."""
    if path.suffix == '.xlsx':
        raw = pd.read_excel(path, header=None)
    else:
        raw = pd.read_csv(path, encoding=encodings[path], header=None, dtype=str)
    raw = raw.iloc[:, :6]
    raw.columns = ['no', 'name', 'district', 'address', 'lat', 'lon']
    raw['no'] = pd.to_numeric(raw['no'], errors='coerce')
    loc = raw.dropna(subset=['no']).copy()
    loc['no'] = loc['no'].astype(int)
    loc['lat'] = pd.to_numeric(loc['lat'], errors='coerce')
    loc['lon'] = pd.to_numeric(loc['lon'], errors='coerce')
    return loc


loc26 = load_station_location(DATA / 'bike_stations' / '공공자전거 대여소 정보(26.6월 기준).xlsx')
loc21 = load_station_location(DATA / 'bike_stations' / '공공자전거 대여소 정보(21.01.31 기준).csv')
for label, loc in (('26.6월', loc26), ('21.01.31', loc21)):
    print(f'\n[{label}] {len(loc):,}행, 번호 고유 {loc.no.nunique():,}개, 중복 번호 {loc.no.duplicated().sum()}개, '
          f'좌표 결측 {loc[["lat", "lon"]].isna().any(axis=1).sum()}개')
    print(f'  위도 {loc.lat.min():.4f}~{loc.lat.max():.4f}, 경도 {loc.lon.min():.4f}~{loc.lon.max():.4f}')
    print(loc.head(3).to_string(index=False))

with_coord26 = set(loc26.dropna(subset=['lat', 'lon']).no)
with_coord21 = set(loc21.dropna(subset=['lat', 'lon']).no)

match_rows = []
for year in (2019, 2026):
    for side in ('rent', 'return'):
        s = sc[(sc.year == year) & (sc.side == side)].dropna(subset=['no_int'])
        by_no = s.groupby('no_int')['n'].sum()
        in26 = by_no.index.isin(list(with_coord26))
        in21 = by_no.index.isin(list(with_coord21))
        found = in26 | in21
        match_rows.append({
            'year': year, 'side': side,
            'stations': len(by_no),
            'found_26': int(in26.sum()), 'found_21_only': int((~in26 & in21).sum()),
            'not_found': int((~found).sum()),
            'not_found_station_pct': round((~found).mean() * 100, 2),
            'trips': int(by_no.sum()),
            'not_found_trips': int(by_no[~found].sum()),
            'not_found_trip_pct': round(by_no[~found].sum() / by_no.sum() * 100, 2),
        })
match_tbl = pd.DataFrame(match_rows)
match_tbl.to_csv(TABLES / '00_station_location_match.csv', index=False, encoding='utf-8-sig')
print('\n대여이력 대여소 ↔ 위치 파일 매칭 (번호 기준)')
print(match_tbl.to_string(index=False))

nf19 = sc[(sc.year == 2019)].dropna(subset=['no_int'])
nf19 = nf19[~nf19.no_int.isin(list(with_coord26 | with_coord21))]
nf19_list = nf19.groupby(['no_int', 'name'])['n'].sum().sort_values(ascending=False)
print(f'\n2019 위치 못 찾은 대여소 (대여+반납 건수 상위 15)')
print(nf19_list.head(15).to_string())

# 같은 번호인데 26 ↔ 21 좌표가 500m 이상 다른 대여소 (1단계 참고용 개수만)
import numpy as np
m = loc26.merge(loc21, on='no', suffixes=('_26', '_21')).dropna(subset=['lat_26', 'lon_26', 'lat_21', 'lon_21'])
lat1, lon1, lat2, lon2 = map(np.radians, (m.lat_26, m.lon_26, m.lat_21, m.lon_21))
d = 2 * 6_371_000 * np.arcsin(np.sqrt(np.sin((lat2 - lat1) / 2) ** 2
                                      + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2))
print(f'\n두 위치 파일 모두 있는 번호 {len(m):,}개 중 좌표 차이 500m 이상: {(d >= 500).sum()}개 (1단계에서 목록 보고)')

# ---------------------------------------------------------------------------
# 5. 지하철 승하차 역명 표기 비교
# ---------------------------------------------------------------------------
section('5. 지하철 승하차 역명 표기 (2019 vs 2026)')

subway = {}
for year, months in ((2019, ('04', '05')), (2026, ('04', '05'))):
    frames = []
    for mm in months:
        f = DATA / 'subway' / f'CARD_SUBWAY_MONTH_{year}{mm}.csv'
        df = pd.read_csv(f, encoding='utf-8-sig', usecols=range(6), dtype={'사용일자': str})
        frames.append(df)
    subway[year] = pd.concat(frames)
    s = subway[year]
    print(f'[{year}] {len(s):,}행, 날짜 {s.사용일자.min()}~{s.사용일자.max()} ({s.사용일자.nunique()}일), '
          f'노선 {s.노선명.nunique()}개, 역명 {s.역명.nunique()}개')

names19, names26 = set(subway[2019].역명), set(subway[2026].역명)
print(f'\n공통 역명 {len(names19 & names26)}개')
print(f'2019에만 있는 역명 ({len(names19 - names26)}개): {sorted(names19 - names26)}')
print(f'2026에만 있는 역명 ({len(names26 - names19)}개): {sorted(names26 - names19)}')
paren19 = sorted(n for n in names19 if '(' in n)
paren26 = sorted(n for n in names26 if '(' in n)
print(f'\n괄호 포함 역명 2019: {len(paren19)}개 / 2026: {len(paren26)}개')
print(f'  2026 예시: {paren26[:20]}')
print(f'\n노선명 2019: {sorted(subway[2019].노선명.unique())}')
print(f'노선명 2026: {sorted(subway[2026].노선명.unique())}')

# ---------------------------------------------------------------------------
# 6. 따릉이 월별 하루 평균 대여건수 (2019·2026 1~6월)
# ---------------------------------------------------------------------------
section('6. 따릉이 월별 하루 평균 대여건수 (1~6월)')

monthly_frames = []
for f in sorted((DATA / 'bike_monthly').glob('*.xlsx')):
    df = pd.read_excel(f, sheet_name='대여')
    df = df.iloc[:, :4]
    df.columns = ['district', 'station', 'ym', 'rents']
    monthly_frames.append(df)
for f in sorted((DATA / 'bike_monthly').glob('*.csv')):
    df = pd.read_csv(f, encoding=detect_encoding(f))
    print(f'{f.name} 컬럼: {list(df.columns)}')
    df = df.iloc[:, :4]
    df.columns = ['district', 'station', 'ym', 'rents']
    monthly_frames.append(df)
monthly = pd.concat(monthly_frames)
monthly['ym'] = pd.to_numeric(monthly['ym'], errors='coerce')
monthly['rents'] = pd.to_numeric(monthly['rents'], errors='coerce')
print(f'합친 뒤 년월 목록: {sorted(monthly.ym.dropna().astype(int).unique())}')
print(f'년월·건수 결측 행: {monthly[["ym", "rents"]].isna().any(axis=1).sum()}')

monthly = monthly.dropna(subset=['ym'])
monthly['year'] = (monthly.ym // 100).astype(int)
monthly['month'] = (monthly.ym % 100).astype(int)
monthly = monthly[monthly.year.isin([2019, 2026]) & monthly.month.between(1, 6)]

mon = monthly.groupby(['year', 'month']).agg(rents=('rents', 'sum'), stations=('station', 'nunique')).reset_index()
mon['days'] = [calendar.monthrange(y, m)[1] for y, m in zip(mon.year, mon.month)]
mon['daily_avg'] = (mon.rents / mon.days).round(0)
mon.to_csv(TABLES / '00_bike_monthly_daily_avg.csv', index=False, encoding='utf-8-sig')
print(mon.to_string(index=False))

# 대여이력 원본과 대조 (4·5월 행 수 vs 월별 파일 합계)
print('\n대여이력 행 수 vs 월별 파일 대여건수 (4·5월)')
for fname, n in trip_rows.items():
    yymm = fname.split('_')[-1].replace('.csv', '')
    y, mth = 2000 + int(yymm[:2]), int(yymm[2:])
    mrow = mon[(mon.year == y) & (mon.month == mth)]
    print(f'  {y}-{mth:02d}: 대여이력 {n:,} / 월별 {int(mrow.rents.iloc[0]):,}')

fig, ax = plt.subplots(figsize=(8, 4.5))
width = 0.38
for i, year in enumerate((2019, 2026)):
    d = mon[mon.year == year]
    x = d.month + (i - 0.5) * width
    ax.bar(x, d.daily_avg, width=width - 0.03, color=COLOR[year], label=f'{year}년')
    top = d.loc[d.daily_avg.idxmax()]
    ax.annotate(f'{int(top.daily_avg):,}', (top.month + (i - 0.5) * width, top.daily_avg),
                ha='center', va='bottom', fontsize=9, color='#333333')
ax.axvspan(3.5, 5.5, color='#999999', alpha=0.12, lw=0)
ax.text(4.5, ax.get_ylim()[1] * 0.97, '분석 후보 기간 (4~5월)', ha='center', va='top', fontsize=9, color='#555555')
ax.set_xticks(range(1, 7), [f'{m}월' for m in range(1, 7)])
ax.set_ylabel('하루 평균 대여건수')
ax.set_title('따릉이 월별 하루 평균 대여건수 (1~6월, 2019 vs 2026)')
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:,.0f}'))
ax.spines[['top', 'right']].set_visible(False)
ax.grid(axis='y', color='#e5e5e5', lw=0.8)
ax.set_axisbelow(True)
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(FIGURES / '00_bike_monthly.png', dpi=150)
print(f'\n저장: {FIGURES / "00_bike_monthly.png"}')
