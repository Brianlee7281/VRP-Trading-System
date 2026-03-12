# Implementation Blueprint

**VRP Production System — Project Structure, Module Responsibilities, and Configuration**

> Translates `pipeline_design.md` and `orchestration.md` into a concrete folder structure.
> Defines every file's responsibility, every module's dependencies, and the complete config schema.
> This is the map that Claude Code follows when building the system.

---

## Table of Contents

1. [Folder Structure](#1-folder-structure)
2. [Module Dependency Map](#2-module-dependency-map)
3. [File-by-File Specification](#3-file-by-file-specification)
4. [Configuration Schema](#4-configuration-schema)
5. [Data Directory Layout](#5-data-directory-layout)
6. [Testing Strategy](#6-testing-strategy)
7. [Environment & Dependencies](#7-environment--dependencies)

---

## 1. Folder Structure

```
vrp-trading/
│
├── config/
│   ├── settings.yaml              # All parameters, thresholds, schedules
│   ├── credentials.yaml.example   # API key template (.gitignored)
│   └── holidays.yaml              # Market holiday calendar (updated annually)
│
├── src/
│   ├── __init__.py
│   │
│   ├── data/                      # ── Layer 0: Data Acquisition ──
│   │   ├── __init__.py
│   │   ├── fetcher.py             # DataFetcher(ABC), FREDFetcher, YFinanceFetcher
│   │   ├── polygon_fetcher.py     # PolygonFetcher (options chain, Phase 2+)
│   │   ├── features.py            # Feature computation (RV, VRP, TS, ΔVol)
│   │   ├── cache.py               # Source-tagged parquet cache
│   │   └── models.py              # Data models (OptionsChain, OptionQuote)
│   │
│   ├── regime/                    # ── Layer 1: Regime Detection ──
│   │   ├── __init__.py
│   │   ├── hmm.py                 # RegimeHMM (3-state, centroid-anchored)
│   │   ├── xgboost_clf.py         # RegimeXGBoost (calibrated classifier)
│   │   ├── features.py            # Regime-specific feature engineering
│   │   ├── calibration.py         # Brier score, reliability diagram
│   │   └── detector.py            # RegimeDetector (HMM + XGBoost orchestrator)
│   │
│   ├── pricing/                   # ── Layer 2: Options Pricing ──
│   │   ├── __init__.py
│   │   ├── black_scholes.py       # BSPricer (price, Greeks, IV solver)
│   │   ├── heston.py              # HestonModel (characteristic function)
│   │   ├── fft_pricer.py          # FFTPricer (Carr-Madan)
│   │   ├── calibrator.py          # HestonCalibrator (DE → LM, Feller, fallback)
│   │   ├── vol_surface.py         # VolSurface (interpolated surface object)
│   │   └── greeks.py              # Spread-level Greeks computation
│   │
│   ├── strategy/                  # ── Layer 3: Strategy Engine ──
│   │   ├── __init__.py
│   │   ├── vrp_signal.py          # VRP measurement and z-score
│   │   ├── entry.py               # EntryDecision (3-condition AND gate)
│   │   ├── strike_selector.py     # StrikeSelector (10-delta Newton-Raphson)
│   │   ├── spread.py              # PutCreditSpread (construction, P&L, lifecycle)
│   │   └── position_manager.py    # PositionManager (exit triggers, monitoring)
│   │
│   ├── risk/                      # ── Layer 4: Risk Management ──
│   │   ├── __init__.py
│   │   ├── vol_scaling.py         # VolScaler (σ_target / σ_portfolio)
│   │   ├── kelly_ceiling.py       # KellyCeiling (adaptive α, regime prior)
│   │   ├── drawdown.py            # DrawdownMonitor (DD tracking, override)
│   │   ├── leverage.py            # LeverageChain (min-chain orchestrator)
│   │   └── kill_switch.py         # KillSwitch (emergency full liquidation)
│   │
│   ├── execution/                 # ── Layer 5: Execution (Phase 3+) ──
│   │   ├── __init__.py
│   │   ├── broker.py              # IBKRBroker (ib_insync wrapper, paper/live)
│   │   ├── order_manager.py       # OrderManager (construction, safety guards)
│   │   ├── fill_tracker.py        # FillTracker (fill logging, slippage calc)
│   │   └── paper_trader.py        # PaperTrader (Phase 2 simulated execution)
│   │
│   ├── orchestrator/              # ── Orchestration (Phase 3+) ──
│   │   ├── __init__.py
│   │   ├── scheduler.py           # APScheduler job registration
│   │   ├── daily_pipeline.py      # DailyPipeline (EOD: data → regime → monitor)
│   │   ├── weekly_pipeline.py     # WeeklyPipeline (Tuesday: entry → execute)
│   │   ├── monthly_pipeline.py    # MonthlyPipeline (HMM refit, cleanup)
│   │   ├── failure_handler.py     # FailureHandler (retry, fallback, escalation)
│   │   ├── state_manager.py       # StateManager (pipeline state in SQLite)
│   │   ├── market_calendar.py     # MarketCalendar (holidays, early closes)
│   │   └── pipeline_context.py    # PipelineContext (shared state object)
│   │
│   └── backtest/                  # ── Validation ──
│       ├── __init__.py
│       ├── proxy_engine.py        # Phase 1: VRP proxy backtest
│       ├── options_engine.py      # Phase 2: options chain backtest
│       ├── metrics.py             # Sharpe, MDD, CVaR, win rate, Calmar, PF
│       ├── cpcv.py                # CPCV + PBO + DSR
│       └── concordance.py         # Phase 3: live vs backtest signal comparison
│
├── alerts/
│   ├── __init__.py
│   ├── manager.py                 # AlertManager (severity routing)
│   └── email_sender.py            # EmailSender (SMTP dispatch)
│
├── scripts/
│   ├── run_system.py              # Main entry: starts scheduler (Phase 3+)
│   ├── run_phase1.py              # Phase 1 backtest entry point
│   ├── run_phase2.py              # Phase 2 backtest entry point
│   ├── concordance_check.py       # Weekly concordance analysis
│   ├── kill.py                    # CLI emergency kill switch
│   └── data_audit.py             # Polygon data availability check
│
├── tests/
│   ├── test_data/
│   │   ├── test_fetcher.py
│   │   ├── test_features.py
│   │   └── test_cache.py
│   ├── test_regime/
│   │   ├── test_hmm.py
│   │   ├── test_xgboost.py
│   │   └── test_detector.py
│   ├── test_pricing/
│   │   ├── test_black_scholes.py
│   │   ├── test_heston.py
│   │   ├── test_fft.py
│   │   ├── test_calibrator.py
│   │   └── test_vol_surface.py
│   ├── test_strategy/
│   │   ├── test_entry.py
│   │   ├── test_strike_selector.py
│   │   ├── test_spread.py
│   │   └── test_position_manager.py
│   ├── test_risk/
│   │   ├── test_vol_scaling.py
│   │   ├── test_kelly.py
│   │   ├── test_drawdown.py
│   │   └── test_leverage.py
│   ├── test_backtest/
│   │   ├── test_proxy_engine.py
│   │   ├── test_options_engine.py
│   │   └── test_metrics.py
│   └── conftest.py                # Shared fixtures
│
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_regime_analysis.ipynb
│   ├── 03_backtest_results.ipynb       # Phase 1 proxy
│   ├── 03b_heston_validation.ipynb     # Phase 2 calibration
│   ├── 04_options_backtest.ipynb       # Phase 2 full backtest
│   └── 05_live_monitoring.ipynb        # Phase 3-4 operational
│
├── data/                          # .gitignored (except README)
│   ├── README.md                  # Describes data directory structure
│   ├── raw/
│   │   ├── fred/
│   │   ├── yfinance/
│   │   └── polygon/
│   ├── processed/
│   │   ├── features/
│   │   ├── regime/
│   │   └── calibration/
│   ├── backtest/
│   │   └── results/
│   └── vrp.db                     # SQLite: trades, snapshots, alerts, state
│
├── logs/                          # .gitignored
│   └── (daily log files)
│
├── docs/
│   ├── mathematical_design_production.md
│   ├── mathematical_design_research.md
│   ├── pipeline_design.md
│   ├── phase1.md
│   ├── phase2.md
│   ├── phase3.md
│   ├── phase4.md
│   ├── orchestration.md
│   ├── implementation_blueprint.md    # This file
│   ├── implementation_roadmap.md
│   └── config_reference.md
│
├── .claude/
│   └── rules/
│       ├── coding.md              # Coding standards for Claude Code
│       ├── patterns.md            # Project-specific patterns
│       └── workflow.md            # Git, testing, commit conventions
│
├── CLAUDE.md                      # Claude Code project overview
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 2. Module Dependency Map

### 2.1 Import Dependencies

```
config/settings.yaml ──────────────────────────────────────────────┐
                                                                    │
src/data/models.py ← (no deps, pure data classes)                   │
     ↑                                                              │
src/data/fetcher.py ← models, cache                                 │
src/data/polygon_fetcher.py ← models, cache                         │
src/data/features.py ← (pandas/numpy only)                          │
src/data/cache.py ← (pathlib, parquet only)                         │
                                                                    │
src/regime/features.py ← src/data/features                          │
src/regime/hmm.py ← hmmlearn, regime/features                      │
src/regime/xgboost_clf.py ← xgboost, sklearn                       │
src/regime/calibration.py ← sklearn.metrics                         │
src/regime/detector.py ← hmm, xgboost_clf, calibration             │
                                                                    │
src/pricing/black_scholes.py ← scipy.stats                         │
src/pricing/heston.py ← numpy (complex math)                       │
src/pricing/fft_pricer.py ← numpy.fft, heston                      │
src/pricing/calibrator.py ← scipy.optimize, fft_pricer, heston     │
src/pricing/vol_surface.py ← calibrator, black_scholes             │
src/pricing/greeks.py ← vol_surface, black_scholes                 │
                                                                    │
src/strategy/vrp_signal.py ← src/data/features                     │
src/strategy/entry.py ← regime/detector, strategy/vrp_signal       │
src/strategy/strike_selector.py ← pricing/vol_surface              │
src/strategy/spread.py ← pricing/greeks, data/models               │
src/strategy/position_manager.py ← spread, regime/detector         │
                                                                    │
src/risk/vol_scaling.py ← (numpy only)                              │
src/risk/kelly_ceiling.py ← regime/detector                         │
src/risk/drawdown.py ← (numpy only)                                 │
src/risk/leverage.py ← vol_scaling, kelly_ceiling, drawdown         │
src/risk/kill_switch.py ← execution/broker                          │
                                                                    │
src/execution/broker.py ← ib_insync                                 │
src/execution/order_manager.py ← broker, strategy/spread            │
src/execution/fill_tracker.py ← broker                              │
src/execution/paper_trader.py ← strategy/spread, data/models        │
                                                                    │
src/orchestrator/pipeline_context.py ← data/models, regime, pricing │
src/orchestrator/state_manager.py ← sqlite3                         │
src/orchestrator/failure_handler.py ← alerts/manager                │
src/orchestrator/market_calendar.py ← config/holidays.yaml          │
src/orchestrator/scheduler.py ← apscheduler                         │
src/orchestrator/daily_pipeline.py ← ALL modules above              │
src/orchestrator/weekly_pipeline.py ← ALL modules above             │
src/orchestrator/monthly_pipeline.py ← regime, state_manager        │
                                                                    │
src/backtest/metrics.py ← (numpy/pandas only)                       │
src/backtest/proxy_engine.py ← data, regime, risk, metrics          │
src/backtest/options_engine.py ← data, regime, pricing, strategy,   │
│                                  risk, metrics                     │
src/backtest/cpcv.py ← metrics                                      │
src/backtest/concordance.py ← state_manager, options_engine         │
                                                                    │
alerts/manager.py ← email_sender                                    │
alerts/email_sender.py ← smtplib                                    │
```

### 2.2 Build Order (Bottom-Up)

Most-depended-on modules are built first:

```
Layer 0: No internal deps (build first)
  1. src/data/models.py
  2. src/data/cache.py
  3. src/data/fetcher.py
  4. src/data/features.py

Layer 1: Depends on Layer 0
  5. src/regime/features.py
  6. src/regime/hmm.py
  7. src/regime/xgboost_clf.py
  8. src/regime/calibration.py
  9. src/regime/detector.py

Layer 2: Depends on Layer 0 (mostly independent of Layer 1)
  10. src/pricing/black_scholes.py
  11. src/pricing/heston.py
  12. src/pricing/fft_pricer.py
  13. src/pricing/calibrator.py
  14. src/pricing/vol_surface.py
  15. src/pricing/greeks.py

Layer 3: Depends on Layer 1 + 2
  16. src/strategy/vrp_signal.py
  17. src/strategy/entry.py
  18. src/strategy/strike_selector.py
  19. src/strategy/spread.py
  20. src/strategy/position_manager.py

Layer 4: Depends on Layer 1
  21. src/risk/vol_scaling.py
  22. src/risk/kelly_ceiling.py
  23. src/risk/drawdown.py
  24. src/risk/leverage.py
  25. src/risk/kill_switch.py

Backtest: Depends on Layers 0-4
  26. src/backtest/metrics.py
  27. src/backtest/proxy_engine.py
  28. src/backtest/options_engine.py
  29. src/backtest/cpcv.py

Execution: Depends on Layer 3 (Phase 3+)
  30. src/execution/broker.py
  31. src/execution/order_manager.py
  32. src/execution/fill_tracker.py

Orchestration: Depends on everything (Phase 3+)
  33. src/orchestrator/pipeline_context.py
  34. src/orchestrator/state_manager.py
  35. src/orchestrator/market_calendar.py
  36. src/orchestrator/failure_handler.py
  37. src/orchestrator/scheduler.py
  38. src/orchestrator/daily_pipeline.py
  39. src/orchestrator/weekly_pipeline.py
  40. src/orchestrator/monthly_pipeline.py

Alerts (Phase 3+):
  41. alerts/email_sender.py
  42. alerts/manager.py

Scripts:
  43. scripts/run_phase1.py
  44. scripts/run_phase2.py
  45. scripts/run_system.py
  46. scripts/kill.py
  47. scripts/concordance_check.py
  48. scripts/data_audit.py
```

### 2.3 Phase Activation

| # | File | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|------|---------|---------|---------|---------|
| 1-4 | data/* | ✅ | ✅ | ✅ | ✅ |
| — | data/polygon_fetcher.py | — | ✅ | ✅ | ✅ |
| 5-9 | regime/* | ✅ | ✅ | ✅ | ✅ |
| 10 | pricing/black_scholes.py | ✅ | ✅ | ✅ | ✅ |
| 11-15 | pricing/heston,fft,calibrator,surface,greeks | — | ✅ | ✅ | ✅ |
| 16-20 | strategy/* | — | ✅ | ✅ | ✅ |
| 21-25 | risk/* | ✅ | ✅ | ✅ | ✅ |
| 26-27 | backtest/metrics,proxy_engine | ✅ | ✅ | ✅ | ✅ |
| 28-29 | backtest/options_engine,cpcv | — | ✅ | ✅ | ✅ |
| — | backtest/concordance.py | — | — | ✅ | ✅ |
| 30-32 | execution/* | — | — | ✅ | ✅ |
| 33-40 | orchestrator/* | — | — | ✅ | ✅ |
| 41-42 | alerts/* | — | — | ✅ | ✅ |

---

## 3. File-by-File Specification

### 3.1 Data Layer

**`src/data/models.py`** — Pure data classes. No business logic. No external dependencies.

```python
# Key classes:
@dataclass OptionQuote        # strike, expiry, type, bid, ask, mid, IV, Greeks, volume, OI
@dataclass OptionsChain       # underlying_price, trade_date, quotes[], risk_free_rate
@dataclass MarketData         # date, spx_close, vix, vix3m, vvix, risk_free_rate
@dataclass FeatureVector      # rv_5, rv_21, rv_63, vix, vix3m, vvix, ts, dvol_5, vrp, z_vrp
```

**`src/data/fetcher.py`** — Abstract data fetcher + free-source implementations.

```python
class DataFetcher(ABC):       # fetch_spx_ohlcv, fetch_vix, fetch_vix3m, fetch_vvix, fetch_rfr
class FREDFetcher(DataFetcher) # FRED API for VIX (VIXCLS), VIX3M (VXVCLS), rates (DGS10)
class YFinanceFetcher          # Yahoo Finance for ^GSPC (SPX OHLCV)
class CBOEFetcher              # CBOE direct download for VVIX
```

**`src/data/polygon_fetcher.py`** — Polygon.io options chain fetcher. Separate file because it has a different interface (options chain, not time series).

```python
class PolygonFetcher:
    fetch_options_chain(underlying, trade_date, min_dte, max_dte) -> OptionsChain
    fetch_date_range() -> tuple[date, date]
    validate_chain(chain: OptionsChain) -> ValidationResult
```

**`src/data/features.py`** — Stateless feature computation functions.

```python
def compute_realized_vol(close: pd.Series, window: int) -> pd.Series
def compute_vrp_proxy(vix: pd.Series, rv_21: pd.Series) -> pd.Series
def compute_vrp_zscore(vrp: pd.Series, window: int = 252) -> pd.Series
def compute_term_structure(vix: pd.Series, vix3m: pd.Series) -> pd.Series
def compute_vol_acceleration(rv_5: pd.Series, rv_21: pd.Series) -> pd.Series
def compute_all_features(market_data: pd.DataFrame) -> pd.DataFrame
```

**`src/data/cache.py`** — Read/write parquet files with source tagging.

```python
class DataCache:
    read(source: str, key: str) -> pd.DataFrame | None
    write(source: str, key: str, data: pd.DataFrame) -> None
    exists(source: str, key: str) -> bool
    age_days(source: str, key: str) -> int | None
    cleanup(max_age_days: int = 90) -> int   # returns files deleted
```

### 3.2 Regime Layer

**`src/regime/hmm.py`** — 3-state Gaussian HMM with custom filtered probability extraction.

```python
class RegimeHMM:
    fit(features: pd.DataFrame) -> None
    get_filtered_probs(features: pd.DataFrame) -> np.ndarray     # (T, 3)
    get_labels() -> np.ndarray                                    # (T,)
    check_stability(old_labels: np.ndarray) -> float              # agreement ratio
    save(path: str) -> None
    load(path: str) -> None
    # Internal: _apply_centroid_labeling, _extract_forward_variables
```

**`src/regime/xgboost_clf.py`** — Calibrated XGBoost multiclass classifier.

```python
class RegimeXGBoost:
    train(features: pd.DataFrame, labels: np.ndarray) -> float   # returns Brier
    predict(features: pd.Series) -> np.ndarray                    # [P_LV, P_NV, P_HV]
    save(path: str) -> None
    load(path: str) -> None
```

**`src/regime/detector.py`** — Orchestrates HMM + XGBoost into single interface.

```python
class RegimeDetector:
    predict(features: pd.Series) -> RegimePrediction
    retrain_xgboost(features: pd.DataFrame, labels: np.ndarray) -> float
    refit_hmm(features: pd.DataFrame) -> bool
    # Returns RegimePrediction(probabilities, regime, confidence, timestamp)
```

### 3.3 Pricing Layer

**`src/pricing/black_scholes.py`** — Closed-form BS formulas.

```python
class BSPricer:
    put_price(S, K, T, r, sigma) -> float
    call_price(S, K, T, r, sigma) -> float
    put_delta(S, K, T, r, sigma) -> float
    put_gamma(S, K, T, r, sigma) -> float
    put_theta(S, K, T, r, sigma) -> float
    put_vega(S, K, T, r, sigma) -> float
    implied_vol(market_price, S, K, T, r, option_type) -> float
    find_strike_by_delta(S, T, r, sigma, target_delta) -> float
```

**`src/pricing/heston.py`** — Heston stochastic vol model.

```python
class HestonModel:
    __init__(v0, kappa, theta, sigma_v, rho)
    characteristic_function(xi, T, r, S0) -> complex
    check_feller() -> bool
    to_dict() -> dict
    from_dict(d: dict) -> HestonModel
```

**`src/pricing/fft_pricer.py`** — Carr-Madan FFT.

```python
class FFTPricer:
    __init__(model: HestonModel, N=4096, alpha=1.5)
    price_calls(S, T, r) -> tuple[np.ndarray, np.ndarray]   # (strikes, prices)
    price_puts(S, T, r) -> tuple[np.ndarray, np.ndarray]    # via put-call parity
```

**`src/pricing/calibrator.py`** — Heston calibration with fallback chain.

```python
class HestonCalibrator:
    calibrate(chain: OptionsChain) -> CalibrationResult
    # CalibrationResult: model, rmse, status, params, timestamp
    # Status: 'success', 'de_only', 'fallback_prev', 'fallback_bs'
```

**`src/pricing/vol_surface.py`** — Interpolated vol surface from calibrated model.

```python
class VolSurface:
    __init__(calibration: CalibrationResult, chain: OptionsChain)
    implied_vol(K, T) -> float
    delta(K, T, S, r) -> float
    gamma(K, T, S, r) -> float
    theta(K, T, S, r) -> float
    vega(K, T, S, r) -> float
    put_price(K, T, S, r) -> float
    richness_score(K, T) -> float
```

### 3.4 Strategy Layer

**`src/strategy/spread.py`** — Core data class for put credit spread.

```python
@dataclass
class PutCreditSpread:
    short_strike, long_strike, width, expiry, dte
    premium, max_loss, breakeven
    delta, gamma, theta, vega
    n_contracts: int = 0
    entry_date: date = None
    entry_cost: float = 0       # slippage + commission

    pnl_at_expiry(S_T: float) -> float
    current_pnl(current_mid: float) -> float
    profit_pct(current_mid: float) -> float
    update_greeks(vol_surface: VolSurface) -> None
```

**`src/strategy/entry.py`** — Three-condition AND gate.

```python
class EntryDecision:
    should_enter(regime, vrp_zscore, premium_ratio) -> EntryResult
    # EntryResult: enter, position_scale, reason, regime_prob_hv, vrp_zscore, premium_ratio
```

### 3.5 Risk Layer

**`src/risk/leverage.py`** — min-chain orchestrator. Central risk module.

```python
class LeverageChain:
    compute(portfolio_vol, portfolio_return, regime,
            current_dd, regime_age_days) -> LeverageResult
    # LeverageResult: f_vol, f_kelly, f_dd, f_final, binding_constraint, n_spreads
```

### 3.6 Execution Layer

**`src/execution/broker.py`** — IBKR wrapper.

```python
class IBKRBroker:
    __init__(mode: str)           # 'paper' or 'live' (with CONFIRM prompt)
    connect() -> bool
    disconnect() -> None
    is_connected() -> bool
    get_spx_price() -> float
    get_account_value() -> float
    get_positions() -> list[Position]
    get_option_quote(strike, expiry, right) -> OptionQuote
    place_spread_order(short_strike, long_strike, expiry, n, limit) -> Order
    close_spread(order_id, urgency) -> Order
    cancel_order(order_id) -> bool
```

### 3.7 Orchestration Layer

**`src/orchestrator/daily_pipeline.py`** — Full EOD pipeline.

```python
class DailyPipeline:
    run() -> PipelineResult
    # Steps: connect → fetch → features → calibrate → regime → monitor → exits → report
```

**`src/orchestrator/weekly_pipeline.py`** — Tuesday entry pipeline.

```python
class WeeklyPipeline:
    run() -> PipelineResult
    # Steps: pre-checks → load context → entry decision → strike → spread → size → execute
```

### 3.8 Backtest Layer

**`src/backtest/proxy_engine.py`** — Phase 1 VRP proxy simulation.

```python
class ProxyBacktestEngine:
    run(start_date, end_date, config) -> BacktestResult
    # BacktestResult: daily_pnl, equity_curve, metrics, regime_history, trades
```

**`src/backtest/options_engine.py`** — Phase 2 options chain simulation.

```python
class OptionsBacktestEngine:
    run(start_date, end_date, config) -> BacktestResult
    # Same BacktestResult structure, but with real trades
```

---

## 4. Configuration Schema

### 4.1 settings.yaml

```yaml
# ── System ──
system:
  phase: 1                        # 1, 2, 3, or 4
  stage: 1                        # Phase 4 only: 1, 2, or 3
  log_level: "INFO"

# ── Data Sources ──
data:
  spx_ticker: "^GSPC"
  fred:
    vix_series: "VIXCLS"
    vix3m_series: "VXVCLS"
    rate_series: "DGS10"
  polygon:
    base_url: "https://api.polygon.io"
    options_underlying: "SPX"
    # API key in .env: POLYGON_API_KEY
  cache:
    base_dir: "data/raw"
    format: "parquet"
    max_age_days: 90

# ── Features ──
features:
  rv_windows: [5, 21, 63]
  vrp_zscore_window: 252
  vol_acceleration_window: 5

# ── Regime Detection ──
regime:
  hmm:
    n_states: 3
    covariance_type: "full"
    n_iter: 200
    n_init: 10
    min_training_days: 504
    stability_threshold: 0.90
  xgboost:
    n_estimators: 200
    max_depth: 4
    calibration_method: "isotonic"
    max_brier_score: 0.25
  centroids:
    low_vol:
      rv_max: 0.12
      vix_max: 15
    normal_vol:
      rv_range: [0.12, 0.20]
      vix_range: [15, 25]
    high_vol:
      rv_min: 0.20
      vix_min: 25

# ── Pricing ──
pricing:
  phase1_model: "black_scholes"
  phase2_model: "heston"
  fft:
    n_points: 4096
    damping_alpha: 1.5
  heston:
    param_bounds:
      v0: [0.001, 1.0]
      kappa: [0.1, 10.0]
      theta: [0.01, 1.0]
      sigma_v: [0.1, 2.0]
      rho: [-0.95, -0.1]
    enforce_feller: true
    calibration:
      optimizer: "de_then_lm"
      de_max_iter: 200
      lm_max_iter: 100
      max_time_sec: 30
    fallback:
      max_consecutive_failures: 3   # FATAL after this many

# ── Strategy ──
strategy:
  underlying: "SPX"
  type: "put_credit_spread"
  entry:
    target_dte_min: 30
    target_dte_max: 45
    target_delta: -0.10
    spread_width: 50              # dollars
    entry_day: "tuesday"
    min_premium_ratio: 0.10
    vrp_zscore_min: -1.0
    regime_thresholds:
      full_position: 0.20         # P_HV < this
      half_position: 0.50         # P_HV < this
      skip: 0.50                  # P_HV >= this
      emergency_close: 0.80       # P_HV >= this
  exit:
    profit_target_pct: 0.75
    stop_loss_multiple: 2.0
    close_dte: 7
  strike_increments: 5            # SPX $5 strike spacing

# ── Risk Management ──
risk:
  vol_scaling:
    target_vol: 0.12
    max_leverage: 1.5
    min_leverage: 0.3
    vol_window: 20
  kelly:
    shrinkage_alpha_steady: 0.6
    shrinkage_alpha_hv_transition: 0.9
    shrinkage_alpha_other_transition: 0.75
    transition_window_days: 5
    mu_prior:
      low_vol: 0.15
      normal_vol: 0.08
      high_vol: 0.02
    rolling_window: 60
    f_min: 0.2
    f_max: 2.0
  drawdown:
    warn: 0.05
    reduce: 0.05
    kill: 0.10
  stage_overrides:                # Phase 4, Stage 1 only
    stage_1:
      target_vol: 0.08
      dd_reduce: 0.03
      dd_kill: 0.07
      kelly_f_max: 1.0
      min_premium_ratio: 0.12
      regime_skip_threshold: 0.40
      max_contracts: 3

# ── Execution ──
execution:
  mode: "paper"                   # "paper" or "live"
  ibkr:
    host: "127.0.0.1"
    paper_port: 7497
    live_port: 7496
    client_id: 1
    timeout_sec: 60
  orders:
    type: "limit"
    aggressive_after_sec: 30
    cancel_after_sec: 120
  costs:
    commission_per_contract: 0.65
    slippage_normal_pct: 0.25     # of bid-ask spread
    slippage_stress_pct: 0.50     # for HV regime exits

# ── Orchestration ──
orchestration:
  daily:
    time: "16:30"
    timezone: "US/Eastern"
    early_close_time: "13:30"
  weekly:
    time: "17:15"
    day: "tuesday"
  monthly:
    time: "18:00"
    day: 1
  xgboost_retrain_day: "friday"
  retry:
    data_fetch:
      max_retries: 3
      delay_sec: 300
    ibkr_connect:
      max_retries: 3
      delay_sec: 60
    order_execution:
      max_retries: 3
      delay_sec: 60
  misfire_grace_sec: 3600

# ── Alerts ──
alerts:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    sender: "vrp-bot@example.com"
    recipient: "you@example.com"
    # Password in .env: SMTP_PASSWORD
  escalation:
    consecutive_warn_to_critical: 3

# ── Database ──
database:
  path: "data/vrp.db"

# ── Backtest ──
backtest:
  phase1:
    start_date: "2004-01-01"
    end_date: "2025-12-31"
    initial_capital: 100000
  phase2:
    initial_capital: 100000
    # start/end determined by Polygon data availability
  cpcv:
    n_groups: 5
    k_test: 2
    embargo_days: 5
  go_nogo:
    phase1:
      min_sharpe: 0.4
      max_mdd: 0.30
      min_regime_sharpe_diff: 0.1
      max_cvar_95: -0.08
      max_worst_month: -0.15
      min_positive_months: 0.70
      max_2008_dd: 0.25
      max_2020_dd: 0.20
      min_cpcv_sharpe: 0.3
      max_pbo: 0.05
    phase2:
      min_sharpe: 0.5
      max_mdd: 0.25
      min_win_rate: 0.75
      min_win_loss_ratio: 0.3
      max_cvar_95: -0.06
      max_worst_month: -0.12
      min_stress_sharpe: 0.3
      min_phase_correlation: 0.5
      min_cal_success_rate: 0.95
      max_pbo: 0.05
```

---

## 5. Data Directory Layout

```
data/
├── README.md                     # Documents structure and conventions
│
├── raw/                          # Source data (cached from APIs)
│   ├── fred/
│   │   ├── VIXCLS.parquet       # VIX daily
│   │   ├── VXVCLS.parquet       # VIX3M daily
│   │   └── DGS10.parquet        # 10Y rate
│   ├── yfinance/
│   │   └── GSPC.parquet          # SPX OHLCV
│   ├── cboe/
│   │   └── VVIX.parquet          # VVIX daily
│   └── polygon/
│       └── options/
│           └── SPX/
│               ├── 2024-01-02.parquet
│               ├── 2024-01-03.parquet
│               └── ...           # One file per trading day
│
├── processed/
│   ├── features/
│   │   └── daily_features.parquet  # All computed features
│   ├── regime/
│   │   ├── hmm_model.pkl          # Serialized HMM
│   │   ├── xgb_model.pkl          # Serialized XGBoost
│   │   └── labels.parquet         # Historical regime labels
│   └── calibration/
│       └── heston_params.parquet  # Daily Heston parameters history
│
├── backtest/
│   └── results/
│       ├── phase1_proxy.parquet   # Phase 1 backtest results
│       └── phase2_options.parquet # Phase 2 backtest results
│
└── vrp.db                        # SQLite database
    # Tables: trades, daily_snapshots, alerts, pipeline_runs, pipeline_locks
```

---

## 6. Testing Strategy

### 6.1 Test Organization

Mirror the src/ structure:

```
tests/
├── conftest.py                   # Shared fixtures: sample data, mock objects
├── test_data/                    # Tests for src/data/*
├── test_regime/                  # Tests for src/regime/*
├── test_pricing/                 # Tests for src/pricing/*
├── test_strategy/                # Tests for src/strategy/*
├── test_risk/                    # Tests for src/risk/*
├── test_backtest/                # Tests for src/backtest/*
└── fixtures/                     # Sample data files for tests
    ├── sample_chain.json         # One day's options chain
    ├── sample_features.csv       # Feature vector examples
    └── sample_trades.json        # Trade lifecycle examples
```

### 6.2 Test Levels

**Unit tests (per function):** Every public method has at least one test. Numerical functions include exact expected values from the phase docs (e.g., Phase 1 Task 3.1: σ_p=0.06 → f_vol=1.5).

**Integration tests (per module):** Each module tested end-to-end with realistic inputs. E.g., calibrator receives a real options chain and produces a valid CalibrationResult.

**Pipeline tests:** DailyPipeline and WeeklyPipeline tested with mocked data sources and broker. Verify step ordering, failure handling, and state persistence.

### 6.3 Test Conventions

```python
# Naming: test_{module}_{method}_{scenario}
def test_vol_scaling_calm_market():
    """σ_p = 0.06, target = 0.12 → f_vol = min(2.0, 1.5) = 1.5"""
    scaler = VolScaler(target=0.12, max_lev=1.5, min_lev=0.3)
    assert scaler.compute(0.06) == 1.5

def test_vol_scaling_volatile_market():
    """σ_p = 0.24, target = 0.12 → f_vol = max(0.5, 0.3) = 0.5"""
    scaler = VolScaler(target=0.12, max_lev=1.5, min_lev=0.3)
    assert scaler.compute(0.24) == 0.5

# All numerical tests use exact values from phase docs
# Tolerance: assert abs(result - expected) < 1e-6 for floats
```

---

## 7. Environment & Dependencies

### 7.1 Python Version

Python 3.11+ (same as soccer project).

### 7.2 requirements.txt

```
# Core
pandas>=2.0
numpy>=1.24
scipy>=1.10

# Data sources
fredapi>=0.5
yfinance>=0.2
polygon-api-client>=1.12

# Regime detection
hmmlearn>=0.3
xgboost>=2.0
scikit-learn>=1.3

# Execution
ib_insync>=0.9

# Orchestration
APScheduler>=3.10

# Config & logging
pyyaml>=6.0
python-dotenv>=1.0
loguru>=0.7

# Testing
pytest>=7.0
pytest-cov>=4.0

# Notebooks
jupyter>=1.0
matplotlib>=3.7
seaborn>=0.12
```

### 7.3 Environment Variables (.env)

```bash
# .env (never committed to git)
FRED_API_KEY=your_fred_key
POLYGON_API_KEY=your_polygon_key        # Phase 2+
SMTP_PASSWORD=your_email_password       # Phase 3+
```

### 7.4 .gitignore

```
# Data
data/raw/
data/processed/
data/backtest/
data/vrp.db

# Logs
logs/

# Environment
.env
*.yaml          # Only credentials.yaml — settings.yaml IS committed
!config/settings.yaml
!config/holidays.yaml

# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# IDE
.vscode/
.idea/

# Notebooks
.ipynb_checkpoints/
```
