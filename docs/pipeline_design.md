# Pipeline Design — VRP Production System

**Regime-Conditioned Systematic Short Volatility | SPX Options | Python**

> Translates `mathematical_design_production.md` into code architecture.
> Defines data sources, module responsibilities, data flow, orchestration, and config schema.
> All mathematical definitions and parameter values reference the mathematical design doc.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Layer](#2-data-layer)
3. [Layer 1: Regime Detection Module](#3-layer-1-regime-detection)
4. [Layer 2: Options Pricing Module](#4-layer-2-options-pricing)
5. [Layer 3: Strategy Engine Module](#5-layer-3-strategy-engine)
6. [Layer 4: Risk Management Module](#6-layer-4-risk-management)
7. [Layer 5: Execution Module](#7-layer-5-execution)
8. [Orchestration & Scheduling](#8-orchestration--scheduling)
9. [Monitoring & Alerts](#9-monitoring--alerts)
10. [Tech Stack](#10-tech-stack)
11. [Design Decision Log](#11-design-decision-log)

---

## 1. Architecture Overview

### 1.1 System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Data Layer                           │
│                                                             │
│  FRED/CBOE (free)          Polygon.io ($29/mo)    IBKR API │
│  ├─ VIX, VIX3M, VVIX      ├─ SPX options chain   ├─ Orders│
│  ├─ SPX daily OHLCV        ├─ Historical snapshots ├─ Fills│
│  └─ Risk-free rate         └─ EOD chain (Phase 2)  └─ Acct │
│                                                             │
│  DataFetcher(ABC) → FREDFetcher, PolygonFetcher, IBKRFeed  │
│  Cache: source-tagged parquet in data/raw/{source}/         │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Regime Detection ────────────┴────────────────────────────┐
│  Input: RV(5,21,63), VIX, TS, VVIX, ΔVol                   │
│  HMM (offline labeling) → XGBoost (real-time inference)     │
│  Output: p = [P_LV, P_NV, P_HV]                            │
│  Module: src/regime/                                        │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Options Pricing ─────────────┴────────────────────────────┐
│  Phase 1: BS closed-form (VIX proxy)                        │
│  Phase 2+: Heston calibration → Carr-Madan FFT             │
│  Output: vol surface, Greeks, richness score                │
│  Module: src/pricing/                                       │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Strategy Engine ─────────────┴────────────────────────────┐
│  Input: regime probs, VRP signal, vol surface               │
│  Entry decision → strike selection → spread construction    │
│  Output: target position (or no-trade)                      │
│  Module: src/strategy/                                      │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Risk Management ─────────────┴────────────────────────────┐
│  Vol scaling → Kelly ceiling → DD override                  │
│  min-chain combination                                      │
│  Output: f_final (leverage factor), N_spreads               │
│  Module: src/risk/                                          │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Execution ───────────────────┴────────────────────────────┐
│  Greeks-based sizing → IBKR order placement                 │
│  Fill tracking → slippage logging                           │
│  Module: src/execution/                                     │
└────────────────────────────────┬────────────────────────────┘
                                 │
┌── Orchestration & Monitoring ──┴────────────────────────────┐
│  Scheduler (APScheduler) → daily/weekly/monthly tasks       │
│  Alert system (email/SMS) → critical events                 │
│  Daily report → automated email summary                     │
│  Module: src/orchestrator/, alerts/                          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Core Design Principles

**1. Phased Data Sources.** Phase 1 uses free data only (FRED/CBOE). Phase 2+ adds Polygon.io. IBKR is execution-only until live trading. Each source has a dedicated fetcher behind `DataFetcher(ABC)`.

**2. Strict Layer Boundaries.** Each module receives typed inputs and produces typed outputs. No module reaches into another module's internals. All inter-module communication goes through defined interfaces (see `contracts.md`).

**3. Fail-Safe Orchestration.** Every step has a defined fallback. Calibration failure → previous parameters. Data fetch failure → cache. Execution failure → hold, alert. The system never enters an undefined state.

**4. Config-Driven.** All parameters, thresholds, and schedules live in `config/settings.yaml`. No magic numbers in code. Every parameter traces back to `mathematical_design_production.md`.

---

## 2. Data Layer

### 2.1 Data Sources

| Source | Data | Phase | Cost | Update Frequency |
|--------|------|-------|------|-----------------|
| FRED | VIX, VIX3M, risk-free rate (DGS10) | 1+ | Free | Daily EOD |
| CBOE | VVIX, VIX term structure | 1+ | Free | Daily EOD |
| Yahoo Finance | SPX daily OHLCV (^GSPC) | 1+ | Free | Daily EOD |
| Polygon.io | SPX/SPY options chain snapshots | 2+ | $29/mo | Daily EOD |
| IBKR TWS API | Real-time quotes, order execution, account | Live | Commissions only | Real-time |

**Data Boundary Rule:** IBKR data is used for order execution only. Never for signals, regime detection, or backtesting. This mirrors the soccer project's Tiingo/Alpaca separation.

### 2.2 DataFetcher Abstraction

```python
class DataFetcher(ABC):
    @abstractmethod
    def fetch_spx_ohlcv(self, start: date, end: date) -> pd.DataFrame: ...

    @abstractmethod
    def fetch_vix(self, start: date, end: date) -> pd.Series: ...

    @abstractmethod
    def fetch_vix3m(self, start: date, end: date) -> pd.Series: ...

    @abstractmethod
    def fetch_vvix(self, start: date, end: date) -> pd.Series: ...

    @abstractmethod
    def fetch_risk_free_rate(self, start: date, end: date) -> pd.Series: ...

class FREDFetcher(DataFetcher): ...      # VIX, VIX3M, VVIX, DGS10
class YFinanceFetcher(DataFetcher): ...   # SPX OHLCV (^GSPC)
class PolygonFetcher:                     # Options chain (separate interface)
    def fetch_options_chain(self, underlying: str, date: date) -> OptionsChain: ...
```

### 2.3 Options Chain Data Model

```python
@dataclass
class OptionQuote:
    strike: float
    expiry: date
    option_type: str          # 'put' or 'call'
    bid: float
    ask: float
    mid: float
    implied_vol: float
    delta: float
    gamma: float
    theta: float
    vega: float
    volume: int
    open_interest: int

@dataclass
class OptionsChain:
    underlying_price: float
    trade_date: date
    quotes: list[OptionQuote]
    risk_free_rate: float
```

### 2.4 Cache Strategy

```
data/
├── raw/
│   ├── fred/                 # VIX, VIX3M, VVIX, rates (parquet)
│   ├── yfinance/             # SPX OHLCV (parquet)
│   └── polygon/              # Options chain snapshots (parquet)
├── processed/
│   ├── features/             # RV, TS, ΔVol computed features
│   ├── regime/               # HMM labels, XGBoost predictions
│   └── calibration/          # Heston parameters history
└── backtest/
    └── results/              # Backtest P&L, metrics
```

- Source-tagged: each source has its own subdirectory
- Incremental: only fetch missing dates
- Parquet format: columnar, fast reads, type-safe
- Cache invalidation: manual only (no auto-expiry)

### 2.5 Feature Computation

`src/data/features.py` — computes derived features from raw data:

| Feature | Formula | Input |
|---------|---------|-------|
| RV(τ) | $\sqrt{252/\tau \cdot \sum r_{t-i}^2}$ | SPX close |
| VRP proxy | $\text{VIX}^2/252 - \text{RV}(21)^2/252$ | VIX, SPX |
| z_VRP | $(VRP - \mu_{252}) / \sigma_{252}$ | VRP history |
| Term structure | $\text{VIX3M}/\text{VIX} - 1$ | VIX, VIX3M |
| ΔVol(5) | $(\text{RV}(5) - \text{RV}(21)) / \text{RV}(21)$ | SPX close |

All features use **point-in-time** computation only. No future information leakage.

---

## 3. Layer 1: Regime Detection

### 3.1 Module Structure

```
src/regime/
├── __init__.py
├── hmm.py                # RegimeHMM: 3-state Gaussian HMM
├── features.py           # Regime feature engineering
├── xgboost_clf.py        # RegimeXGBoost: calibrated classifier
├── calibration.py        # Brier score, reliability diagram
└── detector.py           # RegimeDetector: orchestrates HMM + XGBoost
```

### 3.2 RegimeHMM

```python
class RegimeHMM:
    def fit(self, features: pd.DataFrame) -> None:
        """Expanding window fit with centroid-anchored labeling.
        n_init=10, n_iter=200, full covariance."""

    def get_filtered_probs(self, features: pd.DataFrame) -> np.ndarray:
        """Returns FILTERED probabilities only (not smoothed).
        Uses _do_forward_pass() internally, NOT predict_proba().
        Shape: (T, 3) — [P_LV, P_NV, P_HV] per timestep."""

    def get_labels(self) -> np.ndarray:
        """Centroid-anchored state labels for training XGBoost."""

    def check_stability(self, old_labels: np.ndarray) -> float:
        """Returns overlap agreement ratio. Must be >= 0.90."""
```

**Implementation Note:** `hmmlearn`'s `predict_proba()` returns smoothed posteriors. Must extract forward variables via `_do_forward_pass()` and normalize: $P(s_t|x_{1:t}) = \alpha_t(k) / \sum_k \alpha_t(k)$.

### 3.3 RegimeDetector

```python
class RegimeDetector:
    def __init__(self, hmm: RegimeHMM, xgb: RegimeXGBoost): ...

    def predict(self, features: pd.DataFrame) -> RegimePrediction:
        """Real-time regime prediction via XGBoost.
        Returns calibrated probability vector."""

    def retrain_xgboost(self, features: pd.DataFrame, labels: np.ndarray) -> float:
        """Weekly retraining. Returns Brier score. Must be < 0.25."""

    def refit_hmm(self, features: pd.DataFrame) -> bool:
        """Monthly refit. Returns True if labels stable (>= 90%)."""

@dataclass
class RegimePrediction:
    probabilities: np.ndarray   # [P_LV, P_NV, P_HV]
    regime: str                 # 'low_vol', 'normal_vol', 'high_vol'
    confidence: float           # max probability
    timestamp: datetime
```

---

## 4. Layer 2: Options Pricing

### 4.1 Module Structure

```
src/pricing/
├── __init__.py
├── black_scholes.py      # BS closed-form: price, Greeks, implied vol
├── heston.py             # Heston model: characteristic function
├── fft_pricer.py         # Carr-Madan FFT pricing engine
├── calibrator.py         # Heston calibration (DE → LM)
├── vol_surface.py        # VolSurface: interpolated surface object
└── greeks.py             # Greeks computation for spreads
```

### 4.2 Phase 1: BS Pricing

```python
class BSPricer:
    def put_price(self, S, K, T, r, sigma) -> float: ...
    def put_delta(self, S, K, T, r, sigma) -> float: ...
    def put_gamma(self, S, K, T, r, sigma) -> float: ...
    def put_theta(self, S, K, T, r, sigma) -> float: ...
    def put_vega(self, S, K, T, r, sigma) -> float: ...
    def implied_vol(self, market_price, S, K, T, r, option_type) -> float: ...
    def find_strike_by_delta(self, S, T, r, sigma, target_delta) -> float:
        """Newton-Raphson to find K where delta = target_delta."""
```

### 4.3 Phase 2+: Heston + FFT

```python
class HestonModel:
    def __init__(self, v0, kappa, theta, sigma_v, rho): ...

    def characteristic_function(self, xi, T, r, S0) -> complex: ...

    def check_feller(self) -> bool:
        """Returns True if 2*kappa*theta > sigma_v^2."""

class FFTPricer:
    def __init__(self, model: HestonModel, N=4096, alpha=1.5): ...

    def price_all_strikes(self, S, T, r, strikes) -> np.ndarray:
        """Carr-Madan FFT. Returns prices for all strikes in one pass."""

class HestonCalibrator:
    def calibrate(self, chain: OptionsChain) -> CalibrationResult:
        """DE global → LM local. Enforces Feller condition.
        Returns calibrated HestonModel + diagnostics."""

@dataclass
class CalibrationResult:
    model: HestonModel
    rmse: float
    status: str               # 'success', 'de_only', 'fallback_prev', 'fallback_bs'
    params: dict
    timestamp: datetime
```

**Fallback Chain:**
1. DE + LM succeeds → use result
2. LM fails → use DE-only result, log WARNING
3. DE fails (RMSE > bid-ask) → use previous day's parameters, log WARNING
4. 2+ consecutive failures → fall back to BS, log CRITICAL

### 4.4 VolSurface

```python
class VolSurface:
    def __init__(self, calibration: CalibrationResult, chain: OptionsChain): ...

    def implied_vol(self, K, T) -> float:
        """Interpolated implied vol at any (strike, maturity)."""

    def delta(self, K, T, S, r) -> float: ...
    def gamma(self, K, T, S, r) -> float: ...
    def theta(self, K, T, S, r) -> float: ...
    def vega(self, K, T, S, r) -> float: ...

    def richness_score(self, K, T) -> float:
        """market_price - model_price. Positive = market is rich."""
```

---

## 5. Layer 3: Strategy Engine

### 5.1 Module Structure

```
src/strategy/
├── __init__.py
├── vrp_signal.py         # VRP measurement and z-score
├── entry.py              # Entry decision logic (3-condition AND)
├── strike_selector.py    # 10-delta strike selection
├── spread.py             # PutCreditSpread construction and P&L
└── position_manager.py   # Open position monitoring, exit triggers
```

### 5.2 Entry Decision

```python
class EntryDecision:
    def should_enter(self,
                     regime: RegimePrediction,
                     vrp_zscore: float,
                     premium_ratio: float) -> EntryResult:
        """Three-condition AND gate.
        1. regime.probabilities[HV] < threshold (regime-dependent sizing)
        2. vrp_zscore > z_min (-1.0)
        3. premium_ratio > min_ratio (0.10)
        """

@dataclass
class EntryResult:
    enter: bool
    position_scale: float     # 1.0 (full), 0.5 (half), 0.0 (skip)
    reason: str               # Human-readable explanation
    regime_prob_hv: float
    vrp_zscore: float
    premium_ratio: float
```

### 5.3 PutCreditSpread

```python
@dataclass
class PutCreditSpread:
    short_strike: float       # K1 (10-delta)
    long_strike: float        # K2 = K1 - W
    width: float              # W ($50 or $100)
    expiry: date
    dte: int
    premium: float            # Net credit received (per share)
    max_loss: float           # W - premium (per share)
    breakeven: float          # K1 - premium

    # Greeks (of the spread)
    delta: float
    gamma: float
    theta: float
    vega: float

    def pnl_at_expiry(self, S_T: float) -> float:
        """Exact P&L given underlying price at expiry."""

    def current_pnl(self, current_mid: float) -> float:
        """Mark-to-market P&L."""

    def profit_pct(self, current_mid: float) -> float:
        """Current P&L as % of max profit (premium)."""
```

### 5.4 Position Manager

```python
class PositionManager:
    def check_exit_triggers(self, spread: PutCreditSpread,
                            regime: RegimePrediction) -> ExitSignal:
        """Checks all exit conditions:
        1. DTE <= 7 (gamma risk)
        2. profit >= 75% of premium
        3. loss >= 2x premium (stop loss)
        4. P_HV > 0.8 (regime emergency)
        """

@dataclass
class ExitSignal:
    should_exit: bool
    reason: str               # 'profit_target', 'stop_loss', 'dte', 'regime_emergency'
    urgency: str              # 'normal', 'urgent'
```

---

## 6. Layer 4: Risk Management

### 6.1 Module Structure

```
src/risk/
├── __init__.py
├── vol_scaling.py        # Volatility targeting
├── kelly_ceiling.py      # Portfolio Kelly with adaptive prior
├── drawdown.py           # DD monitoring and override
├── leverage.py           # min-chain orchestrator
└── kill_switch.py        # Emergency full liquidation
```

### 6.2 Leverage Chain

```python
class LeverageChain:
    def __init__(self, vol_scaler, kelly, drawdown): ...

    def compute(self,
                portfolio_vol: float,
                portfolio_return: float,
                regime: RegimePrediction,
                current_dd: float,
                regime_age_days: int) -> LeverageResult:
        """
        f_vol = clip(σ_target / σ_portfolio, 0.3, 1.5)
        f_kelly = clip(μ_hat / σ_hat², 0.2, 2.0)
          where μ_hat uses adaptive α based on regime transition
        f_dd = drawdown_override(current_dd)
        f_final = min(f_vol, f_kelly, f_dd)
        """

@dataclass
class LeverageResult:
    f_vol: float
    f_kelly: float
    f_dd: float
    f_final: float            # min(f_vol, f_kelly, f_dd)
    binding_constraint: str   # which stage is the min
    n_spreads: int            # floor(account * f_final / max_loss)
```

### 6.3 Kelly Adaptive Weighting

```python
class KellyCeiling:
    def compute(self, regime: RegimePrediction,
                rolling_return_60d: float,
                rolling_vol_60d: float,
                regime_age_days: int) -> float:
        """
        α = 0.9  if regime is HV and age < 5 days (emergency)
        α = 0.75 if regime changed (non-HV) and age < 5 days
        α = 0.6  if regime stable >= 5 days
        μ_hat = α * μ_prior(regime) + (1-α) * rolling_return_60d
        f_kelly = clip(μ_hat / rolling_vol_60d², 0.2, 2.0)
        """
```

---

## 7. Layer 5: Execution

### 7.1 Module Structure

```
src/execution/
├── __init__.py
├── broker.py             # IBKRBroker: API wrapper via ib_insync
├── order_manager.py      # Order construction, submission, monitoring
├── fill_tracker.py       # Fill tracking, slippage calculation
└── paper_trader.py       # Simulated execution for paper trading
```

### 7.2 IBKRBroker

```python
class IBKRBroker:
    def __init__(self, mode: str):  # 'paper' or 'live'
        """Connects via ib_insync. Paper: port 7497. Live: port 7496."""

    def place_spread_order(self, spread: PutCreditSpread,
                           n_contracts: int,
                           order_type: str = 'limit') -> OrderResult: ...

    def close_spread(self, spread: PutCreditSpread,
                     urgency: str = 'normal') -> OrderResult:
        """normal: limit at mid. urgent: market order."""

    def get_account_value(self) -> float: ...
    def get_positions(self) -> list[Position]: ...
```

### 7.3 Paper Trading

```python
class PaperTrader:
    """Simulates execution without IBKR connection.
    Uses Polygon.io EOD data for realistic fills.
    Applies slippage model: 25% normal, 50% stress."""

    def simulate_fill(self, spread: PutCreditSpread,
                      chain: OptionsChain,
                      regime: str) -> SimulatedFill: ...
```

---

## 8. Orchestration & Scheduling

### 8.1 Module Structure

```
src/orchestrator/
├── __init__.py
├── scheduler.py          # APScheduler job definitions
├── daily_pipeline.py     # EOD pipeline: data → regime → pricing → monitor
├── weekly_pipeline.py    # Entry decision → execution
├── monthly_pipeline.py   # HMM refit, housekeeping
└── failure_handler.py    # Retry logic, fallback, escalation
```

### 8.2 Schedule

| Frequency | Time (ET) | Task | Depends On |
|-----------|-----------|------|-----------|
| **Daily** | 16:30 | Fetch EOD data (SPX, VIX, VIX3M, VVIX) | Market close |
| | 16:35 | Compute features (RV, TS, ΔVol, z_VRP) | Data fetch |
| | 16:40 | Heston calibration (Phase 2+) | Features + options chain |
| | 16:45 | Regime detection (XGBoost predict) | Features |
| | 16:50 | Position monitoring: Greeks update, exit triggers | Regime + pricing |
| | 16:55 | Execute exits (if triggered) | Position monitoring |
| | 17:00 | Generate daily report email | All above |
| **Weekly** (Tue) | 17:15 | Entry decision | Regime + VRP + pricing |
| | 17:20 | Strike selection + spread construction | Entry decision |
| | 17:25 | Risk sizing (min-chain) | Strategy + risk |
| | 17:30 | Order execution via IBKR | Risk sizing |
| | 17:45 | XGBoost retraining | Regime labels |
| **Monthly** (1st) | 18:00 | HMM refit + stability check | Feature history |
| | 18:15 | Cache cleanup, data integrity check | — |

**Why Tuesday for weekly entry:** Avoid Monday (weekend gap risk, stale data) and Friday (short week for new positions, gamma acceleration). Tuesday gives full data from Monday's session and leaves room for the position to develop.

### 8.3 Dependency Chain

```
Data Fetch ──→ Features ──→ Regime Detection ──→ Position Monitor ──→ Exits
                  │                │
                  ▼                ▼
          Heston Calibration   Entry Decision ──→ Strike Selection
                  │                                      │
                  ▼                                      ▼
            Vol Surface ─────────────────────→ Risk Sizing ──→ Execution
```

Each step must complete before downstream steps begin. If a step fails:

### 8.4 Failure Handling

| Step | Failure Mode | Retry | Fallback | Alert |
|------|-------------|-------|----------|-------|
| Data fetch (SPX) | API timeout | 3x, 5min interval | Cache (prev day) | WARNING |
| Data fetch (VIX) | API error | 3x, 5min interval | Cache (prev day) | WARNING |
| Data fetch (options) | Polygon down | 3x, 10min interval | Skip pricing update | WARNING |
| Feature computation | NaN values | No retry | Forward-fill, log | WARNING |
| Heston calibration | Non-convergence | 1x with wider bounds | Prev day params → BS | WARNING → CRITICAL |
| Regime detection | XGBoost error | No retry | Prev day regime | WARNING |
| Position monitoring | No data | — | Hold all positions | CRITICAL |
| Order execution | IBKR disconnected | 3x, 1min interval | Hold, no new trades | CRITICAL |
| Order execution | Rejected | 1x with adjusted price | Cancel, log | WARNING |

**Critical Rule:** If data fetch AND cache both fail for SPX or VIX, the entire pipeline halts. No decisions are made on stale data older than 1 trading day.

### 8.5 Daily Pipeline Implementation

```python
class DailyPipeline:
    def run(self) -> PipelineResult:
        """
        Sequential execution with failure handling at each step.
        Returns detailed result with status per step.
        """
        # Step 1: Data
        data = self._fetch_data()          # retry + cache fallback
        if data.status == 'CRITICAL_FAIL':
            return self._abort("Data unavailable")

        # Step 2: Features
        features = self._compute_features(data)

        # Step 3: Pricing (Phase 2+)
        pricing = self._calibrate_and_price(data, features)

        # Step 4: Regime
        regime = self._detect_regime(features)

        # Step 5: Position monitoring
        exits = self._monitor_positions(regime, pricing)

        # Step 6: Execute exits
        if exits.any_triggered:
            self._execute_exits(exits)

        # Step 7: Daily report
        self._send_daily_report(data, features, regime, pricing, exits)

        return PipelineResult(status='OK', steps={...})
```

---

## 9. Monitoring & Alerts

### 9.1 Tier Structure

| Tier | Mechanism | Purpose | Frequency |
|------|-----------|---------|-----------|
| **Tier 1: Alerts** | Email + SMS | Critical events, act immediately | Event-driven |
| **Tier 2: Daily Report** | Automated email | Health check, no action needed | Daily 17:00 ET |
| **Tier 3: Deep Analysis** | Jupyter notebooks | Performance review, research | Weekly/monthly |

### 9.2 Alert System

```
alerts/
├── __init__.py
├── manager.py            # Alert routing by severity
├── email_sender.py       # SMTP email dispatch
└── sms_sender.py         # Twilio SMS for CRITICAL (optional)
```

**Alert Levels:**

| Level | Trigger | Channel | Example |
|-------|---------|---------|---------|
| INFO | Normal operations | DB log only | "Daily pipeline completed OK" |
| WARNING | Degraded but functional | Email | "Heston calibration used DE-only" |
| CRITICAL | Requires attention | Email + SMS | "DD > 5%", "Calibration failed 2d" |
| EMERGENCY | Immediate action | Email + SMS + kill switch | "DD > 10%", "IBKR disconnected during exit" |

### 9.3 Daily Report Format

```
=== VRP Daily Report (2026-03-12 17:00 ET) ===

[REGIME]
  Current: Normal-Vol (P_LV: 0.35, P_NV: 0.53, P_HV: 0.12)
  Changed: No (stable 14 days)

[VRP]
  VIX: 16.2 | RV(21): 13.8 | VRP proxy: 0.42
  z-score: 0.8 (above average)
  Term structure: +0.12 (contango, normal)

[POSITION]
  Status: 12 spreads open
  Short: SPX 5200P | Long: SPX 5100P | Exp: 2026-04-10
  DTE: 29 | Premium: $7.20 | Current mid: $2.80
  P&L: +$4.40/spread (+61% of max profit)
  Greeks: Δ -0.03 | Γ -0.001 | Θ +$12/day | V -$45/1%

[RISK]
  Drawdown: 2.1% (OK, threshold: 5%)
  f_vol: 0.92 | f_kelly: 1.1 | f_dd: 1.0
  f_final: 0.92 (binding: vol_scaling)

[PRICING] (Phase 2+)
  Heston calibration: OK (RMSE: 0.003)
  Params: v0=0.024 κ=2.1 θ=0.035 σv=0.42 ρ=-0.72

[PIPELINE]
  All steps: OK
  Data: OK | Features: OK | Regime: OK | Pricing: OK | Monitor: OK
  Next entry day: Tuesday 2026-03-17

[ACTION REQUIRED]
  None. System operating normally.
```

### 9.4 Jupyter Notebooks

```
notebooks/
├── 01_data_exploration.ipynb      # Raw data quality, VRP distribution
├── 02_regime_analysis.ipynb       # HMM states, centroid stability, Brier score
├── 03_backtest_results.ipynb      # Phase 1 proxy, Phase 2 options chain
├── 04_live_monitoring.ipynb       # Equity curve, regime history, DD gauge
└── 05_performance_review.ipynb    # Weekly/monthly: backtest vs live, attribution
```

Used for deep analysis only. Not part of daily operations.

---

## 10. Tech Stack

| Component | Library / Service | Notes |
|-----------|-------------------|-------|
| **Data** | | |
| SPX OHLCV | `yfinance` | ^GSPC, free |
| VIX/VIX3M/VVIX/rates | `fredapi` | FRED API, free |
| Options chain | `polygon-api-client` | $29/mo, Phase 2+ |
| **Regime** | | |
| HMM | `hmmlearn` | Custom filtered prob extraction |
| XGBoost | `xgboost` + `scikit-learn` | CalibratedClassifierCV |
| **Pricing** | | |
| FFT | `numpy.fft` | Carr-Madan implementation |
| Optimization | `scipy.optimize` | DE + LM for Heston calibration |
| BS formulas | Custom | `scipy.stats.norm` for N(d) |
| **Execution** | | |
| IBKR API | `ib_insync` | Wrapper over TWS API |
| **Risk** | | |
| All risk modules | Custom | `numpy`, `pandas` |
| **Orchestration** | | |
| Scheduler | `APScheduler` | Cron-like job scheduling |
| **Monitoring** | | |
| Email | `smtplib` | SMTP for alerts + daily report |
| SMS (optional) | `twilio` | CRITICAL/EMERGENCY only |
| DB | `SQLite` | Trade log, alert history, metrics |
| Analysis | `jupyter`, `matplotlib` | Deep analysis notebooks |
| **Core** | | |
| Language | Python 3.11+ | |
| Data | `pandas`, `numpy`, `scipy` | |
| Config | `pyyaml`, `python-dotenv` | |
| Logging | `loguru` | |
| Testing | `pytest` | |

---

## 11. Design Decision Log

| # | Decision | Alternatives Considered | Rationale |
|---|----------|------------------------|-----------|
| 1 | FRED + Yahoo for free data | Tiingo, Alpha Vantage | FRED has official VIX/VVIX. Yahoo reliable for SPX index. No API key needed for Yahoo. |
| 2 | Polygon.io for options | CBOE DataShop, OptionsDX | Best cost/quality ratio at $29/mo. REST API. Historical snapshots available. |
| 3 | IBKR for execution | Tastytrade, Alpaca | SPX options standard. Paper trading built-in. ib_insync simplifies API. Section 1256 tax. |
| 4 | APScheduler over cron | Linux cron, Celery | In-process, Python-native, job dependency support. Simpler than Celery for single-machine. |
| 5 | SQLite over PostgreSQL | PostgreSQL, TimescaleDB | Single-user system. No concurrent writes. File-based, zero config. Sufficient for trade log + metrics. |
| 6 | Email + SMS over dashboard | Web dashboard, Telegram bot | Lowest implementation cost. Push-based (no need to check). Dashboard deferred to post-validation. |
| 7 | Phased data sources | All sources from day 1 | Phase 1 validates strategy skeleton at $0 cost before committing to Polygon.io subscription. |
| 8 | ib_insync over raw TWS | Raw TWS API, ibapi | ib_insync provides Pythonic async wrapper. Dramatically reduces boilerplate. Well-maintained. |
| 9 | Parquet cache | CSV, HDF5, database | Columnar, type-safe, fast. Better than CSV for typed data. Simpler than database for file-based cache. |
| 10 | Tuesday weekly entry | Monday, Wednesday, Friday | Avoids Monday gap risk and Friday gamma. Full data from Monday session. Standard industry practice. |
