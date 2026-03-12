# Module Interface Contracts

**Type signatures, input/output specifications, and error handling rules for all inter-module boundaries.**

> Every public function that crosses a module boundary is defined here.
> Claude Code must match these signatures exactly.
> If a contract needs to change, update this document FIRST, then update the code.
> Internal (private) functions within a module are not covered — only the public API.

---

## Table of Contents

1. [Contract Conventions](#1-contract-conventions)
2. [Shared Types](#2-shared-types)
3. [Data Layer Contracts](#3-data-layer)
4. [Regime Layer Contracts](#4-regime-layer)
5. [Pricing Layer Contracts](#5-pricing-layer)
6. [Strategy Layer Contracts](#6-strategy-layer)
7. [Risk Layer Contracts](#7-risk-layer)
8. [Execution Layer Contracts](#8-execution-layer)
9. [Backtest Layer Contracts](#9-backtest-layer)
10. [Orchestrator Contracts](#10-orchestrator)
11. [Alert Contracts](#11-alerts)

---

## 1. Contract Conventions

### 1.1 Rules

- All public methods have type hints on all parameters and return types.
- All public methods have a docstring describing purpose, parameters, return value, and exceptions.
- No method returns `None` silently on failure — either raise an exception or return a result object with a status field.
- Dataclasses are immutable where possible (`frozen=True`). Mutable state is explicit.
- All date/datetime parameters use `datetime.date` or `datetime.datetime`, never strings.
- All prices are in dollars (float). All volatilities are decimal (0.15 = 15%). All probabilities are decimal [0, 1].

### 1.2 Error Types

```python
# src/exceptions.py — all custom exceptions

class VRPError(Exception):
    """Base exception for VRP system."""

class DataFetchError(VRPError):
    """Failed to fetch data from external source."""

class DataValidationError(VRPError):
    """Fetched data failed quality checks."""

class CacheError(VRPError):
    """Cache read/write failure."""

class CalibrationError(VRPError):
    """Heston calibration failed."""

class RegimeError(VRPError):
    """Regime detection failure."""

class StrikeSelectionError(VRPError):
    """Could not find valid strike (Newton-Raphson non-convergence)."""

class ExecutionError(VRPError):
    """Order placement or fill failure."""

class PipelineError(VRPError):
    """Pipeline step failure."""
```

---

## 2. Shared Types

```python
# src/data/models.py

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
import numpy as np

@dataclass(frozen=True)
class OptionQuote:
    strike: float
    expiry: date
    option_type: str              # 'put' or 'call'
    bid: float
    ask: float
    mid: float                    # (bid + ask) / 2
    implied_vol: float            # decimal (0.20 = 20%)
    delta: Optional[float]        # [-1, 0] for puts
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    volume: int
    open_interest: Optional[int]

@dataclass(frozen=True)
class OptionsChain:
    underlying_price: float
    trade_date: date
    quotes: tuple[OptionQuote, ...]   # immutable tuple, not list
    risk_free_rate: float

    def puts(self) -> tuple[OptionQuote, ...]:
        """Filter to put options only."""

    def get_by_strike_expiry(self, strike: float, expiry: date,
                              option_type: str = 'put') -> Optional[OptionQuote]:
        """Lookup a specific contract. Returns None if not found."""

@dataclass(frozen=True)
class MarketData:
    trade_date: date
    spx_close: float
    vix: float
    vix3m: Optional[float]        # None before 2007-12
    vvix: Optional[float]         # None before 2007-01
    risk_free_rate: float

@dataclass(frozen=True)
class RegimePrediction:
    probabilities: np.ndarray     # shape (3,): [P_LV, P_NV, P_HV]
    regime: str                   # 'low_vol', 'normal_vol', 'high_vol'
    confidence: float             # max(probabilities)
    timestamp: datetime

    @property
    def p_low_vol(self) -> float:
        return float(self.probabilities[0])

    @property
    def p_normal_vol(self) -> float:
        return float(self.probabilities[1])

    @property
    def p_high_vol(self) -> float:
        return float(self.probabilities[2])

@dataclass(frozen=True)
class CalibrationResult:
    v0: float
    kappa: float
    theta: float
    sigma_v: float
    rho: float
    rmse: float
    status: str                   # 'success', 'de_only', 'fallback_prev', 'fallback_bs'
    calibration_date: date
    feller_satisfied: bool

@dataclass
class PutCreditSpread:
    short_strike: float
    long_strike: float
    width: float                  # short_strike - long_strike
    expiry: date
    dte: int
    premium: float                # net credit per share
    max_loss: float               # width - premium per share
    breakeven: float              # short_strike - premium
    delta: float
    gamma: float
    theta: float
    vega: float
    n_contracts: int = 0
    entry_date: Optional[date] = None
    entry_cost: float = 0.0       # total slippage + commission

@dataclass(frozen=True)
class EntryResult:
    enter: bool
    position_scale: float         # 1.0, 0.5, or 0.0
    reason: str
    regime_prob_hv: float
    vrp_zscore: float
    premium_ratio: float

@dataclass(frozen=True)
class ExitSignal:
    should_exit: bool
    reason: str                   # 'profit_target', 'stop_loss', 'dte', 'regime_emergency', 'none'
    urgency: str                  # 'normal', 'urgent'

@dataclass(frozen=True)
class LeverageResult:
    f_vol: float
    f_kelly: float
    f_dd: float
    f_final: float                # min(f_vol, f_kelly, f_dd)
    binding_constraint: str       # 'vol', 'kelly', 'dd'
    n_spreads: int

@dataclass(frozen=True)
class BacktestResult:
    daily_returns: pd.Series
    equity_curve: pd.Series
    trades: list[dict]
    metrics: dict                 # {sharpe, mdd, cvar_95, worst_month, win_rate, ...}
    regime_history: pd.DataFrame
    leverage_history: pd.DataFrame

@dataclass(frozen=True)
class PipelineResult:
    status: str                   # 'OK', 'SKIPPED', 'DEGRADED', 'FAILED', 'CRASH'
    reason: Optional[str] = None
    step_results: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
```

---

## 3. Data Layer

### 3.1 DataFetcher

```python
# src/data/fetcher.py

class DataFetcher(ABC):
    """Abstract base for market data fetchers."""

    @abstractmethod
    def fetch_spx_ohlcv(self, start: date, end: date) -> pd.DataFrame:
        """Fetch S&P 500 OHLCV data.

        Returns:
            DataFrame with columns: [Open, High, Low, Close, Volume]
            Index: DatetimeIndex (trading days only)

        Raises:
            DataFetchError: API unavailable after retries.
        """

    @abstractmethod
    def fetch_vix(self, start: date, end: date) -> pd.Series:
        """Fetch VIX closing values.

        Returns:
            Series with DatetimeIndex, values in index points (e.g., 16.5)

        Raises:
            DataFetchError: API unavailable.
        """

    @abstractmethod
    def fetch_vix3m(self, start: date, end: date) -> pd.Series:
        """Fetch VIX3M (3-month VIX) closing values.

        Returns:
            Series. May contain NaN for dates before 2007-12.
        """

    @abstractmethod
    def fetch_vvix(self, start: date, end: date) -> pd.Series:
        """Fetch VVIX (VIX of VIX) closing values.

        Returns:
            Series. May contain NaN for dates before 2007-01.
        """

    @abstractmethod
    def fetch_risk_free_rate(self, start: date, end: date) -> pd.Series:
        """Fetch 10-year Treasury yield as risk-free rate proxy.

        Returns:
            Series with values in decimal (0.04 = 4%).
        """
```

### 3.2 PolygonFetcher

```python
# src/data/polygon_fetcher.py

class PolygonFetcher:
    """Fetches SPX options chain data from Polygon.io."""

    def __init__(self, api_key: str, cache: DataCache):
        ...

    def fetch_options_chain(self, underlying: str, trade_date: date,
                            min_dte: int = 7, max_dte: int = 60,
                            option_type: str = 'put') -> OptionsChain:
        """Fetch EOD options chain snapshot.

        Args:
            underlying: 'SPX' (only supported value)
            trade_date: Date to fetch
            min_dte: Minimum days to expiry filter
            max_dte: Maximum days to expiry filter
            option_type: 'put', 'call', or 'all'

        Returns:
            OptionsChain with all matching quotes.

        Raises:
            DataFetchError: Polygon API unavailable.
            DataValidationError: Chain fails quality checks.
        """

    def fetch_date_range(self) -> tuple[date, date]:
        """Returns (earliest, latest) dates with available options data.

        Raises:
            DataFetchError: Cannot reach Polygon API.
        """

    def validate_chain(self, chain: OptionsChain) -> list[str]:
        """Run quality checks on a chain.

        Returns:
            List of warning messages (empty if all checks pass).
            Checks: bid <= ask, bid > 0, IV > 0, IV < 3.0, delta range.
        """
```

### 3.3 DataCache

```python
# src/data/cache.py

class DataCache:
    """Source-tagged parquet cache."""

    def __init__(self, base_dir: str = "data/raw"):
        ...

    def read(self, source: str, key: str) -> Optional[pd.DataFrame]:
        """Read cached data. Returns None if not found."""

    def write(self, source: str, key: str, data: pd.DataFrame) -> None:
        """Write data to cache. Overwrites if exists.

        Raises:
            CacheError: Disk write failure.
        """

    def exists(self, source: str, key: str) -> bool:
        """Check if cache entry exists."""

    def age_days(self, source: str, key: str) -> Optional[int]:
        """Days since cache entry was last written. None if not found."""

    def cleanup(self, max_age_days: int = 90) -> int:
        """Delete cache entries older than max_age_days. Returns count deleted."""
```

### 3.4 Features

```python
# src/data/features.py

def compute_realized_vol(close: pd.Series, window: int) -> pd.Series:
    """Annualized realized volatility from log returns.

    Formula: sqrt(252/window * sum(r²)) where r = ln(close/close.shift(1))

    Args:
        close: Price series with DatetimeIndex
        window: Rolling window in trading days

    Returns:
        Series of annualized vol (decimal: 0.15 = 15%). NaN for first `window` values.
    """

def compute_vrp_proxy(vix: pd.Series, rv_21: pd.Series) -> pd.Series:
    """VRP proxy = VIX²/252 - RV(21)²/252.

    Returns:
        Series of daily variance premium. Positive = IV > RV.
    """

def compute_vrp_zscore(vrp: pd.Series, window: int = 252) -> pd.Series:
    """Standardized VRP z-score.

    Returns:
        Series. z > 0 = above-average premium. z < -1 = unusually low.
    """

def compute_term_structure(vix: pd.Series, vix3m: pd.Series) -> pd.Series:
    """VIX term structure = VIX3M/VIX - 1.

    Returns:
        Series. Positive = contango (normal). Negative = backwardation (fear).
    """

def compute_vol_acceleration(rv_5: pd.Series, rv_21: pd.Series) -> pd.Series:
    """Short-term vol acceleration = (RV5 - RV21) / RV21.

    Returns:
        Series. Positive = vol increasing. Negative = vol decreasing.
    """

def compute_all_features(spx_close: pd.Series, vix: pd.Series,
                         vix3m: pd.Series, vvix: pd.Series) -> pd.DataFrame:
    """Compute all features from raw data.

    Returns:
        DataFrame with columns: [rv_5, rv_21, rv_63, vix, vix3m, vvix,
                                  ts, dvol_5, vrp_proxy, z_vrp]
    """
```

---

## 4. Regime Layer

### 4.1 RegimeHMM

```python
# src/regime/hmm.py

class RegimeHMM:
    """3-state Gaussian HMM with centroid-anchored labeling."""

    def __init__(self, n_states: int = 3, n_init: int = 10,
                 n_iter: int = 200, min_training_days: int = 504):
        ...

    def fit(self, features: pd.DataFrame) -> None:
        """Fit HMM on feature matrix (expanding window).

        Args:
            features: DataFrame with columns matching regime feature set.
                      Must have >= min_training_days rows.

        Raises:
            RegimeError: Too few training samples or convergence failure.
        """

    def get_filtered_probs(self, features: pd.DataFrame) -> np.ndarray:
        """Extract FILTERED (not smoothed) state probabilities.

        Uses forward algorithm only. Does NOT use hmmlearn's predict_proba().

        Args:
            features: Same format as fit().

        Returns:
            ndarray shape (T, 3): [P_LV, P_NV, P_HV] per timestep.
            Rows sum to 1.0.
        """

    def get_labels(self) -> np.ndarray:
        """Get centroid-anchored labels from most recent fit.

        Returns:
            ndarray shape (T,) with values in {0, 1, 2}
            mapped to {low_vol, normal_vol, high_vol} via centroids.
        """

    def check_stability(self, old_labels: np.ndarray) -> float:
        """Compare current labels with previous labels on overlap period.

        Returns:
            Agreement ratio in [0, 1]. Must be >= 0.90 to accept new labels.
        """

    def save(self, path: str) -> None:
        """Serialize HMM model + centroids to disk."""

    def load(self, path: str) -> None:
        """Deserialize HMM model + centroids from disk."""
```

### 4.2 RegimeXGBoost

```python
# src/regime/xgboost_clf.py

class RegimeXGBoost:
    """Calibrated XGBoost classifier for real-time regime prediction."""

    def __init__(self, n_estimators: int = 200, max_depth: int = 4,
                 calibration_method: str = 'isotonic'):
        ...

    def train(self, features: pd.DataFrame, labels: np.ndarray) -> float:
        """Train on HMM labels. Returns Brier score on internal validation.

        Args:
            features: Full feature set (may include more features than HMM uses)
            labels: HMM-generated labels, shape (T,)

        Returns:
            Brier score (float). Must be < 0.25.

        Raises:
            RegimeError: Training failure.
        """

    def predict(self, features: pd.Series) -> np.ndarray:
        """Predict regime probabilities for a single timestep.

        Args:
            features: Single row of features.

        Returns:
            ndarray shape (3,): [P_LV, P_NV, P_HV]. Sums to 1.0.
        """

    def save(self, path: str) -> None: ...
    def load(self, path: str) -> None: ...
```

### 4.3 RegimeDetector

```python
# src/regime/detector.py

class RegimeDetector:
    """Orchestrates HMM labeling + XGBoost real-time prediction."""

    def __init__(self, hmm: RegimeHMM, xgb: RegimeXGBoost):
        ...

    def predict(self, features: pd.Series) -> RegimePrediction:
        """Real-time regime prediction.

        Args:
            features: Current feature vector (single row).

        Returns:
            RegimePrediction with probabilities, label, confidence, timestamp.
        """

    def retrain_xgboost(self, features: pd.DataFrame,
                         labels: np.ndarray) -> float:
        """Weekly XGBoost retraining. Returns Brier score."""

    def refit_hmm(self, features: pd.DataFrame) -> bool:
        """Monthly HMM refit.

        Returns:
            True if new labels accepted (stability >= 90%).
            False if rejected (old model preserved).
        """
```

---

## 5. Pricing Layer

### 5.1 BSPricer

```python
# src/pricing/black_scholes.py

class BSPricer:
    """Black-Scholes closed-form pricing and Greeks."""

    def put_price(self, S: float, K: float, T: float,
                  r: float, sigma: float) -> float:
        """European put price. All inputs as described in math design doc."""

    def call_price(self, S: float, K: float, T: float,
                   r: float, sigma: float) -> float:
        """European call price."""

    def put_delta(self, S: float, K: float, T: float,
                  r: float, sigma: float) -> float:
        """Put delta. Returns value in [-1, 0]."""

    def put_gamma(self, S: float, K: float, T: float,
                  r: float, sigma: float) -> float:
        """Gamma (same for put and call). Always positive."""

    def put_theta(self, S: float, K: float, T: float,
                  r: float, sigma: float) -> float:
        """Put theta. Per-day decay (usually negative for long, positive context varies)."""

    def put_vega(self, S: float, K: float, T: float,
                 r: float, sigma: float) -> float:
        """Vega (same for put and call). Always positive."""

    def implied_vol(self, market_price: float, S: float, K: float,
                    T: float, r: float, option_type: str = 'put') -> float:
        """Newton-Raphson implied vol solver.

        Args:
            market_price: Observed option price.
            option_type: 'put' or 'call'.

        Returns:
            Implied vol (decimal). E.g., 0.20 for 20%.

        Raises:
            ValueError: Non-convergence after 100 iterations.
        """

    def find_strike_by_delta(self, S: float, T: float, r: float,
                              sigma: float, target_delta: float = -0.10,
                              strike_increment: float = 5.0) -> float:
        """Find strike where put delta equals target_delta.

        Uses Newton-Raphson. Rounds to nearest strike_increment.

        Returns:
            Strike price (rounded to nearest increment).

        Raises:
            StrikeSelectionError: Non-convergence.
        """
```

### 5.2 HestonModel

```python
# src/pricing/heston.py

class HestonModel:
    """Heston stochastic volatility model."""

    def __init__(self, v0: float, kappa: float, theta: float,
                 sigma_v: float, rho: float):
        """
        Args:
            v0: Current instantaneous variance (decimal, e.g., 0.04 for 20% vol)
            kappa: Mean reversion speed
            theta: Long-run variance
            sigma_v: Vol-of-vol
            rho: Stock-vol correlation (typically negative)
        """

    def characteristic_function(self, xi: complex, T: float,
                                 r: float, S0: float) -> complex:
        """Heston characteristic function φ(ξ).

        See mathematical_design_production.md Section 4.2.
        """

    def check_feller(self) -> bool:
        """Returns True if 2*kappa*theta > sigma_v². Must be enforced."""

    def to_dict(self) -> dict:
        """Serialize parameters to dict."""

    @classmethod
    def from_dict(cls, d: dict) -> 'HestonModel':
        """Deserialize from dict."""
```

### 5.3 FFTPricer

```python
# src/pricing/fft_pricer.py

class FFTPricer:
    """Carr-Madan FFT pricing engine."""

    def __init__(self, model: HestonModel, N: int = 4096,
                 alpha: float = 1.5):
        ...

    def price_calls(self, S: float, T: float,
                    r: float) -> tuple[np.ndarray, np.ndarray]:
        """Price European calls for all strikes via FFT.

        Returns:
            (strikes, prices) — both ndarray shape (N,).
            strikes: log-spaced strike grid.
            prices: corresponding call prices.
        """

    def price_puts(self, S: float, T: float,
                   r: float) -> tuple[np.ndarray, np.ndarray]:
        """Price European puts via put-call parity applied to FFT call prices.

        Returns:
            (strikes, prices) — same shape as price_calls.
        """
```

### 5.4 HestonCalibrator

```python
# src/pricing/calibrator.py

class HestonCalibrator:
    """Calibrates Heston model to market options data."""

    def __init__(self, param_bounds: dict, enforce_feller: bool = True,
                 de_max_iter: int = 200, lm_max_iter: int = 100,
                 max_time_sec: int = 30):
        ...

    def calibrate(self, chain: OptionsChain,
                  prev_result: Optional[CalibrationResult] = None) -> CalibrationResult:
        """Calibrate Heston to options chain.

        Fallback chain:
        1. DE + LM → status='success'
        2. LM fails → status='de_only'
        3. DE fails → use prev_result params → status='fallback_prev'
        4. No prev_result → status='fallback_bs'

        Args:
            chain: Market options data.
            prev_result: Previous day's calibration (for fallback).

        Returns:
            CalibrationResult with fitted parameters and diagnostics.
            Never raises — always returns a result with appropriate status.
        """
```

### 5.5 VolSurface

```python
# src/pricing/vol_surface.py

class VolSurface:
    """Interpolated volatility surface from calibrated Heston model."""

    def __init__(self, calibration: CalibrationResult,
                 chain: OptionsChain, bs_pricer: BSPricer):
        ...

    def implied_vol(self, K: float, T: float) -> float:
        """Interpolated implied vol at (strike, maturity).

        Returns:
            Implied vol (decimal). Always positive.
        """

    def delta(self, K: float, T: float, S: float, r: float) -> float:
        """Put delta at (K, T) using surface IV."""

    def gamma(self, K: float, T: float, S: float, r: float) -> float: ...
    def theta(self, K: float, T: float, S: float, r: float) -> float: ...
    def vega(self, K: float, T: float, S: float, r: float) -> float: ...

    def put_price(self, K: float, T: float, S: float, r: float) -> float:
        """BS put price using surface-interpolated IV."""

    def richness_score(self, K: float, T: float, S: float, r: float,
                       market_price: float) -> float:
        """market_price - model_price. Positive = market is rich."""
```

---

## 6. Strategy Layer

### 6.1 VRP Signal

```python
# src/strategy/vrp_signal.py

class VRPSignal:
    """VRP measurement and z-score computation."""

    def __init__(self, zscore_window: int = 252, zscore_min: float = -1.0):
        ...

    def compute_proxy(self, vix: float, rv_21: float) -> float:
        """VRP proxy = VIX²/252 - RV²/252. Single point."""

    def compute_zscore(self, vrp_history: pd.Series) -> float:
        """Z-score of latest VRP value relative to rolling window."""

    def is_sufficient(self, z_vrp: float) -> bool:
        """Returns True if z_vrp > zscore_min."""
```

### 6.2 EntryDecision

```python
# src/strategy/entry.py

class EntryDecision:
    """Three-condition AND gate for trade entry."""

    def __init__(self, regime_thresholds: dict, vrp_zscore_min: float,
                 min_premium_ratio: float):
        ...

    def should_enter(self, regime: RegimePrediction,
                     vrp_zscore: float,
                     premium_ratio: float) -> EntryResult:
        """Evaluate entry conditions.

        Condition 1: regime.p_high_vol < threshold (regime-dependent sizing)
        Condition 2: vrp_zscore > vrp_zscore_min
        Condition 3: premium_ratio > min_premium_ratio

        Returns:
            EntryResult with enter (bool), position_scale, and reason.
        """
```

### 6.3 StrikeSelector

```python
# src/strategy/strike_selector.py

class StrikeSelector:
    """Selects 10-delta put strike via Newton-Raphson."""

    def __init__(self, target_delta: float = -0.10,
                 strike_increment: float = 5.0):
        ...

    def select(self, vol_surface: VolSurface, S: float, T: float,
               r: float) -> float:
        """Find strike where put delta = target_delta.

        Uses vol surface for strike-dependent IV (Phase 2+).
        Falls back to flat vol if vol_surface is None (Phase 1).

        Returns:
            Strike rounded to nearest strike_increment.

        Raises:
            StrikeSelectionError: Newton-Raphson did not converge.
        """
```

### 6.4 Spread Construction

```python
# src/strategy/spread.py

def build_spread(short_strike: float, long_strike: float,
                 expiry: date, chain: Optional[OptionsChain],
                 vol_surface: Optional[VolSurface],
                 S: float, r: float) -> PutCreditSpread:
    """Construct a PutCreditSpread with all fields populated.

    Uses chain for actual bid/ask/mid if available.
    Falls back to vol_surface model prices if chain quote missing.

    Returns:
        Fully populated PutCreditSpread.

    Raises:
        ValueError: Invalid spread (short <= long, premium <= 0).
    """
```

### 6.5 PositionManager

```python
# src/strategy/position_manager.py

class PositionManager:
    """Monitors open position and checks exit triggers."""

    def __init__(self, profit_target_pct: float = 0.75,
                 stop_loss_multiple: float = 2.0,
                 close_dte: int = 7,
                 emergency_hv_threshold: float = 0.80):
        ...

    def check_exit_triggers(self, spread: PutCreditSpread,
                            current_mid: float,
                            regime: RegimePrediction) -> ExitSignal:
        """Check all four exit conditions.

        1. profit >= profit_target_pct * premium → profit_target
        2. loss >= stop_loss_multiple * premium → stop_loss (urgent)
        3. DTE <= close_dte → dte
        4. regime.p_high_vol >= emergency threshold → regime_emergency (urgent)

        Returns:
            ExitSignal. If multiple triggers fire, returns the most urgent.
        """

    def update_spread_greeks(self, spread: PutCreditSpread,
                              vol_surface: VolSurface,
                              S: float, r: float) -> None:
        """Update spread's Greeks from current vol surface. Mutates spread."""
```

---

## 7. Risk Layer

### 7.1 VolScaler

```python
# src/risk/vol_scaling.py

class VolScaler:
    """Volatility targeting: scales exposure to achieve target portfolio vol."""

    def __init__(self, target_vol: float, max_leverage: float,
                 min_leverage: float, vol_window: int = 20):
        ...

    def compute(self, portfolio_vol: float) -> float:
        """f_vol = clip(target / portfolio_vol, min, max).

        Args:
            portfolio_vol: Annualized realized vol of portfolio (decimal).

        Returns:
            Leverage factor (float).
        """
```

### 7.2 KellyCeiling

```python
# src/risk/kelly_ceiling.py

class KellyCeiling:
    """Portfolio Kelly with adaptive shrinkage based on regime transitions."""

    def __init__(self, mu_prior: dict, f_min: float, f_max: float,
                 rolling_window: int, alpha_steady: float,
                 alpha_hv_transition: float, alpha_other_transition: float,
                 transition_window_days: int):
        ...

    def compute(self, regime: RegimePrediction,
                rolling_return: float, rolling_vol: float,
                regime_age_days: int) -> float:
        """Compute Kelly ceiling with adaptive α.

        α = alpha_hv_transition if regime=HV and age < transition_window
        α = alpha_other_transition if regime changed (non-HV) and age < window
        α = alpha_steady otherwise

        μ_hat = α * μ_prior[regime] + (1-α) * rolling_return
        f_kelly = clip(μ_hat / rolling_vol², f_min, f_max)

        Returns:
            Kelly leverage factor (float).
        """
```

### 7.3 DrawdownMonitor

```python
# src/risk/drawdown.py

class DrawdownMonitor:
    """Tracks drawdown and produces override factor."""

    def __init__(self, warn_threshold: float, reduce_threshold: float,
                 kill_threshold: float):
        ...

    def update(self, portfolio_value: float) -> None:
        """Update HWM and current drawdown. Call daily."""

    @property
    def current_dd(self) -> float:
        """Current drawdown from HWM (decimal, e.g., 0.08 = 8%)."""

    @property
    def hwm(self) -> float:
        """Current high water mark."""

    def compute_override(self) -> float:
        """DD override factor.

        Returns:
            1.0 if DD < warn, 0.5 if DD in [reduce, kill), 0.0 if DD >= kill.
        """
```

### 7.4 LeverageChain

```python
# src/risk/leverage.py

class LeverageChain:
    """Orchestrates the min-chain: min(f_vol, f_kelly, f_dd)."""

    def __init__(self, vol_scaler: VolScaler, kelly: KellyCeiling,
                 dd_monitor: DrawdownMonitor):
        ...

    def compute(self, portfolio_vol: float, rolling_return: float,
                rolling_vol: float, regime: RegimePrediction,
                regime_age_days: int,
                account_value: float,
                max_loss_per_spread: float) -> LeverageResult:
        """Compute final leverage and number of spreads.

        f_final = min(f_vol, f_kelly, f_dd)
        n_spreads = floor(account_value * f_final / max_loss_per_spread)

        Returns:
            LeverageResult with all components and binding constraint.
        """
```

---

## 8. Execution Layer

### 8.1 IBKRBroker

```python
# src/execution/broker.py

class IBKRBroker:
    """IBKR API wrapper via ib_insync."""

    def __init__(self, mode: str, host: str = '127.0.0.1',
                 client_id: int = 1):
        """
        Args:
            mode: 'paper' (port 7497) or 'live' (port 7496).
                  'live' requires interactive confirmation.
        """

    def connect(self) -> bool:
        """Connect to TWS. Returns True on success.

        Raises:
            ExecutionError: Connection failure after timeout.
        """

    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def get_spx_price(self) -> float: ...
    def get_account_value(self) -> float: ...
    def get_positions(self) -> list[dict]: ...

    def get_option_quote(self, strike: float, expiry: date,
                         right: str = 'P') -> OptionQuote:
        """Fetch real-time option quote from IBKR.

        Raises:
            ExecutionError: Quote unavailable.
        """

    def place_spread_order(self, short_strike: float, long_strike: float,
                           expiry: date, n_contracts: int,
                           limit_price: float) -> dict:
        """Place put credit spread order.

        Returns:
            Order dict with: order_id, status, submitted_time.

        Raises:
            ExecutionError: Order rejected or validation failure.
        """

    def close_spread(self, order_id: int,
                     urgency: str = 'normal') -> dict:
        """Close existing spread.

        urgency='normal': limit at mid. 'urgent': market order.

        Raises:
            ExecutionError: Close failed.
        """

    def cancel_order(self, order_id: int) -> bool:
        """Cancel pending order. Returns True if cancelled."""
```

### 8.2 OrderManager

```python
# src/execution/order_manager.py

class OrderManager:
    """Order construction and safety validation."""

    def __init__(self, broker: IBKRBroker, stage_limits: dict):
        ...

    def validate_order(self, spread: PutCreditSpread,
                       n_contracts: int) -> tuple[bool, str]:
        """Pre-flight safety checks.

        Checks: mode, max_contracts, allowed_underlyings, spread direction,
                DTE >= 7, limit_price > 0.

        Returns:
            (is_valid, reason). reason is empty string if valid.
        """

    def submit_entry(self, spread: PutCreditSpread,
                     n_contracts: int) -> dict:
        """Validate and submit spread entry order.

        Raises:
            ExecutionError: Validation failure or order rejection.
        """

    def submit_exit(self, order_id: int,
                    urgency: str = 'normal') -> dict:
        """Submit spread close order.

        Raises:
            ExecutionError: Close failure.
        """
```

---

## 9. Backtest Layer

### 9.1 Metrics

```python
# src/backtest/metrics.py

def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio. Returns 0.0 if std is zero."""

def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown from peak. Returns decimal (e.g., 0.25 = 25%)."""

def cvar_95(returns: pd.Series) -> float:
    """Conditional Value at Risk at 95% confidence (monthly).
    Returns negative number (e.g., -0.08 = worst 5% months average -8%)."""

def worst_month(returns: pd.Series) -> float:
    """Worst single month return. Returns negative number."""

def win_rate(trade_pnls: list[float]) -> float:
    """Fraction of trades with positive P&L. Returns decimal [0, 1]."""

def profit_factor(trade_pnls: list[float]) -> float:
    """Gross profit / gross loss. Returns > 1 if profitable overall."""

def calmar_ratio(annual_return: float, max_dd: float) -> float:
    """Annual return / max drawdown."""

def compute_all_metrics(daily_returns: pd.Series,
                        trade_pnls: list[float]) -> dict:
    """Compute all metrics in one call. Returns dict with all metric names as keys."""
```

### 9.2 ProxyBacktestEngine

```python
# src/backtest/proxy_engine.py

class ProxyBacktestEngine:
    """Phase 1: VRP proxy simulation."""

    def __init__(self, config: dict, regime_detector: RegimeDetector,
                 leverage_chain: LeverageChain):
        ...

    def run(self, features: pd.DataFrame, market_data: pd.DataFrame,
            start_date: date, end_date: date) -> BacktestResult:
        """Run VRP proxy backtest.

        Iterates day-by-day with point-in-time constraints.
        Monthly HMM refit, weekly XGBoost retrain.

        Returns:
            BacktestResult with daily returns, equity curve, metrics.
        """
```

### 9.3 OptionsBacktestEngine

```python
# src/backtest/options_engine.py

class OptionsBacktestEngine:
    """Phase 2: options chain simulation with real spreads."""

    def __init__(self, config: dict, regime_detector: RegimeDetector,
                 calibrator: HestonCalibrator, leverage_chain: LeverageChain,
                 entry_decision: EntryDecision, strike_selector: StrikeSelector,
                 position_manager: PositionManager,
                 polygon_fetcher: PolygonFetcher):
        ...

    def run(self, start_date: date, end_date: date) -> BacktestResult:
        """Run options chain backtest.

        Weekly entry (Tuesday), daily monitoring, real strikes/premiums.
        Transaction costs applied.

        Returns:
            BacktestResult with trade-level detail.
        """
```

### 9.4 CPCV

```python
# src/backtest/cpcv.py

class CPCV:
    """Combinatorially Purged Cross-Validation."""

    def __init__(self, n_groups: int = 5, k_test: int = 2,
                 embargo_days: int = 5):
        ...

    def generate_splits(self, dates: pd.DatetimeIndex) -> list[tuple]:
        """Generate all C(n,k) train/test splits with embargo.

        Returns:
            List of (train_indices, test_indices) tuples.
        """

    def run(self, engine: ProxyBacktestEngine | OptionsBacktestEngine,
            **engine_kwargs) -> dict:
        """Run backtest across all splits.

        Returns:
            {
                'sharpe_mean': float,
                'sharpe_std': float,
                'sharpe_per_split': list[float],
                'pbo': float,  # Probability of Backtest Overfitting
            }
        """
```

---

## 10. Orchestrator

### 10.1 DailyPipeline

```python
# src/orchestrator/daily_pipeline.py

class DailyPipeline:
    """Full daily EOD pipeline."""

    def __init__(self, config: dict, data_fetchers: dict,
                 regime_detector: RegimeDetector,
                 calibrator: Optional[HestonCalibrator],
                 position_manager: PositionManager,
                 leverage_chain: LeverageChain,
                 broker: Optional[IBKRBroker],
                 failure_handler: FailureHandler,
                 state_manager: StateManager,
                 alert_manager: AlertManager):
        ...

    def run(self) -> PipelineResult:
        """Execute daily pipeline: data → features → pricing → regime → monitor → exits → report.

        Returns:
            PipelineResult with step-by-step status.
            Never raises — catches all exceptions internally, sends alerts.
        """
```

### 10.2 WeeklyPipeline

```python
# src/orchestrator/weekly_pipeline.py

class WeeklyPipeline:
    """Tuesday entry pipeline."""

    def __init__(self, config: dict, entry_decision: EntryDecision,
                 strike_selector: StrikeSelector,
                 leverage_chain: LeverageChain,
                 order_manager: Optional[OrderManager],
                 state_manager: StateManager,
                 position_manager: PositionManager,
                 alert_manager: AlertManager):
        ...

    def run(self) -> PipelineResult:
        """Evaluate entry, construct spread, size position, execute.

        Pre-checks: is Tuesday, is trading day, no open position.
        Returns SKIPPED with reason if pre-checks fail.
        """
```

### 10.3 FailureHandler

```python
# src/orchestrator/failure_handler.py

@dataclass(frozen=True)
class RetryResult:
    data: Any
    source: str                   # 'live', 'fallback', 'failed'
    attempts: int
    error: Optional[str] = None

class FailureHandler:
    """Retry logic and fallback selection."""

    def __init__(self, alert_manager: AlertManager):
        ...

    def retry(self, func: Callable, max_retries: int = 3,
              delay_sec: int = 300,
              fallback: Optional[Callable] = None) -> RetryResult:
        """Attempt func with retries and optional fallback.

        Returns:
            RetryResult — always returns, never raises.
            source='live' if func succeeded.
            source='fallback' if fallback used.
            source='failed' if everything failed (data=None).
        """
```

### 10.4 StateManager

```python
# src/orchestrator/state_manager.py

class StateManager:
    """Pipeline state persistence via SQLite."""

    def __init__(self, db_path: str):
        ...

    def mark_running(self, pipeline_id: str) -> None: ...
    def mark_complete(self, pipeline_id: str) -> None: ...
    def is_running(self, pipeline_id: str) -> bool:
        """Also clears stale locks (> 1 hour old)."""

    def save_context(self, pipeline_id: str, context: dict) -> None: ...
    def get_latest_context(self, pipeline_id: str) -> Optional[dict]: ...
    def get_current_dd(self) -> float: ...
    def get_regime_age(self) -> int: ...
    def log_trade(self, trade: dict) -> None: ...
    def log_daily_snapshot(self, snapshot: dict) -> None: ...
```

---

## 11. Alerts

```python
# alerts/manager.py

class AlertManager:
    """Routes alerts based on severity."""

    def __init__(self, email_sender: EmailSender, db_path: str,
                 escalation_threshold: int = 3):
        ...

    def send(self, level: str, title: str, body: str) -> None:
        """Send alert at specified level.

        Levels: 'INFO' (DB only), 'WARNING' (DB + email),
                'CRITICAL' (DB + email + [CRITICAL] prefix),
                'EMERGENCY' (DB + email + [EMERGENCY] prefix).

        Also tracks consecutive warnings per step for auto-escalation.
        """

# alerts/email_sender.py

class EmailSender:
    """SMTP email dispatch."""

    def __init__(self, smtp_host: str, smtp_port: int,
                 sender: str, recipient: str, password: str):
        ...

    def send(self, subject: str, body: str) -> bool:
        """Send email. Returns True on success, False on failure (logged)."""

    def send_daily_report(self, report: str) -> bool:
        """Send formatted daily report email."""
```
