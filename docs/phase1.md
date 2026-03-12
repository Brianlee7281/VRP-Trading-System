# Phase 1 — VIX Proxy Backtest

**Goal: Validate that regime-conditioned short vol has positive expected value before spending any money.**

> Phase 1 uses only free data. No Polygon.io subscription. No IBKR connection. No options chain.
> The question Phase 1 answers: "Does regime detection meaningfully improve naive short vol?"
> If the answer is NO → stop. The strategy doesn't work. No need for Phase 2.
> If the answer is YES → Phase 2 validates with real options data.

---

## Table of Contents

1. [Phase Scope](#1-phase-scope)
2. [Data Sources & Acquisition](#2-data-sources--acquisition)
3. [Module Activation Map](#3-module-activation-map)
4. [Task Breakdown](#4-task-breakdown)
5. [VRP Proxy Backtest Methodology](#5-vrp-proxy-backtest-methodology)
6. [Regime Detection Validation](#6-regime-detection-validation)
7. [Risk Management Validation](#7-risk-management-validation)
8. [GO / NO-GO Criteria](#8-go--no-go-criteria)
9. [Deliverables & Completion Checklist](#9-deliverables--completion-checklist)

---

## 1. Phase Scope

### 1.1 What Phase 1 Does

- Fetches 20 years of free market data (SPX, VIX, VIX3M, VVIX, risk-free rate)
- Computes derived features (RV, VRP proxy, term structure, vol acceleration)
- Trains HMM regime detector (3-state: Low-Vol / Normal-Vol / High-Vol)
- Trains XGBoost classifier on HMM labels with calibrated probabilities
- Simulates VRP harvesting using a variance-swap proxy (not actual options)
- Applies full risk management stack (vol scaling, Kelly, DD override)
- Compares regime-conditioned vs naive (no regime) performance
- Produces GO / NO-GO verdict

### 1.2 What Phase 1 Does NOT Do

| Not in Phase 1 | Why | When |
|----------------|-----|------|
| Real options data | Costs $29/mo (Polygon) | Phase 2 |
| Heston calibration | No options chain to calibrate against | Phase 2 |
| Carr-Madan FFT | Not needed without Heston | Phase 2 |
| IBKR connection | No execution needed | Phase 3 |
| Orchestration/scheduler | Batch backtest, not daily operations | Phase 3 |
| Alerts/daily report | No live system to monitor | Phase 3 |
| Specific strike selection | No vol surface → BS delta approximation only | Phase 2 |

### 1.3 Key Simplifications

**No actual options are traded in Phase 1.** Instead, we simulate the P&L of a hypothetical short variance position using the VRP proxy:

$$r_{\text{proxy},t} = \frac{1}{\tau}\left(\frac{\text{VIX}_{t-\tau}^2}{252} - \frac{\text{RV}_t(\tau)^2}{252}\right) \times f_{\text{final},t-\tau}$$

This approximates "if we had sold 30-day variance τ days ago, what would the daily mark-to-market be?" It is NOT the same as trading put spreads — that's Phase 2's job. Phase 1 validates the **regime + risk management skeleton**, not the options execution.

---

## 2. Data Sources & Acquisition

### 2.1 Required Data

| Series | Source | Ticker / ID | Start Date | Frequency | Format |
|--------|--------|-------------|-----------|-----------|--------|
| S&P 500 close | Yahoo Finance | `^GSPC` | 2004-01-01 | Daily | OHLCV |
| VIX | FRED | `VIXCLS` | 2004-01-01 | Daily | Close |
| VIX3M | FRED | `VXVCLS` | 2007-12-04 | Daily | Close |
| VVIX | CBOE | Direct download | 2007-01-03 | Daily | Close |
| Risk-free rate | FRED | `DGS10` | 2004-01-01 | Daily | Yield |

**Total cost: $0.**

### 2.2 Data Gaps & Handling

| Issue | Solution |
|-------|----------|
| VIX3M starts 2007-12 (not 2004) | Backtest starts 2004 without TS feature; full feature set from 2008 onward. HMM trained on 4-feature vector pre-2008, 5-feature post-2008. |
| VVIX starts 2007-01 | Same approach as VIX3M. |
| Holidays / missing days | Forward-fill (max 3 days). If gap > 3 days, flag as data error. |
| Yahoo Finance reliability | Cache aggressively. Validate against FRED SPX data where available. |

### 2.3 Data Validation Checks

Before any computation, verify:

```
□ SPX: no missing trading days > 3 consecutive
□ SPX: all close prices > 0, no obvious outliers (daily return > 20%)
□ VIX: range [5, 90], no NaN on trading days
□ VIX3M: range [5, 90] where available
□ VVIX: range [50, 250] where available
□ All series aligned on same trading day calendar
□ Total trading days 2004-2025: approximately 5,300
```

---

## 3. Module Activation Map

| Module | Phase 1 Status | Notes |
|--------|---------------|-------|
| `src/data/fetcher.py` | **Active** | FREDFetcher + YFinanceFetcher only |
| `src/data/cache.py` | **Active** | Parquet cache for all raw data |
| `src/data/features.py` | **Active** | RV, VRP proxy, TS, ΔVol, z_VRP |
| `src/regime/hmm.py` | **Active** | Full implementation |
| `src/regime/features.py` | **Active** | Regime feature engineering |
| `src/regime/xgboost_clf.py` | **Active** | With CalibratedClassifierCV |
| `src/regime/calibration.py` | **Active** | Brier score, reliability diagram |
| `src/regime/detector.py` | **Active** | HMM + XGBoost orchestrator |
| `src/risk/vol_scaling.py` | **Active** | σ_target = 12% |
| `src/risk/kelly_ceiling.py` | **Active** | Adaptive α, regime-conditional μ |
| `src/risk/drawdown.py` | **Active** | DD monitoring + override |
| `src/risk/leverage.py` | **Active** | min-chain: min(f_vol, f_kelly, f_dd) |
| `src/backtest/proxy_engine.py` | **Active** | VRP proxy simulation engine |
| `src/backtest/metrics.py` | **Active** | Sharpe, MDD, CVaR, win rate |
| `src/pricing/black_scholes.py` | **Partial** | Only for delta approximation in analysis |
| `src/pricing/heston.py` | Inactive | Phase 2 |
| `src/pricing/fft_pricer.py` | Inactive | Phase 2 |
| `src/pricing/calibrator.py` | Inactive | Phase 2 |
| `src/strategy/` | Inactive | Phase 2 (no real spread construction) |
| `src/execution/` | Inactive | Phase 3 |
| `src/orchestrator/` | Inactive | Phase 3 |
| `alerts/` | Inactive | Phase 3 |

---

## 4. Task Breakdown

### Sprint 1: Data Foundation (3-4 days)

**Task 1.1 — Project Scaffolding**

Set up project structure, virtual environment, core dependencies.

```
Completion: `import src` runs without error, settings.yaml loads.
```

**Task 1.2 — DataFetcher ABC + Implementations**

Build `DataFetcher` abstraction, `FREDFetcher`, `YFinanceFetcher`.

```
Input:  start_date, end_date
Output: pd.DataFrame / pd.Series with DatetimeIndex

Test: fetch_vix('2020-01-01', '2020-12-31')
  → 253 trading days, no NaN, VIX range [12, 83]
Test: fetch_spx_ohlcv('2020-03-01', '2020-03-31')
  → 22 trading days, low on 2020-03-23 = 2191.86 (±1%)
```

**Task 1.3 — Cache Layer**

Parquet-based cache with source tagging.

```
Test: fetch same data twice → second call reads from cache (0 API calls)
Test: cache file exists at data/raw/fred/VIXCLS.parquet
```

**Task 1.4 — Feature Computation**

Compute all derived features from raw data.

```
Input:  SPX close, VIX, VIX3M, VVIX
Output: DataFrame with columns [rv_5, rv_21, rv_63, vix, vix3m, vvix,
        ts, dvol_5, vrp_proxy, z_vrp]

Test: RV(21) for 2020-03-16 (peak COVID vol)
  → approximately 70-90% annualized
Test: VRP proxy for 2020-03-16
  → strongly negative (RV >> IV at that moment, VIX spiked but RV spiked more)
Test: z_VRP for a random calm day (e.g., 2019-06-15)
  → positive (IV > RV in normal conditions)
```

### Sprint 2: Regime Detection (4-5 days)

**Task 2.1 — HMM Implementation**

3-state Gaussian HMM with centroid-anchored labeling.

```
Input:  Feature matrix (T × 5) — [RV_21, VIX, TS, VVIX, ΔVol]
Output: Filtered probabilities (T × 3), labels (T,)

Test: Fit on 2004-2020 data
  → 3 distinct states with non-degenerate covariances
  → Low-Vol centroid: RV < 12%, VIX < 15
  → High-Vol centroid: RV > 20%, VIX > 25
Test: 2008-09 to 2009-03 classified as High-Vol (>80% of days)
Test: 2017 classified as Low-Vol (>70% of days)
Test: Filtered (not smoothed) probabilities — verify by comparing
      filtered P(HV) on 2020-03-10 vs smoothed P(HV) on 2020-03-10.
      Smoothed should be higher (it "knows" the crash continues).
```

**Task 2.2 — Centroid Anchoring + Stability**

Implement centroid matching and label stability check.

```
Test: Refit HMM on 2004-2021 vs 2004-2020
  → Label agreement on overlap period >= 90%
  → State 0/1/2 mapping to LV/NV/HV is consistent
```

**Task 2.3 — XGBoost Classifier**

Train on HMM labels, calibrate probabilities.

```
Input:  Extended feature set (regime features + additional macro features)
Output: Calibrated probability vector [P_LV, P_NV, P_HV]

Test: Brier score on held-out period < 0.25
Test: Reliability diagram — predicted P(HV) = 0.3 should correspond
      to ~30% actual HV days (±10%)
```

**Task 2.4 — RegimeDetector Integration**

Orchestrate HMM + XGBoost into single interface.

```
Test: detector.predict(features_today)
  → Returns RegimePrediction with valid probabilities summing to 1.0
```

### Sprint 3: Risk Management (3-4 days)

**Task 3.1 — Vol Scaling**

```
Input:  20-day portfolio realized vol
Output: f_vol = clip(0.12 / σ_p, 0.3, 1.5)

Test: σ_p = 0.06 (calm) → f_vol = min(2.0, 1.5) = 1.5
Test: σ_p = 0.24 (volatile) → f_vol = max(0.5, 0.3) = 0.5
Test: σ_p = 0.12 (target) → f_vol = 1.0
```

**Task 3.2 — Kelly Ceiling with Adaptive α**

```
Input:  regime prediction, 60d rolling return/vol, regime age
Output: f_kelly = clip(μ_hat / σ_hat², 0.2, 2.0)

Test: Steady Low-Vol (age > 5d), rolling μ = 0.12, σ = 0.10
  → α = 0.6, μ_hat = 0.6*0.15 + 0.4*0.12 = 0.138
  → f_kelly = 0.138 / 0.01 = 13.8 → clipped to 2.0
Test: Fresh HV transition (age = 1d), rolling μ = 0.12, σ = 0.10
  → α = 0.9, μ_hat = 0.9*0.02 + 0.1*0.12 = 0.030
  → f_kelly = 0.030 / 0.01 = 3.0 → clipped to 2.0
  (Note: the prior dominance cuts μ_hat from 0.138 to 0.030)
```

**Task 3.3 — Drawdown Override**

```
Input:  Current drawdown from HWM
Output: f_dd ∈ {1.0, 0.5, 0.0}

Test: DD = 3% → f_dd = 1.0
Test: DD = 7% → f_dd = 0.5
Test: DD = 12% → f_dd = 0.0
```

**Task 3.4 — min-Chain Integration**

```
Input:  f_vol, f_kelly, f_dd
Output: f_final = min(f_vol, f_kelly, f_dd)

Test: f_vol=0.8, f_kelly=1.2, f_dd=0.5 → f_final = 0.5, binding = DD
Test: f_vol=0.5, f_kelly=1.5, f_dd=1.0 → f_final = 0.5, binding = vol
Test: f_vol=1.5, f_kelly=0.3, f_dd=1.0 → f_final = 0.3, binding = kelly
```

### Sprint 4: Backtest Engine + Validation (5-6 days)

**Task 4.1 — VRP Proxy Backtest Engine**

Core simulation engine. Iterates day-by-day, point-in-time.

```
Input:  Feature history, regime predictions, risk parameters
Output: Daily P&L series, position sizing history, regime history

Test: Run on 2008-2009
  → Regime transitions to HV in ~Sep 2008
  → f_final drops toward 0 during peak crisis
  → Proxy P&L shows drawdown but not catastrophic (regime helped)
```

**Task 4.2 — Naive Baseline**

Same backtest but with regime detection disabled (constant f=1.0, no Kelly prior shift, no DD override that depends on regime).

```
Test: Naive 2008-2009 drawdown >> Regime-conditioned 2008-2009 drawdown
```

**Task 4.3 — Performance Metrics**

```
Sharpe ratio (annualized)
Maximum drawdown
CVaR(95%) monthly
Worst single month
Calmar ratio (Sharpe / MDD)
Win rate (% of positive months)
Profit factor (gross profit / gross loss)
```

**Task 4.4 — Comparative Analysis**

Regime-conditioned vs Naive across all metrics. Statistical significance test.

```
Test: Welch's t-test on monthly returns (regime vs naive)
  → p-value < 0.10 for the difference to be meaningful
```

**Task 4.5 — Stress Period Analysis**

Detailed analysis of specific crisis periods:

```
| Period | Dates | What happened | Expected behavior |
|--------|-------|---------------|-------------------|
| GFC | 2008-09 to 2009-03 | Market crash, VIX > 80 | HV regime, f → 0 |
| Flash Crash | 2010-05-06 | Single-day spike | Brief HV, quick recovery |
| Taper Tantrum | 2013-06 | Bond market sell-off | NV → brief HV |
| Volmageddon | 2018-02-05 | VIX spike, XIV blow-up | HV, f → 0 |
| COVID crash | 2020-03 | Pandemic panic | Extended HV, f → 0 |
| 2022 rate hikes | 2022-01 to 2022-10 | Sustained vol increase | NV → HV cycling |
```

**Task 4.6 — Overfitting Defense**

CPCV + PBO + parameter sensitivity.

```
CPCV: N=5, k=2 → 10 splits, 5-day embargo
  → Mean Sharpe across splits within ±30% of full-sample Sharpe
PBO: < 5%
Parameter sensitivity: ±20% on σ_target, Kelly α, DD thresholds
  → Sharpe variation < ±30%
```

**Task 4.7 — GO / NO-GO Report**

Compile all results into a single acceptance document.

---

## 5. VRP Proxy Backtest Methodology

### 5.1 Simulation Logic

```python
for t in trading_days:
    # 1. Compute features (point-in-time)
    features_t = compute_features(data[:t])  # no future data

    # 2. Regime detection (point-in-time)
    if t is HMM refit day (monthly):
        hmm.fit(features[:t])  # expanding window
    if t is XGBoost retrain day (weekly):
        xgb.retrain(features[:t], hmm.labels[:t])
    regime_t = xgb.predict(features_t)

    # 3. VRP proxy signal
    vrp_t = (VIX[t]² / 252) - (RV_21[t]² / 252)
    z_vrp_t = (vrp_t - mean(vrp[t-252:t])) / std(vrp[t-252:t])

    # 4. Risk management
    f_vol = vol_scaling(portfolio_vol_20d[t])
    f_kelly = kelly_ceiling(regime_t, rolling_return_60d, rolling_vol_60d, regime_age)
    f_dd = dd_override(current_dd[t])
    f_final = min(f_vol, f_kelly, f_dd)

    # 5. Proxy P&L (daily increment)
    daily_vrp_return = (VIX[t-1]² - RV_1d[t]² * 252) / 252 / VIX[t-1]²
    pnl[t] = daily_vrp_return * f_final

    # 6. Update portfolio state
    portfolio_value[t] = portfolio_value[t-1] * (1 + pnl[t])
    current_dd[t] = 1 - portfolio_value[t] / max(portfolio_value[:t])
```

### 5.2 VRP Proxy P&L Explanation

The proxy simulates selling variance at implied levels and realizing at actual levels:

- **Positive VRP day:** VIX² > RV² → the "insurance" we sold was overpriced → profit
- **Negative VRP day:** VIX² < RV² → realized vol exceeded implied → loss

This is mathematically equivalent to a variance swap, which is the purest expression of VRP. Actual put spreads (Phase 2) introduce additional factors like skew, gamma, and discrete strikes, but the core P&L driver is the same variance premium.

### 5.3 Known Proxy Limitations

| Limitation | Impact | Phase 2 Resolution |
|-----------|--------|-------------------|
| VIX is forward-looking, RV is backward-looking | Timing mismatch in vol spikes | Use actual option chain IV and subsequent RV |
| No strike-specific premium | Overstates premium available at 10-delta | Phase 2 uses real strike quotes |
| No transaction costs | Overstates returns | Phase 2 applies $0.65/contract + slippage |
| No gamma/theta dynamics | Missing convexity effects | Phase 2 tracks actual spread P&L |
| Continuous position assumption | Real strategy is weekly entry | Phase 2 simulates weekly discrete entries |

**Critical:** Phase 1 results will overstate actual performance. The question is not "how much does it make?" but "does regime conditioning help?" If the regime-vs-naive difference is robust, Phase 2 will quantify the real numbers.

---

## 6. Regime Detection Validation

### 6.1 HMM Validation

| Check | Criterion | Method |
|-------|-----------|--------|
| State separation | 3 distinct vol regimes | Inspect centroids: LV, NV, HV should have non-overlapping (RV, VIX) ranges |
| Label interpretability | States match known market periods | 2008-09 = HV, 2017 = LV, 2015 = NV |
| Expanding window stability | Labels don't flip dramatically | Refit every 6 months, check overlap agreement ≥ 90% |
| Filtering vs smoothing | No future information leakage | Compare filtered P(HV) on 2020-03-10 vs smoothed — they must differ |
| Multi-init convergence | Best of 10 seeds is reproducible | Run twice with same seed → identical labels |

### 6.2 XGBoost Validation

| Check | Criterion |
|-------|-----------|
| Brier score | < 0.25 on out-of-sample period |
| Reliability diagram | Predicted probabilities track actual frequencies (±10%) |
| Feature importance | VIX, RV dominate (sanity check — these should matter most) |
| No leakage | Features use only data available at time t |
| Retrain stability | Weekly retraining produces consistent predictions (not flipping) |

### 6.3 Regime Value Test

The core question: does regime detection add value?

**Test 1 — Sharpe comparison:**
- Regime-conditioned Sharpe vs Naive Sharpe
- Difference must be > 0.1

**Test 2 — Drawdown comparison:**
- Regime-conditioned MDD vs Naive MDD
- Regime MDD must be meaningfully lower (at least 5pp reduction)

**Test 3 — Crisis-period attribution:**
- For each crisis period, compute P&L under regime vs naive
- Regime should show less loss in every crisis (not just on average)

**Test 4 — Transition timing:**
- Plot P(HV) on a timeline alongside VIX
- P(HV) should rise BEFORE or DURING the VIX spike, not AFTER
- If regime detection is always late, it adds no value

---

## 7. Risk Management Validation

### 7.1 Vol Scaling Validation

```
□ f_vol is always within [0.3, 1.5]
□ f_vol = 1.0 when σ_p ≈ σ_target (12%)
□ f_vol decreases when vol rises (inverse relationship)
□ f_vol is not forward-looking (uses only trailing 20d vol)
```

### 7.2 Kelly Ceiling Validation

```
□ f_kelly is always within [0.2, 2.0]
□ Adaptive α correctly switches on regime transitions
□ In HV regime: μ_hat is dominated by prior (2%), pulling f_kelly down
□ In LV regime: μ_hat blends prior (15%) with rolling, f_kelly is higher
□ Kelly never exceeds 2.0× regardless of inputs
```

### 7.3 min-Chain Validation

```
□ f_final = min(f_vol, f_kelly, f_dd) — NEVER a product
□ Binding constraint varies by market condition:
    - Calm markets: Kelly or Vol is binding (DD = 1.0, not binding)
    - Volatile markets: Vol is binding (low σ_target / high σ_p)
    - Drawdown: DD overrides everything when DD > 5%
□ When DD hits 10%, f_final = 0 (full exit)
□ Log which constraint is binding at each timestep
```

### 7.4 Kill Switch Validation

```
□ DD ≥ 10% → f_final = 0 → simulated full exit
□ After DD recovery below 5%, system re-enters (not permanent stop)
□ Count number of kill events in backtest (should be rare: 0-5 in 20 years)
```

---

## 8. GO / NO-GO Criteria

### 8.1 Primary Metrics (ALL must pass)

| # | Metric | GO | NO-GO | Rationale |
|---|--------|-----|-------|-----------|
| 1 | Regime-conditioned Sharpe | > 0.4 | ≤ 0.4 | Minimum viable risk-adjusted return |
| 2 | Maximum drawdown | < 30% | ≥ 30% | Capital preservation |
| 3 | Regime vs Naive Sharpe diff | > 0.1 | ≤ 0.1 | Regime detection must add value |
| 4 | CVaR(95%) monthly | > -8% | ≤ -8% | Left tail risk bounded |
| 5 | Worst single month | > -15% | ≤ -15% | No catastrophic single month |
| 6 | Positive VRP months | > 70% | ≤ 70% | Premium is persistent |

### 8.2 Crisis Stress Tests (ALL must pass)

| # | Period | Regime-conditioned MDD | NO-GO if |
|---|--------|----------------------|----------|
| 7 | 2008 GFC | < 25% | ≥ 25% |
| 8 | 2020 COVID | < 20% | ≥ 20% |
| 9 | 2018 Volmageddon | < 15% | ≥ 15% |

### 8.3 Overfitting Checks (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 10 | CPCV mean Sharpe | > 0.3 | ≤ 0.3 |
| 11 | CPCV Sharpe std | < 0.2 | ≥ 0.2 |
| 12 | PBO | < 5% | ≥ 5% |
| 13 | Parameter sensitivity (±20%) | Sharpe within ±30% | Outside ±30% |

### 8.4 Regime Quality Checks (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 14 | Brier score | < 0.25 | ≥ 0.25 |
| 15 | HMM label stability (refit) | ≥ 90% agreement | < 90% |
| 16 | Regime transitions during crises | HV detected in all 3 crises | Missed any |

### 8.5 Verdict Logic

```
if ALL 16 checks pass:
    VERDICT = GO → Proceed to Phase 2
    Action: Subscribe to Polygon.io, begin options chain backtest

elif checks 1-6 pass but crisis/overfitting checks fail:
    VERDICT = CONDITIONAL
    Action: Investigate specific failures, consider parameter adjustment
    Do NOT proceed to Phase 2 until resolved

elif any of checks 1-6 fail:
    VERDICT = NO-GO
    Action: Strategy fundamentally doesn't work at proxy level.
    Options:
      a) Reconsider strategy design (different regime features, risk params)
      b) Abandon VRP approach
    Do NOT spend money on Polygon.io
```

---

## 9. Deliverables & Completion Checklist

### 9.1 Code Deliverables

```
□ src/data/fetcher.py        — DataFetcher ABC, FREDFetcher, YFinanceFetcher
□ src/data/cache.py           — Parquet cache with source tagging
□ src/data/features.py        — RV, VRP proxy, TS, ΔVol, z_VRP computation
□ src/regime/hmm.py           — RegimeHMM with filtered probs + centroid anchoring
□ src/regime/features.py      — Regime feature engineering
□ src/regime/xgboost_clf.py   — RegimeXGBoost with calibrated probabilities
□ src/regime/calibration.py   — Brier score, reliability diagram
□ src/regime/detector.py      — RegimeDetector orchestrator
□ src/risk/vol_scaling.py     — Vol targeting
□ src/risk/kelly_ceiling.py   — Adaptive Kelly with regime-conditional prior
□ src/risk/drawdown.py        — DD monitoring + override
□ src/risk/leverage.py        — min-chain: min(f_vol, f_kelly, f_dd)
□ src/backtest/proxy_engine.py — VRP proxy simulation
□ src/backtest/metrics.py     — Sharpe, MDD, CVaR, Calmar, win rate, PF
□ src/backtest/cpcv.py        — CPCV + PBO
□ config/settings.yaml        — All Phase 1 parameters
□ scripts/run_phase1.py       — Phase 1 backtest entry point
```

### 9.2 Analysis Deliverables

```
□ notebooks/01_data_exploration.ipynb
    — Data quality, VRP distribution, VIX/RV relationship
    — Confirm VRP is positive >70% of months

□ notebooks/02_regime_analysis.ipynb
    — HMM state visualization (timeline with regime colors)
    — Centroid scatter plot (RV vs VIX, colored by state)
    — Brier score + reliability diagram
    — Filtered vs smoothed probability comparison

□ notebooks/03_backtest_results.ipynb
    — Equity curves: regime-conditioned vs naive vs buy-and-hold SPX
    — Drawdown chart
    — Monthly return heatmap
    — Crisis period deep-dives
    — Risk management binding constraint breakdown
    — CPCV results, PBO
    — GO/NO-GO verdict table
```

### 9.3 Document Deliverables

```
□ Phase 1 verdict document (GO / CONDITIONAL / NO-GO)
    — All 16 checks with actual values
    — If GO: summary of key metrics, readiness for Phase 2
    — If NO-GO: root cause analysis, recommended next steps
```

### 9.4 Estimated Timeline

| Sprint | Tasks | Duration |
|--------|-------|----------|
| Sprint 1 | Data foundation (fetcher, cache, features) | 3-4 days |
| Sprint 2 | Regime detection (HMM, XGBoost, detector) | 4-5 days |
| Sprint 3 | Risk management (vol, Kelly, DD, min-chain) | 3-4 days |
| Sprint 4 | Backtest engine + validation + verdict | 5-6 days |
| **Total** | | **15-19 days** |

### 9.5 Dependencies

```
Sprint 1 → Sprint 2 (regime needs features)
Sprint 1 → Sprint 3 (risk needs portfolio vol from features)
Sprint 2 + Sprint 3 → Sprint 4 (backtest needs regime + risk)
```

Sprint 2 and Sprint 3 can be developed in parallel after Sprint 1 completes.

```
Sprint 1 ──→ Sprint 2 ──┐
              │          ├──→ Sprint 4
              └→ Sprint 3┘
```
