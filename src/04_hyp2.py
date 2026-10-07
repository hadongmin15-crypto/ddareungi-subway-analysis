"""4단계: 가설②(동반) — 평일 출근 시간 역 근처 반납 비중, 따릉이 역 연계 이동 증가율 vs 지하철 증가율."""
# %% [4-0] 설정
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
MORNING_HOURS = (7, 8)  # 7~9시 = 07:00~08:59
MIN_2019_WD = 10
ALPHA = 0.05
N_BOOT = 5000
rng = np.random.default_rng(42)

H0_21 = '2019와 2026의 평일 7~9시 역 근처 반납 비중 분포가 같다'
H1_21 = '분포가 다르다'
H0_22 = '2019→2026 평일 하루 평균 따릉이 역 연계 이동 증가율과 지하철 이용 증가율 사이에 상관이 없다 (ρ=0)'
H1_22 = '상관이 있다 (ρ≠0)'


def strength(r):
    a = abs(r)
    return '약함' if a < 0.3 else ('중간' if a < 0.7 else '강함')


def is_normal(s):
    return stats.shapiro(s).pvalue >= ALPHA


def shapiro_text(series_by_name):
    return ', '.join(f'{k} {"정규" if is_normal(v) else "비정규"}(Shapiro p{">=" if is_normal(v) else "<"}0.05)'
                     for k, v in series_by_name.items())


def boot_median_ci(v):
    v = np.asarray(v)
    meds = np.median(rng.choice(v, size=(N_BOOT, len(v)), replace=True), axis=1)
    return np.percentile(meds, [2.5, 97.5])


# %% [4-1] 평일 반납 (반납일시 기준, 5~6월 반납만): 역 근처 반납 / 역에서 먼 반납
returns = []
for year in YEARS:
    t = pd.read_parquet(CACHE / f'trips_{year}.parquet', columns=['return_time', 'return_station', 'return_day_type'])
    t = t[(t.return_day_type == '평일') & t.return_time.dt.month.isin([5, 6])]
    returns.append(pd.DataFrame({'year': year, 'date': t.return_time.dt.normalize(), 'hour': t.return_time.dt.hour,
                                 'near_station': t.return_station.notna().values}))
returns = pd.concat(returns, ignore_index=True)
print(f'평일 반납: {returns.groupby(["year", "near_station"]).size().to_dict()}')

# %% [4-2] 평일 시간대별 반납 분포 (각 연도·구분 안에서 비중 %)
hourly = returns.groupby(['year', 'near_station', 'hour']).size().rename('n').reset_index()
hourly['share_pct'] = hourly.n / hourly.groupby(['year', 'near_station']).n.transform('sum') * 100
n_days = returns.groupby('year').date.nunique()
hourly['daily_avg'] = hourly.n / hourly.year.map(n_days)
hourly['where'] = np.where(hourly.near_station, '역 근처 반납', '역에서 먼 반납')
hourly.to_csv(TABLES / '04_hyp2_hourly.csv', index=False, encoding='utf-8-sig')
morning = hourly[hourly.hour.isin(MORNING_HOURS)].groupby(['year', 'where'])['share_pct'].sum().unstack()
print(f'평일 7~9시 반납 비중(%, 기간 합 기준):\n{morning.round(2).to_string()}')

# %% [4-3] 평일 하루 단위: 역 근처 반납 중 7~9시 비중
near = returns[returns.near_station]
daily = near.groupby(['year', 'date']).agg(near_returns=('hour', 'size'),
                                           morning_returns=('hour', lambda h: h.isin(MORNING_HOURS).sum()))
daily['morning_share_pct'] = daily.morning_returns / daily.near_returns * 100
daily = daily.reset_index()
daily.to_csv(TABLES / '04_hyp2_daily_share.csv', index=False, encoding='utf-8-sig')
s19 = daily.loc[daily.year == 2019, 'morning_share_pct']
s26 = daily.loc[daily.year == 2026, 'morning_share_pct']
m19 = daily.loc[daily.year == 2019, 'morning_returns']
m26 = daily.loc[daily.year == 2026, 'morning_returns']

# %% [4-4] 검정 근거: Shapiro (②-1 하루 비중)
shapiro_21 = shapiro_text({'2019 하루 비중': s19, '2026 하루 비중': s26})
print(f'Shapiro ②-1: {shapiro_21} (n={len(s19)} / {len(s26)})')
t_note_21 = ''
if is_normal(s19) and is_normal(s26) and min(len(s19), len(s26)) >= 30:
    _, p_t = stats.ttest_ind(s26, s19, equal_var=False)
    t_note_21 = f'참고 t검정(Welch) p{"<" if p_t < ALPHA else ">"}0.05'

# %% [4-5] ②-1: 평일 7~9시 역 근처 반납 비중 2019 vs 2026 — 순위합 검정(W) (평일 하루 n개)
w_21, p_21 = stats.mannwhitneyu(s26, s19, alternative='two-sided')
print(f'②-1 순위합 검정(W): 2019 n={len(s19)} 중앙값 {s19.median():.2f}% (7~9시 하루 평균 {m19.mean():,.0f}건) / '
      f'2026 n={len(s26)} 중앙값 {s26.median():.2f}% (하루 평균 {m26.mean():,.0f}건), W={w_21:.0f}, '
      f'p{"<" if p_21 < ALPHA else ">"}0.05 {t_note_21}')
print(f'역 근처 반납 전체 하루 평균: 2019 {daily.loc[daily.year == 2019, "near_returns"].mean():,.0f}건 / '
      f'2026 {daily.loc[daily.year == 2026, "near_returns"].mean():,.0f}건')

if p_21 >= ALPHA:
    read_21 = '변화 없음'
elif s26.median() > s19.median():
    read_21 = '2026 비중이 높음 → 출근 연계 역할 커짐, 동반 지지'
else:
    read_21 = (f'2026 비중이 낮음 → 7~9시 반납 건수는 하루 평균 {m19.mean():,.0f}→{m26.mean():,.0f}건으로 '
               f'{"늘어" if m26.mean() > m19.mean() else "줄어"} 다른 시간대 이용이 더 늘어 비중이 묽어진 것으로 판단'
               if m26.mean() > m19.mean() else '2026 비중·건수 모두 낮음 → 출근 연계 역할 약해짐')

# %% [4-6] 역별 평일 하루 평균: 따릉이 역 연계 이동 (1단계 집계) + 지하철
bike_daily = pd.read_parquet(CACHE / 'bike_station_daily.parquet')
subway_daily = pd.read_parquet(CACHE / 'subway_daily.parquet')
link_wd = bike_daily[bike_daily.day_type == '평일'].groupby(['station', 'year'])['station_link'].mean().unstack()
subway_wd = subway_daily[subway_daily.day_type == '평일'].groupby(['station', 'year'])['riders'].mean().unstack()
g = pd.DataFrame({'link_2019': link_wd[2019], 'link_2026': link_wd[2026],
                  'subway_2019': subway_wd[2019], 'subway_2026': subway_wd[2026]})
low = g.link_2019 < MIN_2019_WD
zero = ~low & (g.link_2026 == 0)
g = g[~low & ~zero].copy()
g['link_ratio'] = g.link_2026 / g.link_2019
g['subway_ratio'] = g.subway_2026 / g.subway_2019
g['link_growth_pct'] = (g.link_ratio - 1) * 100
g['subway_growth_pct'] = (g.subway_ratio - 1) * 100
g.reset_index().rename(columns={'index': 'station'}).to_csv(TABLES / '04_hyp2_station_growth.csv',
                                                            index=False, encoding='utf-8-sig')
print(f'②-2 대상: 2019 평일 10건 미만 제외 {low.sum()}개, 2026 평일 0건 제외 {zero.sum()}개 → {len(g)}개 역')
print(f'역 연계 이동 증가율 중앙값 {g.link_growth_pct.median():+.1f}%, 지하철 증가율 중앙값 {g.subway_growth_pct.median():+.1f}%')

# %% [4-7] 검정 근거: Shapiro (②-2 증가율)
shapiro_22 = shapiro_text({'역 연계 증가율': g.link_ratio, '지하철 증가율': g.subway_ratio})
print(f'Shapiro ②-2: {shapiro_22}')
p_note_22 = ''
if is_normal(g.link_ratio) and is_normal(g.subway_ratio):
    r_p, p_p = stats.pearsonr(g.link_ratio, g.subway_ratio)
    p_note_22 = f'참고 Pearson r={r_p:.2f}, p{"<" if p_p < ALPHA else ">"}0.05'

# %% [4-8] ②-2: 따릉이 역 연계 이동 증가율 vs 지하철 증가율 — Spearman (역 n개)
rho_22, p_22 = stats.spearmanr(g.link_ratio, g.subway_ratio)
print(f'②-2 Spearman: n={len(g)}, ρ={rho_22:.2f} ({"양" if rho_22 > 0 else "음"}, {strength(rho_22)}), '
      f'p{"<" if p_22 < ALPHA else ">"}0.05 {p_note_22}')
if p_22 < ALPHA and rho_22 > 0:
    read_22 = '양(+) 상관 → 동반 지지'
elif p_22 < ALPHA:
    read_22 = '음(−) 상관 → 함께 늘었다고 볼 근거 없음 (반대 방향)'
else:
    read_22 = '함께 늘었다고 볼 근거 없음'

tests = pd.read_csv(TABLES / 'tests_summary.csv', encoding='utf-8-sig', dtype=str)
rho_11 = float(tests.set_index('검정ID').loc['①-1', '통계량'].split('=')[1].split('(')[0])
if rho_22 > 0 and rho_11 <= 0:
    joint = '역 연계 ρ>0, 역간 단거리 ρ≤0 → 동반 쪽이 확실'
elif rho_22 > 0 and rho_11 > 0:
    joint = '둘 다 양(+) → 동네 성장 효과일 가능성 (한계에 명시)'
else:
    joint = '역 연계 ρ≤0 → 동반 근거 약함'
print(f'종합(①-1 vs ②-2): ①-1 ρ={rho_11:.2f}, ②-2 ρ={rho_22:.2f} → {joint}')

# %% [4-9] 결과 저장: 막대 그래프용 요약, 검정 상세, tests_summary
bar = []
for year, v, m in ((2019, s19, m19), (2026, s26, m26)):
    ci = boot_median_ci(v)
    bar.append({'year': year, 'n_days': len(v), 'median_share_pct': round(v.median(), 2),
                'ci_low': round(ci[0], 2), 'ci_high': round(ci[1], 2), 'morning_returns_daily_avg': round(m.mean())})
bar = pd.DataFrame(bar)
bar['stars'] = '**' if p_21 < 0.01 else ('*' if p_21 < ALPHA else '')
bar.to_csv(TABLES / '04_hyp2_share_bar.csv', index=False, encoding='utf-8-sig')

pd.DataFrame([
    {'test_id': '②-1', 'stat_name': 'W', 'stat': w_21, 'p_value': p_21, 'n': f'{len(s19)}/{len(s26)}'},
    {'test_id': '②-2', 'stat_name': 'rho', 'stat': rho_22, 'p_value': p_22, 'n': len(g)},
]).to_csv(TABLES / '04_hyp2_tests_detail.csv', index=False, encoding='utf-8-sig')

rows = [
    {'가설': '가설②(동반)', '검정ID': '②-1',
     '질문': '평일 출근 시간(7~9시)에 역 근처 반납이 2019보다 2026에 더 몰리나?',
     '검정명': '순위합 검정(W)', '분석 단위': '평일 하루', 'n': f'{len(s19)} / {len(s26)}', 'Shapiro 결과': shapiro_21,
     'H0': H0_21, 'H1': H1_21, '통계량': f'W = {w_21:.0f}', 'p<0.05': 'p<0.05' if p_21 < ALPHA else 'p>0.05',
     '결과 해석': read_21},
    {'가설': '가설②(동반)', '검정ID': '②-2',
     '질문': '따릉이 역 연계 이동이 많이 는 역일수록 지하철도 더 늘었나?',
     '검정명': 'Spearman', '분석 단위': '역', 'n': str(len(g)), 'Shapiro 결과': shapiro_22,
     'H0': H0_22, 'H1': H1_22, '통계량': f'ρ = {rho_22:.2f} ({"양" if rho_22 > 0 else "음"}, {strength(rho_22)})',
     'p<0.05': 'p<0.05' if p_22 < ALPHA else 'p>0.05', '결과 해석': f'{read_22} / 종합: {joint}'},
]
tests = tests[~tests['검정ID'].isin(['②-1', '②-2'])]
pd.concat([tests, pd.DataFrame(rows)], ignore_index=True).sort_values('검정ID').to_csv(
    TABLES / 'tests_summary.csv', index=False, encoding='utf-8-sig')
print(f'해석: ②-1 {read_21} / ②-2 {read_22}')
