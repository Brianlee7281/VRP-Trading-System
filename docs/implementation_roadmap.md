# Implementation Roadmap

**VRP Production System — Sprint-by-Sprint Task Breakdown**

> Consolidates all tasks from `phase1.md` through `phase4.md` into a single execution plan.
> Each task has: inputs, outputs, dependencies, concrete test cases with expected values, and completion criteria.
> Build order follows `implementation_blueprint.md` dependency map: bottom-up, most-depended-on first.
> Claude Code decomposition docs are created just-in-time before each sprint, not in advance.

---

## Overview

```
Phase 1: VIX Proxy Backtest ──── Sprints 1-4 ──── 15-19 days ──── Cost: $0
Phase 2: Options Chain Backtest ─ Sprints 5-8 ──── 18-23 days ──── Cost: $29/mo
Phase 3: Paper Trading ────────── Sprints 9-11 ─── 10-13 days dev + 20 days ops
Phase 4: Live Trading ─────────── No dev sprints ── Operational (ongoing)

Total development: Sprints 1-11 ── 43-55 days
Total before live money: add 20+ days paper trading
```

### Sprint Dependency Graph

```
Sprint 1 (Data) ──→ Sprint 2 (Regime) ──┐
                      │                   ├──→ Sprint 4 (Backtest P1)
                      └→ Sprint 3 (Risk) ┘
                                │
                    Phase 1 GO ─┘
                                │
Sprint 5 (Polygon) ──→ Sprint 6 (Pricing) ──┐
                          │                   ├──→ Sprint 8 (Backtest P2)
                          └→ Sprint 7 (Strategy)┘
                                │
                    Phase 2 GO ─┘
                                │
Sprint 9 (IBKR) ──→ Sprint 10 (Orchestration) ──→ Sprint 11 (Alerts)
                                │
                    Sprint 12: Paper Trading (4+ weeks operation)
                                │
                    Phase 3 GO ─┘
                                │
                    Phase 4: Live (Stage 1 → 2 → 3)
```

---

## Phase 1: VIX Proxy Backtest

### Sprint 1 — Data Foundation (3-4 days)

**S1-T1: Project Scaffolding**

| Field | Value |
|-------|-------|
| Depends on | Nothing |
| Files | `pyproject.toml`, `requirements.txt`, `config/settings.yaml`, `.env.example`, `.gitignore`, `src/__init__.py`, all `__init__.py` files |
| Completion | `import src` succeeds, `yaml.safe_load(settings.yaml)` returns valid dict |
| Git | `git init`, first commit: "S1-T1: project scaffolding" |

**S1-T2: Data Models**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/data/models.py` |
| Creates | `OptionQuote`, `OptionsChain`, `MarketData`, `FeatureVector` dataclasses |
| Test | Instantiate each dataclass with sample data, verify field access |
| Git | "S1-T2: data models" |

**S1-T3: Cache Layer**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/data/cache.py` |
| Test 1 | `cache.write('fred', 'VIXCLS', df)` → file exists at `data/raw/fred/VIXCLS.parquet` |
| Test 2 | `cache.read('fred', 'VIXCLS')` → returns identical DataFrame |
| Test 3 | `cache.exists('fred', 'VIXCLS')` → True. `cache.exists('fred', 'MISSING')` → False |
| Test 4 | `cache.age_days('fred', 'VIXCLS')` → 0 (just written) |
| Git | "S1-T3: parquet cache layer" |

**S1-T4: FREDFetcher + YFinanceFetcher**

| Field | Value |
|-------|-------|
| Depends on | S1-T2, S1-T3 |
| Files | `src/data/fetcher.py` |
| Test 1 | `fred.fetch_vix('2020-01-01', '2020-12-31')` → 253 values, range [12, 83], no NaN |
| Test 2 | `fred.fetch_vix3m('2020-01-01', '2020-12-31')` → values exist from 2020 onward |
| Test 3 | `yf.fetch_spx_ohlcv('2020-03-01', '2020-03-31')` → 22 days, low on 2020-03-23 ≈ 2191.86 (±1%) |
| Test 4 | Second fetch → cache hit (0 API calls) |
| Test 5 | `fred.fetch_risk_free_rate(...)` → positive values, range [0, 6] |
| Note | VVIX may require CBOE direct download — implement as `CBOEFetcher` if FRED doesn't carry it |
| Git | "S1-T4: FRED and YFinance data fetchers" |

**S1-T5: Feature Computation**

| Field | Value |
|-------|-------|
| Depends on | S1-T4 |
| Files | `src/data/features.py` |
| Test 1 | `compute_realized_vol(spx_close, 21)` for 2020-03-16 → approximately 70-90% annualized |
| Test 2 | `compute_vrp_proxy(vix, rv_21)` for a calm day (2019-06-15) → positive |
| Test 3 | `compute_vrp_proxy(vix, rv_21)` for 2020-03-16 → strongly negative |
| Test 4 | `compute_term_structure(vix, vix3m)` → positive in contango, negative in backwardation |
| Test 5 | `compute_all_features(data)` → DataFrame with columns [rv_5, rv_21, rv_63, vix, vix3m, vvix, ts, dvol_5, vrp_proxy, z_vrp], no NaN in valid range |
| Test 6 | All features use only data up to time t (no future leakage — verify by checking that feature[t] only depends on data[:t+1]) |
| Git | "S1-T5: feature computation" |

---

### Sprint 2 — Regime Detection (4-5 days)

**S2-T1: Regime Feature Engineering**

| Field | Value |
|-------|-------|
| Depends on | S1-T5 |
| Files | `src/regime/features.py` |
| Creates | Function to extract 5-feature vector [RV_21, VIX, TS, VVIX, ΔVol] from full feature DataFrame |
| Test | Output shape (T, 5), no NaN, all features in reasonable ranges |
| Git | "S2-T1: regime feature engineering" |

**S2-T2: RegimeHMM**

| Field | Value |
|-------|-------|
| Depends on | S2-T1 |
| Files | `src/regime/hmm.py` |
| Test 1 | Fit on 2004-2020: 3 states with distinct centroids (LV: RV<12%/VIX<15, HV: RV>20%/VIX>25) |
| Test 2 | 2008-09 to 2009-03: >80% of days labeled High-Vol |
| Test 3 | 2017: >70% of days labeled Low-Vol |
| Test 4 | `get_filtered_probs()` returns shape (T, 3), sums to 1.0 per row |
| Test 5 | Filtered P(HV) on 2020-03-10 ≠ smoothed P(HV) on 2020-03-10 (verify filtering is correct) |
| Test 6 | n_init=10: re-run with same seed → identical labels |
| Implementation note | Use `_do_forward_pass()` for filtered probs, NOT `predict_proba()` |
| Git | "S2-T2: 3-state HMM with centroid anchoring" |

**S2-T3: Centroid Anchoring + Stability**

| Field | Value |
|-------|-------|
| Depends on | S2-T2 |
| Files | Same `src/regime/hmm.py` (methods within RegimeHMM) |
| Test 1 | Refit on 2004-2021 vs 2004-2020: label agreement ≥ 90% |
| Test 2 | State mapping is consistent (state 0/1/2 → same LV/NV/HV assignment) |
| Test 3 | If agreement < 90%: method returns False, old labels preserved |
| Git | "S2-T3: centroid anchoring and stability check" |

**S2-T4: RegimeXGBoost**

| Field | Value |
|-------|-------|
| Depends on | S2-T2 |
| Files | `src/regime/xgboost_clf.py`, `src/regime/calibration.py` |
| Test 1 | Train on 2004-2018 labels, test on 2019-2020: Brier score < 0.25 |
| Test 2 | Calibrated probabilities: predicted P(HV) = 0.3 → actual ~30% HV days (±10%) |
| Test 3 | `predict(features_today)` → array of 3 probabilities summing to 1.0 |
| Test 4 | Feature importance: VIX and RV in top 3 |
| Git | "S2-T4: calibrated XGBoost regime classifier" |

**S2-T5: RegimeDetector**

| Field | Value |
|-------|-------|
| Depends on | S2-T2, S2-T3, S2-T4 |
| Files | `src/regime/detector.py` |
| Test 1 | `detector.predict(features_today)` → RegimePrediction with valid probs, regime label, confidence |
| Test 2 | `detector.refit_hmm(features)` → returns True if stable, False if not |
| Test 3 | `detector.retrain_xgboost(features, labels)` → returns Brier score |
| Test 4 | Save/load roundtrip: save models, load, predict → identical results |
| Git | "S2-T5: regime detector integration" |

---

### Sprint 3 — Risk Management (3-4 days)

**S3-T1: Vol Scaling**

| Field | Value |
|-------|-------|
| Depends on | S1-T5 |
| Files | `src/risk/vol_scaling.py` |
| Test 1 | σ_p = 0.06, target = 0.12 → f_vol = 1.5 (hits max clip) |
| Test 2 | σ_p = 0.24, target = 0.12 → f_vol = 0.5 |
| Test 3 | σ_p = 0.12, target = 0.12 → f_vol = 1.0 |
| Test 4 | σ_p = 0.40, target = 0.12 → f_vol = 0.3 (hits min clip) |
| Git | "S3-T1: volatility scaling" |

**S3-T2: Kelly Ceiling**

| Field | Value |
|-------|-------|
| Depends on | S2-T5 (needs regime prediction) |
| Files | `src/risk/kelly_ceiling.py` |
| Test 1 | Steady LV (age>5d), rolling_μ=0.12, rolling_σ=0.10 → α=0.6, μ_hat=0.138, f_kelly=2.0 (clipped) |
| Test 2 | Fresh HV transition (age=1d), rolling_μ=0.12, rolling_σ=0.10 → α=0.9, μ_hat=0.030, f_kelly=2.0 (clipped, but μ dramatically lower) |
| Test 3 | Fresh NV transition (age=2d) → α=0.75 |
| Test 4 | Negative rolling_μ → f_kelly = 0.2 (min clip) |
| Git | "S3-T2: adaptive Kelly ceiling" |

**S3-T3: Drawdown Monitor**

| Field | Value |
|-------|-------|
| Depends on | Nothing (pure math) |
| Files | `src/risk/drawdown.py` |
| Test 1 | DD = 3% → f_dd = 1.0 |
| Test 2 | DD = 7% → f_dd = 0.5 |
| Test 3 | DD = 12% → f_dd = 0.0 |
| Test 4 | Equity series [100, 105, 103, 95, 98] → DD = (105-95)/105 = 9.52% → f_dd = 0.5 |
| Test 5 | HWM tracking: new high updates HWM, DD resets |
| Git | "S3-T3: drawdown monitor and override" |

**S3-T4: min-Chain (LeverageChain)**

| Field | Value |
|-------|-------|
| Depends on | S3-T1, S3-T2, S3-T3 |
| Files | `src/risk/leverage.py` |
| Test 1 | f_vol=0.8, f_kelly=1.2, f_dd=0.5 → f_final=0.5, binding=DD |
| Test 2 | f_vol=0.5, f_kelly=1.5, f_dd=1.0 → f_final=0.5, binding=vol |
| Test 3 | f_vol=1.5, f_kelly=0.3, f_dd=1.0 → f_final=0.3, binding=kelly |
| Test 4 | f_vol=0.8, f_kelly=1.2, f_dd=0.0 → f_final=0.0, binding=DD (kill) |
| Test 5 | Verify: f_final = min(f_vol, f_kelly, f_dd), NEVER a product |
| Git | "S3-T4: min-chain leverage combination" |

---

### Sprint 4 — Phase 1 Backtest + Verdict (5-6 days)

**S4-T1: Backtest Metrics**

| Field | Value |
|-------|-------|
| Depends on | Nothing (pure math) |
| Files | `src/backtest/metrics.py` |
| Test 1 | Sharpe of constant 1% monthly return → √12 * 0.01/0 = handle zero-vol case |
| Test 2 | Known series: monthly returns [2%, -1%, 3%, -2%, 1%, 4%] → verify Sharpe matches manual calc |
| Test 3 | MDD of [100, 110, 95, 105, 90, 100] → (110-90)/110 = 18.18% |
| Test 4 | CVaR(95%) of known distribution → verify against scipy |
| Test 5 | Win rate, Calmar, profit factor with known trades |
| Git | "S4-T1: backtest performance metrics" |

**S4-T2: VRP Proxy Backtest Engine**

| Field | Value |
|-------|-------|
| Depends on | S1-T5, S2-T5, S3-T4, S4-T1 |
| Files | `src/backtest/proxy_engine.py` |
| Test 1 | Run 2008-2009: regime transitions to HV ~Sep 2008, f_final drops to near 0 |
| Test 2 | Run full period: positive cumulative return |
| Test 3 | No future data leakage: feature[t] uses only data[:t+1], regime[t] uses only features[:t+1] |
| Test 4 | HMM refit happens monthly (expanding window), XGBoost retrain weekly |
| Test 5 | Output contains: daily P&L series, equity curve, regime history, f_final history |
| Git | "S4-T2: VRP proxy backtest engine" |

**S4-T3: Naive Baseline**

| Field | Value |
|-------|-------|
| Depends on | S4-T2 |
| Files | Same engine, different config (regime disabled, constant f=1.0) |
| Test 1 | Naive 2008 MDD >> Regime-conditioned 2008 MDD |
| Test 2 | Sharpe difference (regime - naive) > 0.1 |
| Git | "S4-T3: naive baseline comparison" |

**S4-T4: CPCV + PBO**

| Field | Value |
|-------|-------|
| Depends on | S4-T2, S4-T1 |
| Files | `src/backtest/cpcv.py` |
| Test 1 | N=5, k=2 → generates exactly C(5,2)=10 train/test splits |
| Test 2 | Embargo: 5 days gap between each train/test boundary |
| Test 3 | No test period overlaps with its corresponding train period |
| Test 4 | PBO computation returns value in [0, 1] |
| Git | "S4-T4: CPCV and PBO overfitting defense" |

**S4-T5: Stress Period Analysis**

| Field | Value |
|-------|-------|
| Depends on | S4-T2 |
| Files | `notebooks/03_backtest_results.ipynb` (analysis, not code) |
| Check | GFC (2008): regime-conditioned MDD < 25% |
| Check | COVID (2020-03): regime-conditioned MDD < 20% |
| Check | Volmageddon (2018-02): regime-conditioned MDD < 15% |
| Check | Regime detected HV BEFORE or DURING each crisis, not AFTER |
| Git | "S4-T5: stress period analysis" |

**S4-T6: GO / NO-GO Verdict**

| Field | Value |
|-------|-------|
| Depends on | S4-T2, S4-T3, S4-T4, S4-T5 |
| Files | `notebooks/03_backtest_results.ipynb` (final section) |
| Output | Phase 1 verdict document with all 16 checks and actual values |
| Decision | GO → proceed to Phase 2. NO-GO → stop or revise. |
| Git | "S4-T6: Phase 1 verdict — [GO/NO-GO]" |

---

## Phase 2: Options Chain Backtest

### Sprint 5 — Polygon.io Integration (3-4 days)

**S5-T1: Data Availability Audit**

| Field | Value |
|-------|-------|
| Depends on | Phase 1 GO |
| Files | `scripts/data_audit.py` |
| Action | Call Polygon API, determine exact date range for SPX options |
| Output | Document: start date, end date, completeness assessment |
| Decision | If < 2 years: evaluate OptionsDX. If >= 2 years: proceed. |
| Critical | This is the "Odds-API discovery" moment. Do BEFORE building pipeline. |
| Git | "S5-T1: Polygon data availability audit" |

**S5-T2: PolygonFetcher**

| Field | Value |
|-------|-------|
| Depends on | S5-T1 (confirmed data available), S1-T2, S1-T3 |
| Files | `src/data/polygon_fetcher.py` |
| Test 1 | `fetch_options_chain('SPX', known_date)` → OptionsChain with 50+ puts |
| Test 2 | All quotes have bid > 0, ask > bid, IV > 0 |
| Test 3 | `fetch_date_range()` → matches audit results |
| Test 4 | Cache: second fetch → cache hit |
| Test 5 | Data quality checks: flag invalid quotes (negative bid, IV > 300%) |
| Git | "S5-T2: Polygon options chain fetcher" |

**S5-T3: Cross-Validation**

| Field | Value |
|-------|-------|
| Depends on | S5-T2 |
| Files | Part of data_audit.py or notebook |
| Test | ATM implied vol from Polygon chain ≈ VIX/100 (within ±2%) for 10 random dates |
| Git | "S5-T3: Polygon data cross-validation" |

---

### Sprint 6 — Heston + FFT Pricing (5-6 days)

**S6-T1: Black-Scholes (Full)**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/pricing/black_scholes.py` |
| Test 1 | put_price(S=100, K=95, T=0.25, r=0.05, σ=0.20) → verify against known BS value |
| Test 2 | Put-call parity: C - P = S - K*exp(-rT) within $0.001 |
| Test 3 | implied_vol: given BS price, recover σ within 0.0001 |
| Test 4 | find_strike_by_delta(S=5500, T=0.1, r=0.05, σ=0.15, Δ=-0.10) → K ≈ 5200-5300 |
| Test 5 | Greeks: delta in [-1, 0] for puts, gamma > 0, theta < 0 (usually), vega > 0 |
| Git | "S6-T1: Black-Scholes pricer with Greeks and IV solver" |

**S6-T2: Heston Model**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/pricing/heston.py` |
| Test 1 | Known params (v0=0.04, κ=1.5, θ=0.04, σv=0.3, ρ=-0.7): char function value matches literature |
| Test 2 | check_feller(): 2×1.5×0.04=0.12 > 0.3²=0.09 → True |
| Test 3 | check_feller(): 2×1.5×0.02=0.06 < 0.3²=0.09 → False |
| Test 4 | to_dict() / from_dict() roundtrip preserves all params |
| Git | "S6-T2: Heston stochastic vol model" |

**S6-T3: Carr-Madan FFT**

| Field | Value |
|-------|-------|
| Depends on | S6-T2 |
| Files | `src/pricing/fft_pricer.py` |
| Test 1 | Heston with σv=0, ρ=0 (reduces to BS) → all prices match BS within $0.01 |
| Test 2 | 4096-point FFT produces prices for 4096 strikes in < 50ms |
| Test 3 | Put-call parity holds across all output strikes (within $0.02) |
| Test 4 | All output prices are positive |
| Test 5 | Prices monotonically increase for puts as strike increases |
| Git | "S6-T3: Carr-Madan FFT pricing engine" |

**S6-T4: Heston Calibrator**

| Field | Value |
|-------|-------|
| Depends on | S6-T3, S5-T2 (needs real chain data) |
| Files | `src/pricing/calibrator.py` |
| Test 1 | Calibrate on real date → RMSE < average bid-ask spread |
| Test 2 | Feller condition satisfied in output |
| Test 3 | All params within bounds |
| Test 4 | Fallback: poison LM → status='de_only', WARNING |
| Test 5 | Fallback: poison DE → status='fallback_prev' (needs prev day params) |
| Test 6 | Fallback: both fail → status='fallback_bs', CRITICAL |
| Test 7 | Calibration time < 30 seconds |
| Git | "S6-T4: Heston calibrator with fallback chain" |

**S6-T5: Vol Surface + Spread Greeks**

| Field | Value |
|-------|-------|
| Depends on | S6-T4 |
| Files | `src/pricing/vol_surface.py`, `src/pricing/greeks.py` |
| Test 1 | implied_vol(K, T) → positive, reasonable range (10-40%) |
| Test 2 | IV skew present: IV(OTM put) > IV(ATM) |
| Test 3 | Surface delta matches BS delta computed with surface IV |
| Test 4 | Spread Greeks: theta > 0 (seller benefits), vega < 0 (vol hurts seller) |
| Test 5 | Spread delta ≈ short_delta - long_delta |
| Git | "S6-T5: vol surface and spread Greeks" |

---

### Sprint 7 — Strategy Engine (4-5 days)

**S7-T1: VRP Signal (Chain-Based)**

| Field | Value |
|-------|-------|
| Depends on | S5-T2, S1-T5 |
| Files | `src/strategy/vrp_signal.py` |
| Test 1 | Chain-based VRP vs Phase 1 proxy correlation > 0.7 (on same dates) |
| Test 2 | Chain VRP typically smaller than proxy (proxy overstates) |
| Git | "S7-T1: chain-based VRP signal" |

**S7-T2: Strike Selector**

| Field | Value |
|-------|-------|
| Depends on | S6-T5 |
| Files | `src/strategy/strike_selector.py` |
| Test 1 | Selected strike delta within [-0.12, -0.08] of target -0.10 |
| Test 2 | VIX=15, DTE=35, S=5500 → K ≈ 5200-5250 |
| Test 3 | VIX=30, DTE=35, S=5500 → K ≈ 4900-5000 (more OTM) |
| Test 4 | Output rounded to nearest $5 (SPX strike spacing) |
| Git | "S7-T2: 10-delta strike selector" |

**S7-T3: Spread Construction**

| Field | Value |
|-------|-------|
| Depends on | S7-T2 |
| Files | `src/strategy/spread.py` |
| Test 1 | max_loss = width - premium (exact) |
| Test 2 | premium > 0 |
| Test 3 | premium / width > 0.10 for typical entry |
| Test 4 | breakeven = short_strike - premium |
| Test 5 | pnl_at_expiry: S_T > K1 → pnl = premium. S_T < K2 → pnl = -(width - premium) |
| Git | "S7-T3: put credit spread construction" |

**S7-T4: Entry Decision**

| Field | Value |
|-------|-------|
| Depends on | S2-T5, S7-T1 |
| Files | `src/strategy/entry.py` |
| Test 1 | P_HV=0.1, z_VRP=0.5, ratio=0.12 → enter, scale=1.0 |
| Test 2 | P_HV=0.3, z_VRP=0.5, ratio=0.12 → enter, scale=0.5 |
| Test 3 | P_HV=0.6, z_VRP=0.5, ratio=0.12 → skip (regime) |
| Test 4 | P_HV=0.1, z_VRP=-1.5, ratio=0.12 → skip (VRP) |
| Test 5 | P_HV=0.1, z_VRP=0.5, ratio=0.06 → skip (premium) |
| Git | "S7-T4: three-condition entry decision" |

**S7-T5: Position Manager**

| Field | Value |
|-------|-------|
| Depends on | S7-T3 |
| Files | `src/strategy/position_manager.py` |
| Test 1 | 80% profit → exit (profit_target) |
| Test 2 | -250% premium loss → exit (stop_loss, urgent) |
| Test 3 | DTE = 5 → exit (dte) |
| Test 4 | P_HV = 0.85 → exit (regime_emergency, urgent) |
| Test 5 | 50% profit, DTE=20, P_HV=0.1 → hold |
| Git | "S7-T5: position manager with exit triggers" |

---

### Sprint 8 — Phase 2 Backtest + Verdict (6-8 days)

**S8-T1: Options Backtest Engine**

| Field | Value |
|-------|-------|
| Depends on | All Sprint 5-7 tasks |
| Files | `src/backtest/options_engine.py` |
| Test 1 | 1-year run → 20-40 trades, all valid strikes in chain |
| Test 2 | No future data: verify date checks in engine loop |
| Test 3 | Spot-check 3 trade P&Ls against manual calculation |
| Test 4 | Transaction costs applied: $0.65/contract + slippage |
| Git | "S8-T1: options chain backtest engine" |

**S8-T2: Transaction Cost Model + Stress Test**

| Field | Value |
|-------|-------|
| Depends on | S8-T1 |
| Files | Part of options_engine.py |
| Test 1 | Normal slippage (25%): total cost ≈ $25-30/spread |
| Test 2 | Stress slippage (50% for HV exits): rerun backtest |
| Test 3 | Stress Sharpe > 0.3, Stress MDD < 30% |
| Git | "S8-T2: transaction cost model and stress test" |

**S8-T3: Phase 1 vs Phase 2 Correlation**

| Field | Value |
|-------|-------|
| Depends on | S8-T1, S4-T2 |
| Files | Analysis in notebook |
| Test | Monthly return correlation between proxy and options backtest > 0.5 (GO minimum) |
| Note | If < 0.5: investigate (costs? discrete entry? skew effects?) |
| Git | "S8-T3: phase correlation analysis" |

**S8-T4: CPCV + Parameter Sensitivity**

| Field | Value |
|-------|-------|
| Depends on | S8-T1 |
| Files | Reuse `src/backtest/cpcv.py` |
| Test 1 | CPCV mean Sharpe > 0.3 |
| Test 2 | PBO < 5% |
| Test 3 | ±20% on delta, width, profit target, stop loss → Sharpe within ±30% |
| Git | "S8-T4: Phase 2 overfitting defense" |

**S8-T5: GO / NO-GO Verdict**

| Field | Value |
|-------|-------|
| Depends on | S8-T1 through S8-T4 |
| Files | `notebooks/04_options_backtest.ipynb` |
| Output | Phase 2 verdict document with all 16 checks |
| Decision | GO → Phase 3. NO-GO → revise or stop. |
| Git | "S8-T5: Phase 2 verdict — [GO/NO-GO]" |

---

## Phase 3: Paper Trading

### Sprint 9 — IBKR Execution Layer (4-5 days)

**S9-T1: IBKRBroker**

| Field | Value |
|-------|-------|
| Depends on | Phase 2 GO, IBKR account ready |
| Files | `src/execution/broker.py` |
| Test 1 | Connect to paper TWS (port 7497) → is_connected() True |
| Test 2 | get_spx_price() → current SPX level (market hours) or last close |
| Test 3 | get_account_value() → paper balance (~$1M default) |
| Test 4 | get_option_quote(5200, date, 'P') → valid bid/ask/IV/delta |
| Test 5 | mode='live' → requires interactive "CONFIRM LIVE" (Phase 3 should never reach this) |
| Git | "S9-T1: IBKR broker wrapper" |

**S9-T2: Order Manager + Safety Guards**

| Field | Value |
|-------|-------|
| Depends on | S9-T1 |
| Files | `src/execution/order_manager.py` |
| Test 1 | Place valid spread order → accepted by IBKR paper |
| Test 2 | Safety: n_contracts=100 → REJECTED |
| Test 3 | Safety: underlying='AAPL' → REJECTED |
| Test 4 | Safety: short_strike < long_strike → REJECTED |
| Test 5 | Safety: DTE < 7 → REJECTED |
| Git | "S9-T2: order manager with safety guards" |

**S9-T3: Fill Tracker**

| Field | Value |
|-------|-------|
| Depends on | S9-T1 |
| Files | `src/execution/fill_tracker.py` |
| Test | After paper fill: fill.avg_price recorded, slippage calculated, logged to SQLite |
| Git | "S9-T3: fill tracker and slippage logger" |

---

### Sprint 10 — Orchestration (4-5 days)

**S10-T1: Market Calendar**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/orchestrator/market_calendar.py`, `config/holidays.yaml` |
| Test 1 | is_trading_day(date(2026, 1, 1)) → False (New Year's) |
| Test 2 | is_trading_day(date(2026, 3, 12)) → True (Thursday) |
| Test 3 | is_trading_day(date(2026, 3, 14)) → False (Saturday) |
| Test 4 | is_early_close(date(2026, 11, 27)) → True (day after Thanksgiving) |
| Test 5 | next_trading_day(date(2026, 3, 13)) → date(2026, 3, 16) (skip weekend) |
| Git | "S10-T1: market calendar" |

**S10-T2: State Manager + Pipeline Context**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/orchestrator/state_manager.py`, `src/orchestrator/pipeline_context.py` |
| Test 1 | mark_running / mark_complete lifecycle |
| Test 2 | Stale lock: mark_running, wait 61 min, is_running() → False (auto-cleared) |
| Test 3 | save_context / get_latest_context roundtrip |
| Test 4 | SQLite tables created on first access |
| Git | "S10-T2: state manager and pipeline context" |

**S10-T3: Failure Handler**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `src/orchestrator/failure_handler.py` |
| Test 1 | retry(always_fails, max_retries=3, delay=0) → 3 attempts, then fallback |
| Test 2 | retry(succeeds_on_attempt_2, max_retries=3) → 2 attempts, returns result |
| Test 3 | retry(fails, fallback=lambda: "cached") → returns "cached" with source='fallback' |
| Test 4 | retry(fails, no_fallback) → returns None with source='failed' |
| Git | "S10-T3: failure handler with retry and fallback" |

**S10-T4: Daily Pipeline**

| Field | Value |
|-------|-------|
| Depends on | S10-T1, S10-T2, S10-T3, all data/regime/pricing modules |
| Files | `src/orchestrator/daily_pipeline.py` |
| Test 1 | Run with all real dependencies → all steps OK |
| Test 2 | Simulate data fetch failure → cache fallback, WARNING |
| Test 3 | Simulate calibration failure → prev day fallback |
| Test 4 | Market holiday → pipeline skips cleanly |
| Test 5 | State saved to SQLite after completion |
| Git | "S10-T4: daily EOD pipeline" |

**S10-T5: Weekly Pipeline**

| Field | Value |
|-------|-------|
| Depends on | S10-T4, S7-T4, S9-T2 |
| Files | `src/orchestrator/weekly_pipeline.py` |
| Test 1 | Tuesday with conditions met → spread order placed |
| Test 2 | Wednesday → SKIPPED (not entry day) |
| Test 3 | Open position exists → SKIPPED (no stacking) |
| Test 4 | Conditions not met → SKIPPED with reason logged |
| Git | "S10-T5: weekly entry pipeline" |

**S10-T6: Monthly Pipeline + Scheduler**

| Field | Value |
|-------|-------|
| Depends on | S10-T4, S2-T5 |
| Files | `src/orchestrator/monthly_pipeline.py`, `src/orchestrator/scheduler.py` |
| Test 1 | HMM refit with expanded data → stability check passes |
| Test 2 | Scheduler registers all 3 jobs with correct cron triggers |
| Test 3 | Scheduler respects misfire_grace_time |
| Git | "S10-T6: monthly pipeline and scheduler" |

---

### Sprint 11 — Alerts & Monitoring (2-3 days)

**S11-T1: Email Sender**

| Field | Value |
|-------|-------|
| Depends on | S1-T1 |
| Files | `alerts/email_sender.py` |
| Test | Send test email → received within 60 seconds |
| Git | "S11-T1: SMTP email sender" |

**S11-T2: Alert Manager**

| Field | Value |
|-------|-------|
| Depends on | S11-T1 |
| Files | `alerts/manager.py` |
| Test 1 | INFO alert → DB entry only, no email |
| Test 2 | WARNING alert → DB entry + email |
| Test 3 | CRITICAL alert → DB entry + email with [CRITICAL] prefix |
| Test 4 | Escalation: 3 consecutive WARNINGs for same step → CRITICAL |
| Git | "S11-T2: alert manager with escalation" |

**S11-T3: Daily Report + Trade Logger**

| Field | Value |
|-------|-------|
| Depends on | S11-T1, S10-T2 |
| Files | Part of daily_pipeline.py (report generation), SQLite schema |
| Test 1 | Report email sent with all sections (regime, VRP, position, risk, pipeline) |
| Test 2 | Trade entry creates row in trades table |
| Test 3 | Daily snapshot creates row in daily_snapshots table |
| Git | "S11-T3: daily report and trade logger" |

**S11-T4: Concordance Check Script**

| Field | Value |
|-------|-------|
| Depends on | S8-T1, S10-T2 |
| Files | `src/backtest/concordance.py`, `scripts/concordance_check.py` |
| Test | Compare live outputs vs backtest for same dates → metrics computed |
| Git | "S11-T4: concordance checker" |

**S11-T5: Kill Switch + Run Script**

| Field | Value |
|-------|-------|
| Depends on | S9-T1, S10-T2 |
| Files | `src/risk/kill_switch.py`, `scripts/kill.py`, `scripts/run_system.py` |
| Test 1 | kill.py → closes all positions (paper), sends EMERGENCY alert |
| Test 2 | run_system.py → starts scheduler, runs until SIGTERM |
| Git | "S11-T5: kill switch and system entry point" |

---

### Sprint 12 — Paper Trading Operation (20+ trading days)

This is NOT a development sprint. It's operational validation.

| Week | Focus | Checks |
|------|-------|--------|
| Week 1-2 | System stability | 10 consecutive days without crash, reports delivered, DB growing |
| Week 2-3 | Execution mechanics | 2+ paper trades placed and filled, 1+ exit triggered |
| Week 3-4 | Signal concordance | Regime > 95%, entry > 95%, strikes > 90% |
| Week 4 | Failure recovery | Intentional tests: IBKR kill, API block, calibration poison, DD override |

**Completion:** Phase 3 verdict with all 17 checks. See `phase3.md` Section 9.

---

## Phase 4: Live Trading

No development sprints. Operational transition:

| Stage | Duration | Action |
|-------|----------|--------|
| Stage 1 | 4-8 weeks | Switch to live, $5-10K, tightened risk params |
| Stage 2 | 2-3 months | Restore standard params, $15-25K |
| Stage 3 | Ongoing | Full capital, quarterly reviews |

See `phase4.md` for scaling criteria and operational procedures.

---

## Timeline Summary

| Sprint | Phase | Duration | Cumulative |
|--------|-------|----------|-----------|
| S1: Data Foundation | P1 | 3-4 days | 3-4 days |
| S2: Regime Detection | P1 | 4-5 days | 7-9 days |
| S3: Risk Management | P1 | 3-4 days | 10-13 days |
| S4: Backtest + Verdict | P1 | 5-6 days | 15-19 days |
| — | **Phase 1 GO/NO-GO** | — | — |
| S5: Polygon Integration | P2 | 3-4 days | 18-23 days |
| S6: Heston + FFT | P2 | 5-6 days | 23-29 days |
| S7: Strategy Engine | P2 | 4-5 days | 27-34 days |
| S8: Backtest + Verdict | P2 | 6-8 days | 33-42 days |
| — | **Phase 2 GO/NO-GO** | — | — |
| S9: IBKR Execution | P3 | 4-5 days | 37-47 days |
| S10: Orchestration | P3 | 4-5 days | 41-52 days |
| S11: Alerts + Monitoring | P3 | 2-3 days | 43-55 days |
| S12: Paper Trading | P3 | 20+ trading days | 63-75+ days |
| — | **Phase 3 GO/NO-GO** | — | — |
| Phase 4: Live Stage 1 | P4 | 4-8 weeks | — |

**Total to first live trade:** approximately 3-4 months.

---

## Appendix: Task Count by Module

| Module | Tasks | Sprint |
|--------|-------|--------|
| Data (fetcher, cache, features, models) | 5 | S1 |
| Data (Polygon) | 3 | S5 |
| Regime (HMM, XGBoost, detector) | 5 | S2 |
| Pricing (BS, Heston, FFT, calibrator, surface) | 5 | S6 |
| Strategy (VRP, entry, strike, spread, position) | 5 | S7 |
| Risk (vol, Kelly, DD, leverage) | 4 | S3 |
| Backtest (metrics, proxy engine, CPCV, verdict) | 6 | S4 |
| Backtest (options engine, costs, correlation) | 5 | S8 |
| Execution (broker, orders, fills) | 3 | S9 |
| Orchestration (calendar, state, failure, pipelines) | 6 | S10 |
| Alerts + monitoring | 5 | S11 |
| **Total** | **52 tasks** | **11 sprints** |
