"""5단계: 견고성 — (a) 두 해 모두 존재한 대여소만 (b) 하루 값 중앙값 (c) 지하철 증가율 상위 5% 역 제외."""
# %% [5-0] 설정
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 30)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data' / 'cache'
TABLES = ROOT / 'outputs' / 'tables'
YEARS = (2019, 2026)
HOP, LINK = '따릉이 역간 단거리 이동', '따릉이 역 연계 이동'
MORNING_HOURS = (7, 8)
MIN_2019_WD = 10
TOP_PCT = 0.95
ALPHA = 0.05

# %% [5-1] 데이터 읽기: 정제 대여이력, 지하철 역·날짜별
cols = ['rent_time', 'return_time', 'rent_no', 'return_no', 'rent_station', 'return_station',
        'trip_type', 'rent_day_type', 'return_day_type']
trips = {y: pd.read_parquet(CACHE / f'trips_{y}.parquet', columns=cols) for y in YEARS}
subway_daily = pd.read_parquet(CACHE / 'subway_daily.parquet')
stations = sorted(subway_daily.station.unique())
weekdays = {y: np.sort(subway_daily.loc[(subway_daily.year == y) & (subway_daily.day_type == '평일'), 'date'].unique())
            for y in YEARS}
subway_wd = subway_daily[subway_daily.day_type == '평일']


# %% [5-2] 공통 함수: 역별 평일 대표값(평균/중앙값), 검정 4개
def station_values(trips_by_year, agg):
    out = {}
    for y, t in trips_by_year.items():
        t = t[t.rent_day_type == '평일']
        t = t.assign(date=t.rent_time.dt.normalize())
        grid = pd.MultiIndex.from_product([stations, weekdays[y]], names=['station', 'date'])
        for tt, key in ((HOP, 'hop'), (LINK, 'link')):
            s = t[t.trip_type == tt]
            cnt = pd.concat([s[['rent_station', 'date']].rename(columns={'rent_station': 'station'}),
                             s[['return_station', 'date']].rename(columns={'return_station': 'station'})])
            cnt = cnt.dropna(subset=['station']).astype({'station': str}).groupby(['station', 'date']).size()
            out[f'{key}_{y}'] = cnt.reindex(grid, fill_value=0).groupby('station').agg(agg)
        out[f'subway_{y}'] = subway_wd[subway_wd.year == y].groupby('station')['riders'].agg(agg)
    return pd.DataFrame(out)


def growth_table(v, key, drop_stations=()):
    d = v[[f'{key}_2019', f'{key}_2026', 'subway_2019', 'subway_2026']].copy()
    d = d[(d[f'{key}_2019'] >= MIN_2019_WD) & (d[f'{key}_2026'] > 0) & ~d.index.isin(drop_stations)]
    d['bike_ratio'] = d[f'{key}_2026'] / d[f'{key}_2019']
    d['subway_ratio'] = d.subway_2026 / d.subway_2019
    return d


def spearman(d):
    r, p = stats.spearmanr(d.bike_ratio, d.subway_ratio)
    return {'n': len(d), 'stat': r, 'p': p}


def rank_groups(d):
    med = d.bike_ratio.median()
    hi = d.loc[d.bike_ratio > med, 'subway_ratio']
    lo = d.loc[d.bike_ratio <= med, 'subway_ratio']
    _, p = stats.mannwhitneyu(hi, lo, alternative='two-sided')
    return {'n': f'{len(hi)}/{len(lo)}', 'stat': (hi.median() - lo.median()) * 100, 'p': p}


def morning_share(trips_by_year):
    vals = {}
    for y, t in trips_by_year.items():
        t = t[(t.return_day_type == '평일') & t.return_time.dt.month.isin([5, 6]) & t.return_station.notna()]
        g = t.groupby(t.return_time.dt.normalize())['return_time'].agg(
            lambda s: s.dt.hour.isin(MORNING_HOURS).mean() * 100)
        vals[y] = g
    _, p = stats.mannwhitneyu(vals[2026], vals[2019], alternative='two-sided')
    return {'n': f'{len(vals[2019])}/{len(vals[2026])}', 'stat': vals[2026].median() - vals[2019].median(), 'p': p}


def run_all(trips_by_year, agg='mean', drop_stations=(), tests=('①-1', '①-2', '②-1', '②-2')):
    v = station_values(trips_by_year, agg)
    hop, link = growth_table(v, 'hop', drop_stations), growth_table(v, 'link', drop_stations)
    res = {}
    if '①-1' in tests:
        res['①-1'] = spearman(hop)
    if '①-2' in tests:
        res['①-2'] = rank_groups(hop)
    if '②-1' in tests:
        res['②-1'] = morning_share(trips_by_year)
    if '②-2' in tests:
        res['②-2'] = spearman(link)
    return res, v


# %% [5-3] 본 분석 (3·4단계와 같은 값인지 확인)
main, main_v = run_all(trips)
for k, r in main.items():
    print(f'본 분석 {k}: n={r["n"]}, 통계={r["stat"]:.3f}, p{"<" if r["p"] < ALPHA else ">"}0.05')

# %% [5-4] (a) 두 해 모두 존재한 대여소만 (출발·도착 대여소가 모두 두 해 정제 대여이력에 등장)
used = {y: set(t.rent_no.dropna()) | set(t.return_no.dropna()) for y, t in trips.items()}
common = used[2019] & used[2026]
trips_a = {y: t[t.rent_no.isin(common) & t.return_no.isin(common)] for y, t in trips.items()}
for y in YEARS:
    print(f'(a) {y}: 대여소 {len(used[y]):,} → 공통 {len(common):,}, 이동 {len(trips[y]):,} → {len(trips_a[y]):,}건 '
          f'({len(trips_a[y]) / len(trips[y]) * 100:.1f}%)')
res_a, _ = run_all(trips_a)

# %% [5-5] (b) 역별 대표값 = 평일 하루 값의 중앙값 (②-1은 역별 대표값이 없어 해당 없음)
res_b, _ = run_all(trips, agg='median', tests=('①-1', '①-2', '②-2'))

# %% [5-6] (c) 지하철 평일 증가율 상위 5% 역 제외 (분석 대상 295개 역 기준)
sub_growth = (main_v.subway_2026 / main_v.subway_2019 - 1) * 100
cut = sub_growth.quantile(TOP_PCT)
top_stations = sub_growth[sub_growth > cut].sort_values(ascending=False)
print(f'(c) 지하철 증가율 상위 5% 기준 {cut:+.1f}% 초과 → 제외 {len(top_stations)}개 역:')
print(top_stations.round(1).to_string())
top_stations.round(2).rename('subway_growth_pct').to_csv(TABLES / '05_excluded_top5pct_stations.csv',
                                                          encoding='utf-8-sig')
res_c, _ = run_all(trips, drop_stations=set(top_stations.index), tests=('①-1', '②-2'))

# %% [5-7] 비교표: 방향·유의 여부가 본 분석과 같으면 유지
STAT_LABEL = {'①-1': 'ρ', '①-2': '지하철 증가율 중앙값 차이(많이 는−적게 는, %p)',
              '②-1': '7~9시 비중 중앙값 차이(2026−2019, %p)', '②-2': 'ρ'}
rows = []
for test, m in main.items():
    rows.append({'test': test, 'variant': '본 분석', 'stat_name': STAT_LABEL[test], 'n': m['n'],
                 'stat': m['stat'], 'direction': '+' if m['stat'] > 0 else '−',
                 'sig': 'p<0.05' if m['p'] < ALPHA else 'p>0.05', 'verdict': '-'})
    for name, res in (('(a) 공통 대여소', res_a), ('(b) 하루 값 중앙값', res_b), ('(c) 상위 5% 역 제외', res_c)):
        if test not in res:
            rows.append({'test': test, 'variant': name, 'stat_name': STAT_LABEL[test], 'n': '-', 'stat': None,
                         'direction': '-', 'sig': '-', 'verdict': '해당 없음'})
            continue
        r = res[test]
        same = ((r['stat'] > 0) == (m['stat'] > 0)) and ((r['p'] < ALPHA) == (m['p'] < ALPHA))
        rows.append({'test': test, 'variant': name, 'stat_name': STAT_LABEL[test], 'n': r['n'],
                     'stat': r['stat'], 'direction': '+' if r['stat'] > 0 else '−',
                     'sig': 'p<0.05' if r['p'] < ALPHA else 'p>0.05', 'verdict': '유지' if same else '변화'})
comp = pd.DataFrame(rows)
comp.to_csv(TABLES / '05_robustness_comparison.csv', index=False, encoding='utf-8-sig')
pd.DataFrame([{'test': t, 'variant': v, 'p_value': r['p']} for v, res in
              (('본 분석', main), ('(a)', res_a), ('(b)', res_b), ('(c)', res_c)) for t, r in res.items()]
             ).to_csv(TABLES / '05_robustness_p_detail.csv', index=False, encoding='utf-8-sig')
print(comp.to_string(index=False))
