"""3단계: 가설①(경쟁) — 따릉이 역간 단거리 이동 증가율 vs 지하철 증가율 (단위: 역, 평일 하루 평균)."""
# %% [3-0] 설정
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
MIN_2019_WD = 10
PAIR_KM_OPTIONS = (1.5, 2.5, 3.0)
MAIN_KM = 2.5
ALPHA = 0.05
N_BOOT = 5000
rng = np.random.default_rng(42)

H0_1 = '2019→2026 평일 하루 평균 따릉이 역간 단거리 이동 증가율과 지하철 이용 증가율 사이에 상관이 없다 (ρ=0)'
H1_1 = '상관이 있다 (ρ≠0)'
H0_2 = '역간 단거리 이동 증가율 많이 는 역 / 적게 는 역의 평일 하루 평균 지하철 이용 증가율 분포가 같다'
H1_2 = '분포가 다르다'


def strength(r):
    a = abs(r)
    return '약함' if a < 0.3 else ('중간' if a < 0.7 else '강함')


def shapiro_text(series_by_name):
    parts = []
    for name, s in series_by_name.items():
        p = stats.shapiro(s).pvalue
        parts.append(f'{name} {"정규" if p >= ALPHA else "비정규"}(Shapiro p{">=" if p >= ALPHA else "<"}0.05)')
    return ', '.join(parts)


def boot_median_ci(v):
    v = np.asarray(v)
    meds = np.median(rng.choice(v, size=(N_BOOT, len(v)), replace=True), axis=1)
    return np.percentile(meds, [2.5, 97.5])


# %% [3-1] 역별 평일 하루 평균: 지하철 (1단계 결과) + 따릉이 역간 단거리 이동 (거리 기준별로 다시 셈)
subway_daily = pd.read_parquet(CACHE / 'subway_daily.parquet')
weekdays = {y: subway_daily.loc[(subway_daily.year == y) & (subway_daily.day_type == '평일'), 'date'].unique()
            for y in YEARS}
n_weekdays = {y: len(d) for y, d in weekdays.items()}
subway_wd = (subway_daily[subway_daily.day_type == '평일'].groupby(['station', 'year'])['riders'].mean()
             .unstack('year').rename(columns=lambda y: f'subway_{y}'))
stations = subway_wd.index

hop_wd = {km: {} for km in PAIR_KM_OPTIONS}
hop_pairs_wd = {}
for year in YEARS:
    t = pd.read_parquet(CACHE / f'trips_{year}.parquet',
                        columns=['rent_station', 'return_station', 'pair_km', 'rent_day_type'])
    t = t[(t.rent_day_type == '평일') & t.pair_km.notna()]
    for km in PAIR_KM_OPTIONS:
        h = t[t.pair_km <= km]
        cnt = (h.rent_station.astype(str).value_counts().add(h.return_station.astype(str).value_counts(), fill_value=0))
        hop_wd[km][year] = (cnt.reindex(stations, fill_value=0) / n_weekdays[year])
    h = t[t.pair_km <= MAIN_KM]
    a, b = h.rent_station.astype(str), h.return_station.astype(str)
    pair = pd.Series(np.where(a < b, a + ' ↔ ' + b, b + ' ↔ ' + a))
    hop_pairs_wd[year] = pair.value_counts() / n_weekdays[year]
    print(f'[{year}] 평일 {n_weekdays[year]}일, 역간 단거리 이동(2.5km) 평일 하루 평균 '
          f'{len(t[t.pair_km <= MAIN_KM]) / n_weekdays[year]:,.0f}건')

# 1단계 결과와 같은지 확인 (2.5km)
check = pd.read_csv(TABLES / '01_station_daily_avg.csv').set_index('station')
diff = (hop_wd[MAIN_KM][2019] - check['station_hop_2019_wd']).abs().max()
print(f'1단계 역별 평균과 최대 차이: {diff:.4f}')


def build_growth(km):
    d = subway_wd.copy()
    d['hop_2019'], d['hop_2026'] = hop_wd[km][2019], hop_wd[km][2026]
    low = d.hop_2019 < MIN_2019_WD
    zero = ~low & (d.hop_2026 == 0)
    d = d[~low & ~zero].copy()
    d['hop_ratio'] = d.hop_2026 / d.hop_2019
    d['subway_ratio'] = d.subway_2026 / d.subway_2019
    d['hop_growth_pct'] = (d.hop_ratio - 1) * 100
    d['subway_growth_pct'] = (d.subway_ratio - 1) * 100
    med = d.hop_ratio.median()
    d['group'] = np.where(d.hop_ratio > med, '많이 는 역', '적게 는 역')
    return d, int(low.sum()), int(zero.sum()), med


def run_tests(d):
    rho, p_rho = stats.spearmanr(d.hop_ratio, d.subway_ratio)
    hi = d.loc[d.group == '많이 는 역', 'subway_ratio']
    lo = d.loc[d.group == '적게 는 역', 'subway_ratio']
    w, p_w = stats.mannwhitneyu(hi, lo, alternative='two-sided')
    return rho, p_rho, w, p_w, hi, lo


# %% [3-2] 본 분석 데이터 (2.5km): 제외 역 수
growth, n_low, n_zero, med_ratio = build_growth(MAIN_KM)
print(f'2019 평일 10건 미만 제외 {n_low}개, 2026 평일 0건 제외 {n_zero}개 → 분석 역 {len(growth)}개')
print(f'역간 단거리 이동 증가율 중앙값: {(med_ratio - 1) * 100:+.1f}% | 지하철 증가율 중앙값: '
      f'{growth.subway_growth_pct.median():+.1f}%')
print(growth[['hop_growth_pct', 'subway_growth_pct']].describe().round(1).to_string())

# %% [3-3] 검정 근거: Shapiro 정규성
shapiro_main = shapiro_text({'역간 단거리 증가율': growth.hop_ratio, '지하철 증가율': growth.subway_ratio})
shapiro_groups = shapiro_text({g: growth.loc[growth.group == g, 'subway_ratio'] for g in ('많이 는 역', '적게 는 역')})
print(f'Shapiro: {shapiro_main} | 그룹별 지하철 증가율: {shapiro_groups}')

# %% [3-4] ①-1: 따릉이 역간 단거리 이동 증가율 vs 지하철 증가율 — Spearman (역 n개)
rho, p_rho, w, p_w, hi, lo = run_tests(growth)
pearson_note = ''
if stats.shapiro(growth.hop_ratio).pvalue >= ALPHA and stats.shapiro(growth.subway_ratio).pvalue >= ALPHA:
    r_p, p_p = stats.pearsonr(growth.hop_ratio, growth.subway_ratio)
    pearson_note = f'참고 Pearson r={r_p:.2f}, p{"<" if p_p < ALPHA else ">"}0.05'
print(f'①-1 Spearman: n={len(growth)}, ρ={rho:.2f} ({"양" if rho > 0 else "음"}, {strength(rho)}), '
      f'p{"<" if p_rho < ALPHA else ">"}0.05 {pearson_note}')

# %% [3-5] ①-2: 역간 단거리 이동 많이 는 역 vs 적게 는 역의 지하철 증가율 — 순위합 검정(W)
print(f'①-2 순위합 검정(W): 많이 는 역 n={len(hi)} (지하철 증가율 중앙값 {(hi.median() - 1) * 100:+.1f}%), '
      f'적게 는 역 n={len(lo)} (중앙값 {(lo.median() - 1) * 100:+.1f}%), W={w:.0f}, p{"<" if p_w < ALPHA else ">"}0.05')


# %% [3-6] 결과 읽는 법에 따른 해석
def read_spearman(rho, p):
    if p >= ALPHA:
        return '상관 유의하지 않음 → 경쟁 근거 없음'
    return '음(−) 상관 → 경쟁 지지' if rho < 0 else '양(+) 상관 → 같이 느는 관계'


def read_rank(hi, lo, p):
    if p >= ALPHA:
        return '두 그룹 차이 없음'
    return '많이 는 그룹의 지하철 증가율이 낮음 → 경쟁 지지' if hi.median() < lo.median() \
        else '많이 는 그룹의 지하철 증가율이 높음 → 같이 느는 관계'


read_1 = read_spearman(rho, p_rho)
read_2 = read_rank(hi, lo, p_w)
consistent = ((rho > 0) == (hi.median() > lo.median())) and ((p_rho < ALPHA) == (p_w < ALPHA))
print(f'해석: ①-1 {read_1} / ①-2 {read_2} / 두 방법 {"일관됨" if consistent else "불일치"}')

# %% [3-7] 민감도: 거리 기준 1.5 / 2.5 / 3km
sens = []
for km in PAIR_KM_OPTIONS:
    d, nl, nz, _ = build_growth(km)
    r, pr, ww, pw, h_, l_ = run_tests(d)
    sens.append({'pair_km': km, 'n_stations': len(d), 'excluded_low_2019': nl, 'excluded_zero_2026': nz,
                 'spearman_rho': r, 'spearman_sig': pr < ALPHA, 'spearman_dir': '양' if r > 0 else '음',
                 'w': round(ww), 'w_sig': pw < ALPHA,
                 'median_subway_growth_high_pct': round((h_.median() - 1) * 100, 2),
                 'median_subway_growth_low_pct': round((l_.median() - 1) * 100, 2)})
sens = pd.DataFrame(sens)
sens.to_csv(TABLES / '03_hyp1_sensitivity.csv', index=False, encoding='utf-8-sig')
print(sens.to_string(index=False))

# %% [3-8] 결과 저장: 역별 증가율, 그룹 막대용 요약, 검정 상세, tests_summary
growth.reset_index().to_csv(TABLES / '03_hyp1_station_growth.csv', index=False, encoding='utf-8-sig')

bar = []
for g, v in (('많이 는 역', hi), ('적게 는 역', lo)):
    ci = boot_median_ci((v - 1) * 100)
    bar.append({'group': g, 'n': len(v), 'median_subway_growth_pct': round((v.median() - 1) * 100, 2),
                'ci_low': round(ci[0], 2), 'ci_high': round(ci[1], 2)})
bar = pd.DataFrame(bar)
bar['stars'] = '**' if p_w < 0.01 else ('*' if p_w < ALPHA else '')
bar.to_csv(TABLES / '03_hyp1_group_bar.csv', index=False, encoding='utf-8-sig')

detail = pd.DataFrame([
    {'test_id': '①-1', 'stat_name': 'rho', 'stat': rho, 'p_value': p_rho, 'n': len(growth)},
    {'test_id': '①-2', 'stat_name': 'W', 'stat': w, 'p_value': p_w, 'n': f'{len(hi)}/{len(lo)}'},
])
detail.to_csv(TABLES / '03_hyp1_tests_detail.csv', index=False, encoding='utf-8-sig')

summary_rows = [
    {'가설': '가설①(경쟁)', '검정ID': '①-1',
     '질문': '따릉이 역간 단거리 이동이 많이 는 역일수록 지하철 이용이 덜 늘었나?',
     '검정명': 'Spearman', '분석 단위': '역', 'n': str(len(growth)), 'Shapiro 결과': shapiro_main,
     'H0': H0_1, 'H1': H1_1, '통계량': f'ρ = {rho:.2f} ({"양" if rho > 0 else "음"}, {strength(rho)})',
     'p<0.05': 'p<0.05' if p_rho < ALPHA else 'p>0.05', '결과 해석': read_1},
    {'가설': '가설①(경쟁)', '검정ID': '①-2',
     '질문': '역간 단거리 이동이 많이 는 역은 적게 는 역보다 지하철 증가율이 낮은가?',
     '검정명': '순위합 검정(W)', '분석 단위': '역', 'n': f'{len(hi)} / {len(lo)}', 'Shapiro 결과': shapiro_groups,
     'H0': H0_2, 'H1': H1_2, '통계량': f'W = {w:.0f}',
     'p<0.05': 'p<0.05' if p_w < ALPHA else 'p>0.05',
     '결과 해석': read_2 + (' (①-1과 두 방법에서 일관됨)' if consistent else ' (①-1과 불일치)')},
]
path = TABLES / 'tests_summary.csv'
old = pd.read_csv(path, encoding='utf-8-sig', dtype=str) if path.exists() else pd.DataFrame()
if len(old):
    old = old[~old['검정ID'].isin(['①-1', '①-2'])]
pd.concat([old, pd.DataFrame(summary_rows)], ignore_index=True).sort_values('검정ID').to_csv(
    path, index=False, encoding='utf-8-sig')

# %% [3-9] 따릉이 역간 단거리 이동이 많은 역 구간 Top 10 (2026 평일 하루 평균)
top = pd.DataFrame({'wd_2019': hop_pairs_wd[2019], 'wd_2026': hop_pairs_wd[2026]}).fillna(0)
top = top.sort_values('wd_2026', ascending=False).head(10)
top['growth_pct'] = np.where(top.wd_2019 > 0, (top.wd_2026 / top.wd_2019 - 1) * 100, np.nan)
top = top.round(1).rename_axis('pair').reset_index()
top.to_csv(TABLES / '03_hyp1_top10_pairs.csv', index=False, encoding='utf-8-sig')
print(top.to_string(index=False))
