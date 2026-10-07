"""2단계: 큰 그림 — 2019→2026 지하철·따릉이 하루 평균 변화, 이동 유형별 비중 변화."""
# %% [2-0] 설정
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.width', 250)

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data' / 'cache'
TABLES = ROOT / 'outputs' / 'tables'
YEARS = (2019, 2026)
SUBWAY_LABEL = '지하철 (분석 대상 295개 역)'  # 승하차 합계
BIKE_LABEL = '따릉이 (서울 전체)'  # 정제 후 전체 이동
TRIP_TYPES = ['따릉이 역간 단거리 이동', '따릉이 역 연계 이동', '따릉이 기타 이동']


def mean_ci(values):
    v = np.asarray(values, dtype=float)
    n = len(v)
    m = v.mean()
    half = stats.t.ppf(0.975, n - 1) * v.std(ddof=1) / np.sqrt(n)
    return n, m, m - half, m + half


# %% [2-1] 날짜별 합계: 지하철(분석 대상 역 전체 승하차) / 따릉이(정제 후 전체 이동, 대여일시 기준)
subway_daily = pd.read_parquet(CACHE / 'subway_daily.parquet')
subway_day = subway_daily.groupby(['year', 'date', 'day_type'], as_index=False)['riders'].sum()

bike_day = []
for year in YEARS:
    t = pd.read_parquet(CACHE / f'trips_{year}.parquet', columns=['rent_time', 'rent_day_type', 'trip_type'])
    d = (t.assign(date=t.rent_time.dt.normalize())
         .groupby(['date', 'rent_day_type', 'trip_type'], observed=True).size().unstack('trip_type', fill_value=0)
         .reset_index().rename(columns={'rent_day_type': 'day_type'}))
    d['year'] = year
    bike_day.append(d)
bike_day = pd.concat(bike_day, ignore_index=True)
bike_day['bike_trips'] = bike_day[TRIP_TYPES].sum(axis=1)

daily = subway_day.merge(bike_day, on=['year', 'date', 'day_type'], how='outer')
daily['day_type'] = daily['day_type'].astype(str)
daily = daily[daily.day_type != '제외일']
daily.to_csv(TABLES / '02_overview_daily.csv', index=False, encoding='utf-8-sig')
print(f'날짜 수: {daily.groupby(["year", "day_type"]).size().to_dict()}')

# %% [2-2] 하루 평균 + 95% 신뢰구간 (단위: 날짜)
rows = []
for measure, label in (('riders', SUBWAY_LABEL), ('bike_trips', BIKE_LABEL)):
    for day_type in ('평일', '주말'):
        for year in YEARS:
            v = daily.loc[(daily.year == year) & (daily.day_type == day_type), measure]
            n, m, lo, hi = mean_ci(v)
            rows.append({'measure': label, 'day_type': day_type, 'year': year, 'n_days': n,
                         'mean': round(m), 'ci_low': round(lo), 'ci_high': round(hi)})
overview = pd.DataFrame(rows)
change = (overview.pivot_table(index=['measure', 'day_type'], columns='year', values='mean')
          .assign(change_pct=lambda x: ((x[2026] / x[2019] - 1) * 100).round(1)))
overview = overview.merge(change['change_pct'].reset_index(), on=['measure', 'day_type'])
overview.to_csv(TABLES / '02_overview_summary.csv', index=False, encoding='utf-8-sig')
print(overview.to_string(index=False))

# %% [2-3] 이동 유형별 비중 (전체 기간 합 기준) + 하루 평균 건수
type_rows = []
for day_type in ('평일', '주말'):
    for year in YEARS:
        d = daily[(daily.year == year) & (daily.day_type == day_type)]
        total = d[TRIP_TYPES].sum().sum()
        for tt in TRIP_TYPES:
            type_rows.append({'day_type': day_type, 'year': year, 'trip_type': tt,
                              'daily_avg': round(d[tt].mean()), 'share_pct': round(d[tt].sum() / total * 100, 2)})
trip_types = pd.DataFrame(type_rows)
trip_types.to_csv(TABLES / '02_trip_type_share.csv', index=False, encoding='utf-8-sig')
print(trip_types.pivot_table(index=['day_type', 'trip_type'], columns='year',
                             values=['share_pct', 'daily_avg']).to_string())
