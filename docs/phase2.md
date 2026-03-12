# Phase 2 — Options Chain Backtest

**Goal: Validate actual put credit spread performance using real options data.**

> Phase 2 activates only after Phase 1 GO verdict.
> Adds Polygon.io options chain data ($29/mo) and full Heston + FFT pricing layer.
> Simulates actual weekly 10-delta put credit spread entries with real strikes, real premiums, real bid-ask spreads.
> The question Phase 2 answers: "Does this strategy make money after transaction costs with real options?"
> If YES → Phase 3 (paper trading). If NO → revisit strategy parameters or stop.

---

## Table of Contents

1. [Phase Scope](#1-phase-scope)
2. [Prerequisites](#2-prerequisites)
3. [Data Sources & Acquisition](#3-data-sources--acquisition)
4. [Module Activation Map](#4-module-activation-map)
5. [Task Breakdown](#5-task-breakdown)
6. [Options Chain Backtest Methodology](#6-options-chain-backtest-methodology)
7. [Heston Calibration Validation](#7-heston-calibration-validation)
8. [Strategy Validation](#8-strategy-validation)
9. [Phase 1 vs Phase 2 Correlation](#9-phase-1-vs-phase-2-correlation)
10. [GO / NO-GO Criteria](#10-go--no-go-criteria)
11. [Deliverables & Completion Checklist](#11-deliverables--completion-checklist)

---

## 1. Phase Scope

### 1.1 What Phase 2 Does

- Fetches historical SPX options chain snapshots from Polygon.io
- Implements full Heston stochastic vol model + Carr-Madan FFT pricing
- Builds daily vol surface calibration pipeline with Feller constraint and 3-stage fallback
- Constructs actual 10-delta put credit spreads with real market strikes and premiums
- Simulates weekly entry, daily monitoring, and rule-based exits
- Applies full risk management stack on real spread P&L
- Applies realistic transaction costs (commissions + slippage model)
- Runs stress slippage test (50% bid-ask for High-Vol exits)
- Compares Phase 2 results against Phase 1 proxy (correlation check)
- Produces GO / NO-GO verdict

### 1.2 What Phase 2 Does NOT Do

| Not in Phase 2 | Why | When |
|----------------|-----|------|
| IBKR connection | No live execution | Phase 3 |
| Real-time data feed | Historical EOD snapshots only | Phase 3 |
| Orchestration / scheduler | Batch backtest | Phase 3 |
| Alerts / daily report | No live system | Phase 3 |

### 1.3 Key Difference from Phase 1

| Aspect | Phase 1 | Phase 2 |
|--------|---------|---------|
| Data | Free (FRED, Yahoo) | + Polygon.io ($29/mo) |
| VRP measurement | VIX proxy | Actual option IV at specific strikes |
| Pricing | BS closed-form | Heston + Carr-Madan FFT |
| Position | Hypothetical variance swap | Actual 10-delta put credit spread |
| Entry | Continuous daily exposure | Weekly discrete entries (Tuesday) |
| P&L | Proxy daily VRP return | Exact: premium - payoff at expiry |
| Costs | None | $0.65/contract + slippage model |
| Strike selection | N/A | Real: nearest tradeable 10-delta |
| Exit rules | N/A (continuous) | 75% profit, 2x stop, DTE <= 7, regime |

---

## 2. Prerequisites

### 2.1 Phase 1 Must Be Complete

```
[] Phase 1 verdict = GO (all 16 checks passed)
[] Regime detection validated (Brier < 0.25, stability >= 90%)
[] Risk management validated (min-chain working correctly)
[] All Phase 1 code committed and tested
```

### 2.2 Carried Forward from Phase 1

Reused without modification:
- `src/data/fetcher.py` — FREDFetcher, YFinanceFetcher
- `src/data/cache.py` — Extended with Polygon source tag
- `src/data/features.py` — Same feature computation
- `src/regime/*` — Entire regime detection stack
- `src/risk/*` — Entire risk management stack
- `src/backtest/metrics.py` — Extended with new metrics
- `src/backtest/cpcv.py` — Reused for overfitting defense

### 2.3 Polygon.io Setup

```
[] Polygon.io Starter subscription active ($29/mo)
[] API key obtained and stored in .env
[] Verify SPX options data availability:
    -> Which date range is available?
    -> Are EOD snapshots complete (all strikes, all expiries)?
    -> Is bid/ask included or just last price?
[] If data starts later than expected (soccer Odds-API lesson):
    -> Document exact start date
    -> Adjust backtest period accordingly
    -> If < 2 years available, evaluate OptionsDX for extended history
```

**Data Availability Risk:** This is the Polygon equivalent of the Odds-API discovery in the soccer project. Verify data range BEFORE building the pipeline. If Polygon only has 1 year of SPX options, Phase 2 backtest may be too short for statistical significance.

---

## 3. Data Sources & Acquisition

### 3.1 Polygon.io Options Data

| Field | Description | Required |
|-------|-------------|----------|
| `strike_price` | Option strike | Yes |
| `expiration_date` | Option expiry | Yes |
| `contract_type` | 'put' or 'call' | Yes |
| `close_price` | Last trade price | Yes |
| `bid` | End-of-day bid | Yes (slippage) |
| `ask` | End-of-day ask | Yes (slippage) |
| `implied_volatility` | Market-implied vol | Yes (calibration) |
| `delta` | Option delta | Preferred (cross-check) |
| `gamma`, `theta`, `vega` | Other Greeks | Preferred |
| `volume` | Daily volume | Yes (liquidity filter) |
| `open_interest` | Open interest | Preferred |

### 3.2 PolygonFetcher

```python
class PolygonFetcher:
    def fetch_options_chain(self, underlying: str, trade_date: date,
                            min_dte: int = 7, max_dte: int = 60,
                            option_type: str = 'put') -> OptionsChain:
        """Fetches EOD options chain snapshot for a given date."""

    def fetch_date_range(self) -> tuple[date, date]:
        """Returns (earliest, latest) dates of available data.
        MUST be called before building backtest."""
```

### 3.3 Data Quality Checks

```
[] Bid <= Ask for all quotes
[] Bid > 0 for tradeable strikes
[] Implied vol > 0 and < 300%
[] Delta in [-1, 0] for puts
[] Volume > 0 for at least 50% of relevant strikes
[] No missing trading days in range
[] Cross-check: ATM IV ~ VIX/100 (within +/-2%)
```

---

## 4. Module Activation Map

| Module | Phase 1 | Phase 2 | Change |
|--------|---------|---------|--------|
| `src/data/fetcher.py` | Active | Active | + PolygonFetcher |
| `src/data/cache.py` | Active | Active | + polygon/ source tag |
| `src/data/features.py` | Active | Active | No change |
| `src/regime/*` | Active | Active | No change |
| `src/risk/*` | Active | Active | No change |
| `src/pricing/black_scholes.py` | Partial | Active | Full BS + IV solver |
| `src/pricing/heston.py` | Inactive | **Active** | New |
| `src/pricing/fft_pricer.py` | Inactive | **Active** | New |
| `src/pricing/calibrator.py` | Inactive | **Active** | New |
| `src/pricing/vol_surface.py` | Inactive | **Active** | New |
| `src/pricing/greeks.py` | Inactive | **Active** | New |
| `src/strategy/vrp_signal.py` | Inactive | **Active** | New |
| `src/strategy/entry.py` | Inactive | **Active** | New |
| `src/strategy/strike_selector.py` | Inactive | **Active** | New |
| `src/strategy/spread.py` | Inactive | **Active** | New |
| `src/strategy/position_manager.py` | Inactive | **Active** | New |
| `src/backtest/options_engine.py` | N/A | **Active** | New |
| `src/execution/` | Inactive | Inactive | Phase 3 |
| `src/orchestrator/` | Inactive | Inactive | Phase 3 |

---

## 5. Task Breakdown

### Sprint 5: Polygon.io Integration (3-4 days)

**Task 5.1 — PolygonFetcher Implementation**

```
Input:  underlying='SPX', trade_date, DTE range
Output: OptionsChain object with all put quotes

Test: fetch_options_chain('SPX', date(2024, 6, 15), min_dte=25, max_dte=50)
  -> Returns chain with 50+ put strikes across 2-3 expiry dates
  -> All quotes have bid > 0, ask > bid, IV > 0
Test: fetch_date_range()
  -> Returns actual (start, end) dates — document these
```

**Task 5.2 — Options Cache Layer**

```
Cache: data/raw/polygon/options/SPX/YYYY-MM-DD.parquet

Test: Fetch same date twice -> second call is cache hit
Test: Cache file ~50-200 KB per date
```

**Task 5.3 — Data Quality Pipeline**

```
Test: Inject bad data (negative bid, IV > 500%)
  -> Quality checker flags and logs warnings
  -> Bad quotes excluded from downstream
```

**Task 5.4 — Data Availability Audit**

```
[] Run fetch_date_range() and document exact coverage
[] Count trading days with complete chains
[] Identify gaps
[] Decision: sufficient for meaningful backtest?
    -> Minimum: 2 years (500+ trading days)
    -> Ideal: 4+ years (includes high-vol period)
    -> If insufficient: evaluate OptionsDX supplement
```

### Sprint 6: Heston + FFT Pricing (5-6 days)

**Task 6.1 — Heston Model**

```
Input:  Parameters (v0, kappa, theta, sigma_v, rho), evaluation point
Output: Characteristic function value (complex)

Test: Known params (v0=0.04, kappa=1.5, theta=0.04, sigma_v=0.3, rho=-0.7)
  -> ATM call price matches QuantLib within $0.01
Test: Feller check
  -> 2*1.5*0.04=0.12 > 0.09=0.3^2 -> True
  -> 2*1.5*0.02=0.06 < 0.09=0.3^2 -> False (reject)
```

**Task 6.2 — Carr-Madan FFT**

```
Input:  HestonModel, S, r, T, N=4096, alpha=1.5
Output: Array of (strike, price) pairs

Test: Set sigma_v=0, rho=0 (reduces to BS) -> all prices match BS within $0.01
Test: 100 strikes in single FFT call -> execution < 50ms
Test: Put-call parity holds within $0.02
```

**Task 6.3 — Heston Calibrator**

```
Input:  OptionsChain (market quotes)
Output: CalibrationResult (model + diagnostics)

Test: Calibrate on known date -> RMSE < avg bid-ask spread
Test: Fallback chain:
  -> Poison LM -> falls to DE-only, logs WARNING
  -> Poison DE -> falls to prev day params, logs WARNING
  -> Both fail -> falls to BS, logs CRITICAL
```

**Task 6.4 — Vol Surface**

```
Test: implied_vol(K=5000, T=0.1) -> reasonable IV (10-40%)
Test: IV monotonically decreasing in K for puts (skew present)
Test: delta() matches BS delta computed with surface IV
```

**Task 6.5 — Spread Greeks**

```
Test: Spread delta ~ short_delta - long_delta
  -> 10-delta short, 5-delta long: spread delta ~ -0.05
Test: Spread theta > 0 (time decay benefits seller)
Test: Spread vega < 0 (vol increase hurts seller)
```

### Sprint 7: Strategy Engine (4-5 days)

**Task 7.1 — VRP Signal (Chain-Based)**

```
Test: Chain-based VRP vs Phase 1 proxy correlation > 0.7
Test: Chain-based VRP typically smaller (proxy overstates)
```

**Task 7.2 — Strike Selector**

```
Input:  VolSurface, target_delta=-0.10, S, T, r
Output: K_1 rounded to nearest $5

Test: Selected strike has delta within [-0.12, -0.08]
Test: VIX=15, DTE=35, S=5500 -> K_1 ~ 5200-5250 (5-6% OTM)
Test: VIX=30, DTE=35, S=5500 -> K_1 ~ 4900-5000 (more OTM)
```

**Task 7.3 — Spread Construction**

```
Test: max_loss = W - premium
Test: premium > 0
Test: premium/W > 0.10
Test: breakeven = K_1 - premium
```

**Task 7.4 — Entry Decision**

```
Test: P_HV=0.1, z_VRP=0.5, ratio=0.12 -> Enter, full (1.0)
Test: P_HV=0.3, z_VRP=0.5, ratio=0.12 -> Enter, half (0.5)
Test: P_HV=0.6, z_VRP=0.5, ratio=0.12 -> Skip (regime)
Test: P_HV=0.1, z_VRP=-1.5, ratio=0.12 -> Skip (VRP)
Test: P_HV=0.1, z_VRP=0.5, ratio=0.06 -> Skip (premium)
```

**Task 7.5 — Position Manager**

```
Test: 80% profit -> Exit (profit_target)
Test: -250% loss -> Exit (stop_loss, urgent)
Test: DTE=5 -> Exit (dte)
Test: P_HV=0.85 -> Exit (regime_emergency, urgent)
Test: 50% profit, DTE=20, P_HV=0.1 -> Hold
```

### Sprint 8: Options Backtest + Validation (6-8 days)

**Task 8.1 — Options Chain Backtest Engine**

```python
class OptionsBacktestEngine:
    def run(self, start_date, end_date) -> BacktestResult:
        """Weekly loop:
        1. Fetch chain, calibrate Heston, detect regime
        2. Monitor open positions daily (exit triggers, M2M)
        3. Entry on Tuesday if no open position
        4. Risk sizing via min-chain
        5. Record all trades, P&L, Greeks, regime state"""
```

```
Test: 1 year run -> 20-40 trades, all valid strikes, no future leakage
Test: Spot-check 3 trade P&Ls against manual calculation
```

**Task 8.2 — Transaction Cost Model**

```
Per spread (entry + exit):
  Commission: 4 x $0.65 = $2.60
  Slippage (normal): 25% of bid-ask per leg
  Slippage (stress): 50% of bid-ask per leg (HV exits)

Test: Typical all-in cost ~ $25-30/spread
```

**Task 8.3 — Stress Slippage Backtest**

```
Normal: 25% bid-ask all entries and exits
Stress: 25% entries, 50% exits when regime=HV at exit

Test: Stress Sharpe > 0.3
Test: Stress MDD < 30%
```

**Task 8.4 — Performance Metrics**

Phase 1 metrics plus:
- Win rate, avg win/loss ratio, avg trade duration
- Avg premium/width, trades per year
- Commission drag, slippage drag (% of gross profit)
- Regime-conditional win rate

**Task 8.5 — Phase 1 vs Phase 2 Correlation**

```
Run both on same date range, compare monthly returns:
  -> Correlation > 0.7: Phase 1 was valid proxy
  -> Correlation 0.5-0.7: partially valid, trust Phase 2 numbers
  -> Correlation < 0.5: Phase 1 was misleading, investigate why
```

**Task 8.6 — Crisis Period Analysis**

For each crisis within data range:
```
[] Regime correctly detected HV?
[] Position sizing reduced?
[] Emergency exits triggered?
[] Bid-ask widening captured in slippage?
[] Trade-by-trade P&L during crisis
```

**Task 8.7 — Overfitting Defense**

```
CPCV: N=5, k=2, 5-day embargo
  -> Mean Sharpe within +/-30% of full sample
PBO: < 5%
Sensitivity: +/-20% on delta, width, profit target, stop loss
  -> Sharpe within +/-30%
```

**Task 8.8 — GO / NO-GO Report**

---

## 6. Options Chain Backtest Methodology

### 6.1 Simulation Logic

```python
for week in trading_weeks:
    entry_day = week.tuesday

    for day in week.trading_days:
        # 1. Data (point-in-time)
        chain = polygon.fetch_options_chain('SPX', day)
        features = compute_features(market_data[:day])

        # 2. Calibrate Heston (daily)
        cal_result = calibrator.calibrate(chain)
        vol_surface = VolSurface(cal_result, chain)

        # 3. Regime
        regime = detector.predict(features)

        # 4. Monitor open position
        if has_open_position:
            spread.update_greeks(vol_surface)
            spread.update_pnl(chain)
            exit_signal = position_manager.check_exit(spread, regime)
            if exit_signal.should_exit:
                close_trade(spread, chain, exit_signal)

        # 5. Entry (Tuesday only, no open position)
        if day == entry_day and not has_open_position:
            entry = entry_decision(regime, vrp_zscore, premium_ratio)
            if entry.enter:
                K1 = strike_selector.find_10delta(vol_surface)
                K2 = K1 - W
                spread = PutCreditSpread(K1, K2, chain, vol_surface)
                f_final = leverage_chain.compute(...)
                n = floor(account * f_final * entry.scale / max_loss)
                open_trade(spread, n, chain)

    # Expiry settlement if within week
    if has_open_position and spread.expiry <= week.friday:
        settle_at_expiry(spread, spx_close_on_expiry)
```

### 6.2 Mark-to-Market

```
spread_value = mid(K1_put) - mid(K2_put)
unrealized_pnl = (premium_received - spread_value) x n_contracts x 100
```

If a specific strike is missing in the daily chain, use vol surface to interpolate.

### 6.3 Trade Lifecycle

```
ENTRY
  -> Select K1 (10-delta), K2 = K1 - W
  -> Record: date, K1, K2, expiry, premium, n_contracts
  -> Deduct: slippage (25% bid-ask/leg) + commission ($0.65 x 4)

MONITORING (daily)
  -> Mark-to-market, update Greeks, check exit triggers

EXIT (one of four reasons)
  -> profit_target: close at mid - slippage
  -> stop_loss: close at mid - slippage (stress if HV)
  -> dte: close at mid - slippage
  -> regime_emergency: close at mid - stress slippage
  -> Deduct: slippage + commission

EXPIRY (if held)
  -> Cash settle: max(0, K1-SPX) - max(0, K2-SPX)
  -> No slippage (cash settlement)
```

---

## 7. Heston Calibration Validation

### 7.1 Daily Quality Checks

```
[] Feller: 2*kappa*theta > sigma_v^2
[] RMSE < avg bid-ask of calibration set
[] All params within bounds
[] Model prices positive and monotone in strike
[] Calibration time < 30 seconds per day
```

### 7.2 Stability

```
[] Day-to-day param changes smooth (|delta_kappa/kappa| < 50%)
[] Fallback event log:
    -> DE-only: < 5% of days
    -> Prev day: < 1% of days
    -> BS fallback: 0 days
```

### 7.3 Vol Surface Quality

```
[] IV positive everywhere
[] Put skew present: IV(OTM put) > IV(ATM) for all dates
[] No butterfly arbitrage (spot-check 10 dates)
[] ATM IV ~ VIX/100 (within +/-3%)
[] Surface smooth (no interpolation artifacts)
```

---

## 8. Strategy Validation

### 8.1 Trade-Level

```
[] 40-50 trades/year (weekly minus skips)
[] Win rate > 75%
[] Avg winner: 60-80% of premium
[] Avg loser: 150-250% of premium (asymmetric, expected)
[] Avg duration: 15-25 days
[] Held to expiry: < 10% of trades
```

### 8.2 Entry Analysis

```
[] Skip rate: 20-40% of weeks
[] LV weeks: < 10% skipped
[] HV weeks: > 80% skipped
[] Avg premium ratio at entry: 10-18%
[] Avg delta at entry: -0.08 to -0.12
```

### 8.3 Exit Analysis

```
[] Exit distribution:
    -> Profit target: 60-70%
    -> DTE: 15-25%
    -> Stop loss: 5-15%
    -> Regime emergency: < 5%
```

### 8.4 Risk Management

```
[] Binding constraint varies by environment
[] Kill events (f=0): 0-3 in entire backtest
[] Recovery after DD: < 3 months to new HWM
[] No single trade loss > 5% of account
```

---

## 9. Phase 1 vs Phase 2 Correlation

### 9.1 Methodology

Run both engines on same date range (Polygon coverage):
```
Phase 1: proxy_engine.run(start, end) -> monthly returns
Phase 2: options_engine.run(start, end) -> monthly returns
```

### 9.2 Expected Results

| Metric | Expected | Concern if |
|--------|----------|-----------|
| Monthly correlation | > 0.7 | < 0.5 |
| Sharpe difference | Phase 2 < Phase 1 | Phase 2 > Phase 1 |
| MDD difference | Within +/-5pp | Phase 2 >> Phase 1 |
| Regime direction | Same (both better in LV) | Opposite |
| DD timing | Same months | Uncorrelated |

### 9.3 If Correlation Is Low

Investigate systematically:
1. Remove costs -> does correlation improve? (cost model issue)
2. Daily vs weekly entry -> does weekly hurt? (discretization issue)
3. Check strike-specific effects (skew, gamma not in proxy)

Document findings regardless — valuable for proxy reliability assessment.

---

## 10. GO / NO-GO Criteria

### 10.1 Primary (ALL must pass)

| # | Metric | GO | NO-GO |
|---|--------|-----|-------|
| 1 | Post-cost Sharpe | > 0.5 | <= 0.5 |
| 2 | MDD | < 25% | >= 25% |
| 3 | Win rate | > 75% | <= 75% |
| 4 | Avg win / Avg loss | > 0.3 | <= 0.3 |
| 5 | CVaR(95%) monthly | > -6% | <= -6% |
| 6 | Worst month | > -12% | <= -12% |

### 10.2 Cost & Execution (ALL must pass)

| # | Metric | GO | NO-GO |
|---|--------|-----|-------|
| 7 | Stress slippage Sharpe | > 0.3 | <= 0.3 |
| 8 | Commission drag | < 15% of gross | >= 15% |
| 9 | Slippage drag | < 20% of gross | >= 20% |

### 10.3 Phase Correlation

| # | Metric | GO | NO-GO |
|---|--------|-----|-------|
| 10 | Phase 1 vs 2 correlation | > 0.5 | <= 0.5 |

### 10.4 Calibration Quality

| # | Metric | GO | NO-GO |
|---|--------|-----|-------|
| 11 | Heston success rate | > 95% of days | <= 95% |
| 12 | BS fallback days | 0 | > 0 |
| 13 | Avg calibration RMSE | < mean bid-ask | >= mean bid-ask |

### 10.5 Overfitting (ALL must pass)

| # | Metric | GO | NO-GO |
|---|--------|-----|-------|
| 14 | CPCV mean Sharpe | > 0.3 | <= 0.3 |
| 15 | PBO | < 5% | >= 5% |
| 16 | Param sensitivity | Within +/-30% | Outside |

### 10.6 Verdict Logic

```
if ALL 16 pass:
    VERDICT = GO -> Phase 3 (Paper Trading)
    Action: Set up IBKR paper account, build execution layer

elif 1-6 pass but cost/calibration/overfitting fail:
    VERDICT = CONDITIONAL
    Action: Fix specific issue (wider spreads, SPY instead of SPX, etc.)

elif any of 1-6 fail:
    VERDICT = NO-GO
    Action:
      a) Compare against Phase 1 — did Phase 2 degrade?
      b) If yes, issue is execution (costs, strikes), not strategy
      c) Try: wider spreads, less frequent entry, different delta
      d) If nothing helps -> strategy doesn't survive implementation
    Do NOT proceed to Phase 3.
```

---

## 11. Deliverables & Completion Checklist

### 11.1 Code

```
[] src/data/fetcher.py            — + PolygonFetcher
[] src/pricing/black_scholes.py   — Full BS with IV solver
[] src/pricing/heston.py          — Heston model + char function
[] src/pricing/fft_pricer.py      — Carr-Madan FFT engine
[] src/pricing/calibrator.py      — DE -> LM with Feller + fallback
[] src/pricing/vol_surface.py     — Interpolated vol surface
[] src/pricing/greeks.py          — Spread-level Greeks
[] src/strategy/vrp_signal.py     — Chain-based VRP
[] src/strategy/entry.py          — 3-condition entry gate
[] src/strategy/strike_selector.py — 10-delta Newton-Raphson
[] src/strategy/spread.py         — PutCreditSpread
[] src/strategy/position_manager.py — Exit triggers
[] src/backtest/options_engine.py — Full options backtest
[] src/backtest/metrics.py        — + trade-level metrics
[] config/settings.yaml           — + Phase 2 params
[] scripts/run_phase2.py          — Entry point
```

### 11.2 Analysis

```
[] notebooks/03b_heston_validation.ipynb
    — Calibration quality, param stability, surface vis, fallback log

[] notebooks/04_options_backtest.ipynb
    — Equity curve, trade analysis, entry/exit breakdown
    — Regime-conditional performance, risk constraint analysis
    — Phase 1 vs 2 correlation, stress slippage comparison
    — Crisis analysis, CPCV + PBO, GO/NO-GO table
```

### 11.3 Documents

```
[] Phase 2 verdict (GO / CONDITIONAL / NO-GO)
    — All 16 checks with values
    — Phase 1 vs 2 correlation
    — Cost breakdown
    — Readiness for Phase 3 (or root cause if NO-GO)
```

### 11.4 Timeline

| Sprint | Tasks | Duration |
|--------|-------|----------|
| Sprint 5 | Polygon integration + data audit | 3-4 days |
| Sprint 6 | Heston + FFT pricing | 5-6 days |
| Sprint 7 | Strategy engine | 4-5 days |
| Sprint 8 | Backtest + validation + verdict | 6-8 days |
| **Total** | | **18-23 days** |

### 11.5 Dependencies

```
Phase 1 --> Sprint 5 --> Sprint 6 --+
                          |          +--> Sprint 8
                          +-> Sprint 7 -+
```

Sprint 7 depends on Sprint 6 (strike selector needs vol surface), but entry logic and position manager can start while pricing is being built.
