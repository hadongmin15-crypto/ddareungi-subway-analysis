"""1단계: 전처리 — 역 목록 확정, 대여소 배정, 대여이력 정제·이동 분류, 역별 집계."""
# %% [1-0] 설정
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 30)
pd.set_option('display.max_rows', 300)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CACHE = DATA / 'cache'
TABLES = ROOT / 'outputs' / 'tables'
CACHE.mkdir(parents=True, exist_ok=True)
TABLES.mkdir(parents=True, exist_ok=True)

YEARS = (2019, 2026)
MONTHS = ('05', '06')
RENAME = {'당고개': '불암산', '뚝섬유원지': '자양', '화전': '한국항공대', '지제': '평택지제',
          '총신대입구': '이수'}  # 총신대입구(4호선)·이수(7호선)는 같은 환승역 → 한 역으로 합침
DROP_STATIONS = ['양평']
GYEONGGI_STATIONS = ['역곡', '철산', '석수', '갈매', '지축']  # 1km 규칙에 걸렸지만 경기 소재 (사용자 확정)
# 2026에만 있는 노선명: 진짜 새 노선(2019 데이터에 없음 → 2026에서 행 제외) / 이름만 바뀜(2019 표기)
NEW_LINES_2026 = {'신림선': '2022년 개통', '서해선': '2019 데이터에 없음, 2023년 김포공항 연결'}
RENAMED_LINES_2026 = {'9호선2~3단계': '9호선', '경부선': '1호선', '경원선': '1호선', '경인선': '1호선',
                      '장항선': '1호선', '과천선': '4호선', '안산선': '4호선', '일산선': '3호선',
                      '중앙선': '경의선', '공항철도 1호선': '공항철도', '우이신설선': '우이신설경전철'}
EXCLUDED_DATES = {
    2019: ['2019-05-01', '2019-05-06', '2019-06-06'],
    2026: ['2026-05-01', '2026-05-05', '2026-05-25', '2026-06-03'],
}
SEOUL_RADIUS_KM = 1.0
ASSIGN_RADIUS_KM = 0.5
PAIR_MAX_KM = 2.5
MOVED_KM = 0.5
MIN_DURATION, MAX_DURATION = 2, 120
HOP, LINK, OTHER = '따릉이 역간 단거리 이동', '따릉이 역 연계 이동', '따릉이 기타 이동'
WEEKDAY_KO = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}

summary = []  # (구분, 연도, 항목, 값, 비율%)


def add_summary(part, year, item, value, base=None):
    pct = round(value / base * 100, 2) if base else None
    summary.append({'part': part, 'year': year, 'item': item, 'value': value, 'pct_of_base': pct})


def section(title):
    print('\n' + '=' * 90 + f'\n{title}\n' + '=' * 90)


def normalize_name(name):
    name = re.sub(r'\(.*?\)', '', str(name)).strip()
    name = re.sub(r'\s+', '', name)
    if name.endswith('역') and len(name) > 2:
        name = name[:-1]
    return RENAME.get(name, name)


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def distance_matrix(lat_a, lon_a, lat_b, lon_b):
    return haversine_km(np.asarray(lat_a)[:, None], np.asarray(lon_a)[:, None],
                        np.asarray(lat_b)[None, :], np.asarray(lon_b)[None, :])


def day_type(dates, year):
    excluded = pd.to_datetime(EXCLUDED_DATES[year])
    dt = pd.Series(np.where(dates.dt.dayofweek < 5, '평일', '주말'), index=dates.index)
    dt[dates.dt.normalize().isin(excluded)] = '제외일'
    return dt


# %% [1-1] 지하철역 좌표: 수도권만, 역명 정규화, 역마다 평균 좌표 하나
section('[1-1] 지하철역 좌표')
coord_raw = pd.read_csv(DATA / 'subway' / '지하철노선위경도정보2.csv', encoding='utf-8-sig')
coord_raw = coord_raw[coord_raw['역지역'] == '수도권'].copy()
coord_raw['station'] = coord_raw['역이름'].map(normalize_name)
station_coord = (coord_raw.groupby('station')
                 .agg(lat=('위도', 'mean'), lon=('경도', 'mean'), n_lines_coord=('호선', 'size'),
                      lines_coord=('호선', lambda s: '/'.join(sorted(s))))
                 .reset_index())
spread = coord_raw.merge(station_coord[['station', 'lat', 'lon']], on='station')
spread['d_km'] = haversine_km(spread['위도'], spread['경도'], spread['lat'], spread['lon'])
print(f'수도권 좌표 {len(coord_raw)}행 → 역 {len(station_coord)}개 (같은 역 좌표 간 최대 거리 {spread.d_km.max() * 1000:.0f}m)')

# %% [1-2] 서울 역 판정: 반경 1km 안에 2026 대여소가 있는 역
section('[1-2] 서울(따릉이 서비스권) 역 판정')


def load_bike_location(path):
    raw = pd.read_excel(path, header=None) if path.suffix == '.xlsx' else \
        pd.read_csv(path, encoding='cp949', header=None, dtype=str)
    raw = raw.iloc[:, :6]
    raw.columns = ['bike_no', 'bike_name', 'district', 'address', 'lat', 'lon']
    raw['bike_no'] = pd.to_numeric(raw['bike_no'], errors='coerce')
    loc = raw.dropna(subset=['bike_no']).copy()
    loc['bike_no'] = loc['bike_no'].astype(int)
    loc['lat'] = pd.to_numeric(loc['lat'], errors='coerce')
    loc['lon'] = pd.to_numeric(loc['lon'], errors='coerce')
    return loc


loc26 = load_bike_location(DATA / 'bike_stations' / '공공자전거 대여소 정보(26.6월 기준).xlsx')
loc21 = load_bike_location(DATA / 'bike_stations' / '공공자전거 대여소 정보(21.01.31 기준).csv')

d_seoul = distance_matrix(station_coord.lat, station_coord.lon, loc26.lat, loc26.lon)
station_coord['n_bike_1km'] = (d_seoul <= SEOUL_RADIUS_KM).sum(axis=1)
station_coord['nearest_bike_km'] = d_seoul.min(axis=1).round(3)
station_coord['is_seoul'] = (station_coord['n_bike_1km'] > 0) & ~station_coord.station.isin(GYEONGGI_STATIONS)
print(f'서울 역 {station_coord.is_seoul.sum()}개 / 비서울 {(~station_coord.is_seoul).sum()}개 '
      f'(경기 소재로 직접 제외 {len(GYEONGGI_STATIONS)}개 포함)')

# %% [1-3] 승하차 데이터 읽기 + 역명 정규화 + 좌표 파일과 매칭
section('[1-3] 승하차 데이터와 역 매칭')
subway_raw = {}
for year in YEARS:
    frames = [pd.read_csv(DATA / 'subway' / f'CARD_SUBWAY_MONTH_{year}{mm}.csv', encoding='utf-8-sig',
                          usecols=range(6)) for mm in MONTHS]
    df = pd.concat(frames, ignore_index=True)
    df['date'] = pd.to_datetime(df['사용일자'].astype(str))
    df['station'] = df['역명'].map(normalize_name)
    df['riders'] = df['승차총승객수'] + df['하차총승객수']
    add_summary('지하철', year, '원본 행', len(df))
    add_summary('지하철', year, '원본 역명(정규화 후)', df.station.nunique())
    subway_raw[year] = df

# %% [1-3a] 2026 전용 노선명 분류 → 진짜 새 노선 행은 2026에서 제외
lines19, lines26 = set(subway_raw[2019]['노선명']), set(subway_raw[2026]['노선명'])
only26 = sorted(lines26 - lines19)
unknown = set(only26) - set(NEW_LINES_2026) - set(RENAMED_LINES_2026)
assert not unknown, f'분류 안 된 2026 전용 노선명: {unknown}'
df26 = subway_raw[2026]
line_tbl = pd.DataFrame([{
    'line_2026': ln,
    'class': '진짜 새 노선' if ln in NEW_LINES_2026 else '이름만 바뀜',
    'note': NEW_LINES_2026.get(ln, f'2019 표기: {RENAMED_LINES_2026.get(ln)}'),
    'rows': int((df26['노선명'] == ln).sum()),
    'stations': '/'.join(sorted(df26.loc[df26['노선명'] == ln, 'station'].unique())),
} for ln in only26])
line_tbl.to_csv(TABLES / '01_lines_2026_only.csv', index=False, encoding='utf-8-sig')
print(line_tbl[['line_2026', 'class', 'note', 'rows']].to_string(index=False))
print(f'2019에만 있는 노선명: {sorted(lines19 - lines26)}')

new_line_rows = df26['노선명'].isin(NEW_LINES_2026)
new_line_share = (df26[new_line_rows].groupby('station')['riders'].sum()
                  / df26.groupby('station')['riders'].sum() * 100).dropna().round(1)
print(f'2026 새 노선 행 제외: {new_line_rows.sum():,}행 (역별 승하차 중 비중 %: {new_line_share.to_dict()})')
add_summary('지하철', 2026, '제외 - 새 노선(신림선·서해선) 행', int(new_line_rows.sum()), len(df26))
subway_raw[2026] = df26[~new_line_rows]

unmatched = []
for year in YEARS:
    names = set(subway_raw[year].station)
    for n in sorted(names - set(station_coord.station)):
        orig = sorted(subway_raw[year].loc[subway_raw[year].station == n, '역명'].unique())
        lines = sorted(subway_raw[year].loc[subway_raw[year].station == n, '노선명'].unique())
        unmatched.append({'year': year, 'station': n, 'raw_name': '/'.join(orig), 'lines': '/'.join(lines)})
unmatched = pd.DataFrame(unmatched)
unmatched.to_csv(TABLES / '01_unmatched_stations.csv', index=False, encoding='utf-8-sig')
for year in YEARS:
    u = unmatched[unmatched.year == year]
    print(f'[{year}] 좌표 파일과 매칭 안 된 역 {len(u)}개: {u.station.tolist()}')

# %% [1-3b] 하루 행 수가 위경도 파일 노선 수와 다른 역 (점검)
rows_check = []
for year in YEARS:
    df = subway_raw[year]
    r = df.groupby(['station', 'date']).agg(rows=('riders', 'size'), riders=('riders', 'sum'),
                                           min_row=('riders', 'min')).reset_index()
    g = r.groupby('station').agg(rows_min=('rows', 'min'), rows_max=('rows', 'max'))
    g['lines'] = df.groupby('station')['노선명'].agg(lambda s: '/'.join(sorted(set(s))))
    # 행 수가 날마다 다른 역: 들쭉날쭉한 작은 행이 하루 합계에서 차지하는 최대 비중
    var = g.index[g.rows_min != g.rows_max]
    rv = r[r.station.isin(var)]
    g['max_small_row_share_pct'] = (rv.min_row / rv.riders * 100).groupby(rv.station).max().round(3)
    g.columns = [f'{c}_{year}' for c in g.columns]
    rows_check.append(g)
rows_check = pd.concat(rows_check, axis=1).join(station_coord.set_index('station')[['n_lines_coord', 'lines_coord']])
rows_check = rows_check.dropna(subset=['rows_max_2019', 'rows_max_2026', 'n_lines_coord'])
mismatch = rows_check[(rows_check.rows_max_2019 != rows_check.n_lines_coord)
                      | (rows_check.rows_max_2026 != rows_check.n_lines_coord)
                      | (rows_check.rows_min_2019 != rows_check.rows_max_2019)
                      | (rows_check.rows_min_2026 != rows_check.rows_max_2026)]
mismatch.to_csv(TABLES / '01_rows_vs_lines_check.csv', encoding='utf-8-sig')
print(f'하루 행 수 ≠ 노선 수 (또는 날마다 다름) 역: {len(mismatch)}개 → 01_rows_vs_lines_check.csv')

# %% [1-4] 분석 대상 역 확정: 양평 제외, 좌표 매칭, 서울, 두 해 모두 존재
section('[1-4] 분석 대상 역 목록')
seoul_names = set(station_coord.loc[station_coord.is_seoul, 'station'])
coord_names = set(station_coord.station)
names_by_year = {y: set(subway_raw[y].station) for y in YEARS}
all_names = names_by_year[2019] | names_by_year[2026]

steps = {'양평 제외(동명이역)': set(DROP_STATIONS) & all_names}
pool = all_names - steps['양평 제외(동명이역)']
steps['좌표 파일 매칭 안 됨'] = pool - coord_names
pool -= steps['좌표 파일 매칭 안 됨']
steps['경기 소재(1km 규칙엔 걸림, 직접 제외)'] = pool & set(GYEONGGI_STATIONS)
pool -= steps['경기 소재(1km 규칙엔 걸림, 직접 제외)']
steps['비서울(1km 내 대여소 없음)'] = pool - seoul_names
pool -= steps['비서울(1km 내 대여소 없음)']
steps['한 해에만 존재'] = pool - (names_by_year[2019] & names_by_year[2026])
pool -= steps['한 해에만 존재']
analysis_stations = sorted(pool)

print(f'승하차 역명(두 해 합집합, 정규화 후) {len(all_names)}개')
for k, v in steps.items():
    print(f'  {k}: {len(v)}개 제외')
    add_summary('역', None, f'제외 - {k}', len(v), len(all_names))
print(f'분석 대상 역: {len(analysis_stations)}개')
add_summary('역', None, '분석 대상 역', len(analysis_stations), len(all_names))

non_seoul = station_coord[~station_coord.is_seoul & station_coord.station.isin(all_names - set(DROP_STATIONS))
                          & ~station_coord.station.isin(GYEONGGI_STATIONS)]
non_seoul[['station', 'lat', 'lon', 'lines_coord', 'nearest_bike_km']].sort_values('station').to_csv(
    TABLES / '01_excluded_non_seoul_stations.csv', index=False, encoding='utf-8-sig')
near = non_seoul[non_seoul.nearest_bike_km.between(1, 2)].sort_values('nearest_bike_km')
print(f'비서울 제외 중 가장 가까운 대여소 1~2km 역 ({len(near)}개):\n'
      f'{near[["station", "lines_coord", "nearest_bike_km"]].to_string(index=False)}')
only_one = pd.DataFrame([{'station': n, 'year': 2019 if n in names_by_year[2019] else 2026}
                         for n in sorted(steps['한 해에만 존재'])])
only_one.to_csv(TABLES / '01_excluded_one_year_stations.csv', index=False, encoding='utf-8-sig')
print(f'비서울 제외 역 → 01_excluded_non_seoul_stations.csv')
print(f'한 해에만 있는 서울 역: {only_one.to_dict("records")}')

stations = station_coord[station_coord.station.isin(analysis_stations)].reset_index(drop=True)
stations[['station', 'lat', 'lon', 'n_lines_coord', 'lines_coord', 'n_bike_1km']].to_csv(
    TABLES / '01_analysis_stations.csv', index=False, encoding='utf-8-sig')

# %% [1-4b] 지하철 역·날짜별 합산 → 제외일 표시 → 평일/주말 하루 평균
subway_daily = []
for year in YEARS:
    df = subway_raw[year]
    df = df[df.station.isin(analysis_stations)]
    d = df.groupby(['station', 'date'], as_index=False)['riders'].sum()
    d['year'] = year
    d['day_type'] = day_type(d['date'], year)
    d['weekday'] = d['date'].dt.dayofweek.map(WEEKDAY_KO)
    n_days = d.date.nunique()
    missing = len(analysis_stations) * n_days - len(d)
    print(f'[{year}] 지하철 역-일 {len(d):,}개 (날짜 {n_days}일, 빠진 역-일 {missing}개)')
    subway_daily.append(d)
subway_daily = pd.concat(subway_daily, ignore_index=True)
for year in YEARS:
    d = subway_daily[subway_daily.year == year]
    excluded_days = d.loc[d.day_type == '제외일', 'date'].dt.strftime('%m-%d').unique().tolist()
    print(f'[{year}] 제외일 {excluded_days} | 평일 {d[d.day_type == "평일"].date.nunique()}일, '
          f'주말 {d[d.day_type == "주말"].date.nunique()}일')
    for t in ('평일', '주말', '제외일'):
        add_summary('날짜', year, f'{t} 일수', int(d[d.day_type == t].date.nunique()))
subway_daily.to_parquet(CACHE / 'subway_daily.parquet', index=False)

# %% [1-5] 대여소 좌표: 26.6월 우선, 없으면 21.01.31
section('[1-5] 대여소 좌표 · 역 배정')
dup21 = loc21[loc21.bike_no.duplicated(keep=False)]
print(f'21.01.31 파일 중복 번호: {dup21[["bike_no", "bike_name", "lat", "lon"]].to_dict("records")}')
loc21_valid = loc21.dropna(subset=['lat', 'lon']).drop_duplicates('bike_no', keep='first')
print(f'21.01.31 파일 좌표 결측 {loc21[["lat", "lon"]].isna().any(axis=1).sum()}행 제외')

bike_loc = pd.concat([loc26.dropna(subset=['lat', 'lon']).assign(source='26.6'),
                      loc21_valid[~loc21_valid.bike_no.isin(loc26.bike_no)].assign(source='21.01')],
                     ignore_index=True)[['bike_no', 'bike_name', 'lat', 'lon', 'source']]
print(f'대여소 좌표 {len(bike_loc):,}개 (26.6월 {(bike_loc.source == "26.6").sum():,} + 21.01만 {(bike_loc.source == "21.01").sum():,})')

moved = loc26.merge(loc21_valid, on='bike_no', suffixes=('_26', '_21'))
moved['moved_m'] = (haversine_km(moved.lat_26, moved.lon_26, moved.lat_21, moved.lon_21) * 1000).round(0)
moved = moved[moved.moved_m >= MOVED_KM * 1000][['bike_no', 'bike_name_21', 'bike_name_26', 'moved_m']]
moved.to_csv(TABLES / '01_moved_bike_stations.csv', index=False, encoding='utf-8-sig')
print(f'두 파일 좌표 500m 이상 차이 (26.6월 좌표 사용):\n{moved.to_string(index=False)}')

# %% [1-5b] 대여소 → 분석 대상 역 배정 (500m 안 가장 가까운 역 하나)
d_assign = distance_matrix(bike_loc.lat, bike_loc.lon, stations.lat, stations.lon)
nearest = d_assign.argmin(axis=1)
nearest_km = d_assign[np.arange(len(bike_loc)), nearest]
bike_loc['station'] = np.where(nearest_km <= ASSIGN_RADIUS_KM, stations.station.values[nearest], None)
bike_loc['station_km'] = nearest_km.round(3)
bike_loc.to_csv(TABLES / '01_bike_station_assignment.csv', index=False, encoding='utf-8-sig')
print(f'역 근처(500m) 대여소 {bike_loc.station.notna().sum():,}개 / 전체 {len(bike_loc):,}개')

# %% [1-6] 대여이력 읽기 (필요한 컬럼만, 개인정보 제외)
section('[1-6] 대여이력 정제 · 이동 분류')
TRIP_COLS = {'대여일시': 'rent_time', '대여 대여소번호': 'rent_no', '반납일시': 'return_time',
             '반납대여소번호': 'return_no'}


def read_trips(year):
    frames = []
    for mm in MONTHS:
        f = DATA / 'bike_trips' / str(year) / f'서울특별시 공공자전거 대여이력 정보_{str(year)[2:]}{mm}.csv'
        for chunk in pd.read_csv(f, encoding='cp949', usecols=list(TRIP_COLS), dtype=str,
                                 na_values=['\\N', ''], chunksize=2_000_000):
            chunk = chunk.rename(columns=TRIP_COLS)
            chunk['rent_time'] = pd.to_datetime(chunk['rent_time'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            chunk['return_time'] = pd.to_datetime(chunk['return_time'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            chunk['rent_no'] = pd.to_numeric(chunk['rent_no'], errors='coerce').astype('Int32')
            chunk['return_no'] = pd.to_numeric(chunk['return_no'], errors='coerce').astype('Int32')
            frames.append(chunk)
        print(f'  읽음: {f.name}')
    return pd.concat(frames, ignore_index=True)


assign_map = bike_loc.set_index('bike_no')['station']
known_bike = set(bike_loc.bike_no)
st_xy = stations.set_index('station')[['lat', 'lon']]
trips_clean = {}

for year in YEARS:
    t = read_trips(year)
    n0 = len(t)
    add_summary('대여이력', year, '원본 건수', n0)
    print(f'[{year}] 원본 {n0:,}건')

    # 대여일시 결측·기간 밖
    bad = t.rent_time.isna() | ~t.rent_time.dt.month.isin([5, 6])
    print(f'  대여일시 결측·5~6월 밖 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 대여일시 결측·기간 밖', int(bad.sum()), n0)
    t = t[~bad]

    # 반납 대여소·반납 시각 결측
    bad = t.return_no.isna() | t.return_time.isna()
    print(f'  반납 대여소·시각 결측 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 반납 대여소·시각 결측', int(bad.sum()), n0)
    t = t[~bad]

    # 이용시간 = 실제 시각 차이(반납 − 대여), 원본 이용시간 컬럼은 쓰지 않음 (사용자 확정)
    t = t.assign(duration_min=((t.return_time - t.rent_time).dt.total_seconds() / 60).astype('float32'))

    # 이용시간 2분 미만
    bad = t.duration_min < MIN_DURATION
    print(f'  2분 미만 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 이용시간 2분 미만', int(bad.sum()), n0)
    t = t[~bad]

    # 이용시간 2시간 초과
    bad = t.duration_min > MAX_DURATION
    print(f'  2시간 초과 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 이용시간 2시간 초과', int(bad.sum()), n0)
    t = t[~bad]

    # 같은 대여소 반납
    bad = t.rent_no == t.return_no
    print(f'  같은 대여소 반납 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 같은 대여소 반납', int(bad.sum()), n0)
    t = t[~bad]

    # 위치를 못 찾는 대여소 (대여 또는 반납)
    bad = ~t.rent_no.isin(known_bike) | ~t.return_no.isin(known_bike)
    print(f'  위치 없는 대여소 제외: {bad.sum():,}건')
    add_summary('대여이력', year, '제외 - 위치 없는 대여소', int(bad.sum()), n0)
    t = t[~bad].copy()

    add_summary('대여이력', year, '최종 건수', len(t), n0)
    print(f'  최종 {len(t):,}건 ({len(t) / n0 * 100:.1f}%)')

    # 이동 분류 (두 역 2.5km 초과 역↔역 이동은 기타 — 사용자 확정, pair_km는 민감도 확인용으로 남김)
    t['rent_station'] = t.rent_no.map(assign_map)
    t['return_station'] = t.return_no.map(assign_map)
    both = t.rent_station.notna() & t.return_station.notna()
    diff = both & (t.rent_station != t.return_station)
    a = st_xy.reindex(t.rent_station)
    b = st_xy.reindex(t.return_station)
    t['pair_km'] = np.where(diff, haversine_km(a.lat.values, a.lon.values, b.lat.values, b.lon.values), np.nan)
    t['pair_km'] = t['pair_km'].astype('float32')
    one = t.rent_station.notna() ^ t.return_station.notna()
    t['trip_type'] = np.select([diff & (t.pair_km <= PAIR_MAX_KM), one], [HOP, LINK], default=OTHER)
    print(f'  기타 이동 중 두 역 2.5km 초과 역↔역 이동: {(diff & (t.pair_km > PAIR_MAX_KM)).sum():,}건')
    t['rent_day_type'] = day_type(t.rent_time, year)
    t['return_day_type'] = day_type(t.return_time, year)
    t['year'] = year
    for c in ('rent_station', 'return_station', 'trip_type', 'rent_day_type', 'return_day_type'):
        t[c] = t[c].astype('category')
    t.to_parquet(CACHE / f'trips_{year}.parquet', index=False)
    trips_clean[year] = t

# %% [1-6b] 이동 유형 비율 (2019 vs 2026, 전체 / 평일 / 주말, 제외일 빼고)
type_share = []
for year, t in trips_clean.items():
    for scope, mask in (('전체(제외일 제외)', t.rent_day_type != '제외일'),
                        ('평일', t.rent_day_type == '평일'), ('주말', t.rent_day_type == '주말')):
        vc = t.loc[mask, 'trip_type'].value_counts()
        for k, v in vc.items():
            type_share.append({'year': year, 'scope': scope, 'trip_type': k, 'trips': int(v),
                               'share_pct': round(v / vc.sum() * 100, 2)})
type_share = pd.DataFrame(type_share)
type_share.to_csv(TABLES / '01_trip_type_share.csv', index=False, encoding='utf-8-sig')
print(type_share.pivot_table(index=['scope', 'trip_type'], columns='year', values='share_pct').to_string())

# %% [1-7] 역별 집계: 역·날짜별 따릉이 역간 단거리/역 연계 이동 (출발·도착 양쪽 1건씩, 대여일시 기준)
section('[1-7] 역별 집계')
bike_daily = []
for year, t in trips_clean.items():
    t = t.assign(date=t.rent_time.dt.normalize())
    parts = []
    for col in ('rent_station', 'return_station'):
        g = (t[t.trip_type.isin([HOP, LINK]) & t[col].notna()]
             .groupby([col, 'date', 'trip_type'], observed=True).size().rename('n').reset_index()
             .rename(columns={col: 'station'}))
        parts.append(g)
    g = pd.concat(parts).groupby(['station', 'date', 'trip_type'], observed=True)['n'].sum().unstack('trip_type', fill_value=0)
    g = g.rename(columns={HOP: 'station_hop', LINK: 'station_link'})
    dates = pd.date_range(f'{year}-05-01', f'{year}-06-30')
    grid = pd.MultiIndex.from_product([analysis_stations, dates], names=['station', 'date'])
    g.index = g.index.set_levels(g.index.levels[0].astype(str), level=0)
    g = g.reindex(grid, fill_value=0).reset_index()
    g['year'] = year
    g['day_type'] = day_type(g['date'], year)
    bike_daily.append(g)
bike_daily = pd.concat(bike_daily, ignore_index=True)
bike_daily.to_parquet(CACHE / 'bike_station_daily.parquet', index=False)

station_daily = subway_daily.merge(bike_daily[['station', 'date', 'station_hop', 'station_link']],
                                   on=['station', 'date'], how='left')
station_avg = (station_daily[station_daily.day_type != '제외일']
               .groupby(['station', 'year', 'day_type'])[['riders', 'station_hop', 'station_link']].mean()
               .round(2).unstack(['year', 'day_type']))
station_avg.columns = [f'{m}_{y}_{"wd" if d == "평일" else "we"}' for m, y, d in station_avg.columns]
station_avg = station_avg.reset_index()
station_avg.to_csv(TABLES / '01_station_daily_avg.csv', index=False, encoding='utf-8-sig')
print(f'역별 하루 평균 표: {len(station_avg)}개 역 → 01_station_daily_avg.csv')

# %% [1-7b] 역별 배정 대여소 수 분포 (각 해 정제 후 대여이력에 등장한 대여소 기준)
assign_dist = []
for year, t in trips_clean.items():
    used = set(t.rent_no.unique()) | set(t.return_no.unique())
    b = bike_loc[bike_loc.bike_no.isin(used) & bike_loc.station.notna()]
    n = b.groupby('station').size().reindex(analysis_stations, fill_value=0)
    assign_dist.append(n.rename(f'bikes_{year}'))
    add_summary('대여소', year, '정제 후 이용 대여소', len(used))
    add_summary('대여소', year, '그중 역 500m 안 배정', len(b), len(used))
assign_dist = pd.concat(assign_dist, axis=1)
assign_dist.to_csv(TABLES / '01_bikes_per_station.csv', encoding='utf-8-sig')
print(assign_dist.describe().round(2).to_string())
for year in YEARS:
    c = assign_dist[f'bikes_{year}']
    print(f'[{year}] 배정 대여소 0개 역: {(c == 0).sum()}개, 분포: '
          f'{c.value_counts(bins=[-0.5, 0.5, 2.5, 5.5, 10.5, 100]).sort_index().to_dict()}')

# %% [1-7c] 증가율 대상 역: 2019 평일 하루 평균 10건 미만 제외 (가설① 역간 단거리 / 가설② 역 연계 각각)
MIN_2019_WD = 10
for key, col in (('hyp1', 'station_hop'), ('hyp2', 'station_link')):
    low = station_avg[f'{col}_2019_wd'] < MIN_2019_WD
    zero26 = station_avg[f'{col}_2026_wd'] == 0
    station_avg[f'{key}_eligible'] = ~low & ~zero26
    print(f'[{key}] {col} 2019 평일 10건 미만 제외: {low.sum()}개 역, 2026 평일 0 제외: {(~low & zero26).sum()}개 '
          f'→ 남은 역 {station_avg[f"{key}_eligible"].sum()}개')
    print(f'  제외 역(신규 따릉이권): {station_avg.loc[low, "station"].tolist()}')
    add_summary('역', None, f'{key} 대상 역 (2019 평일 {col} 10건 이상)',
                int(station_avg[f'{key}_eligible'].sum()), len(station_avg))
station_avg.to_csv(TABLES / '01_station_daily_avg.csv', index=False, encoding='utf-8-sig')

# %% [1-8] 정제 요약표
section('정제 요약표')
summary = pd.DataFrame(summary)
summary.to_csv(TABLES / '01_cleaning_summary.csv', index=False, encoding='utf-8-sig')
print(summary.to_string(index=False))
