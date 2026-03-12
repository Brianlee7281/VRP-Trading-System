# CLAUDE.md

## Project Overview

VRP (Variance Risk Premium) Trading System — a regime-conditioned systematic short volatility strategy on SPX options. Harvests structural insurance premium from the options market by selling put credit spreads, with HMM + XGBoost regime detection controlling position sizing.

**Not alpha-seeking.** This system collects a structural premium (implied vol > realized vol) that exists because institutional hedging demand is mandated by regulation. Regime detection is for risk management (when to reduce), not prediction (what will happen).

**Four phases:** Phase 1 (VIX proxy backtest, free data) → Phase 2 (options chain backtest, Polygon.io) → Phase 3 (IBKR paper trading) → Phase 4 (live trading). Each phase has a GO/NO-GO gate. Build only what the current phase needs.

## Project Structure

```
vrp-trading/
├── config/           # settings.yaml, holidays.yaml, credentials template
├── src/
│   ├── data/         # Fetchers, cache, features, data models
│   ├── regime/       # HMM, XGBoost, regime detector
│   ├── pricing/      # Black-Scholes, Heston, FFT, calibrator, vol surface
│   ├── strategy/     # VRP signal, entry, strike selector, spread, position mgr
│   ├── risk/         # Vol scaling, Kelly, drawdown, leverage chain, kill switch
│   ├── execution/    # IBKR broker, order manager, fill tracker (Phase 3+)
│   ├── orchestrator/ # Scheduler, pipelines, failure handler, state (Phase 3+)
│   └── backtest/     # Proxy engine, options engine, metrics, CPCV, concordance
├── alerts/           # Alert manager, email sender (Phase 3+)
├── scripts/          # Entry points: run_phase1, run_phase2, run_system, kill
├── tests/            # Mirrors src/ structure
├── notebooks/        # Analysis notebooks (01-05)
├── data/             # .gitignored except README
├── logs/             # .gitignored
└── docs/             # All design documents
```

## Key Documents

Read these before implementing any module:

| Document | When to Read |
|----------|-------------|
| `docs/mathematical_design_production.md` | Before any module — contains all formulas and parameters |
| `docs/pipeline_design.md` | Before any module — system architecture and data flow |
| `docs/implementation_blueprint.md` | Before any module — file responsibilities and config schema |
| `docs/implementation_roadmap.md` | Before each sprint — task breakdown with test cases |
| `docs/phase1.md` through `docs/phase4.md` | Before starting each phase — scope, GO/NO-GO criteria |
| `docs/orchestration.md` | Before Sprint 10 — scheduling and failure handling |
| `docs/contracts.md` | Before any module — interface contracts between modules |

## Coding Standards

### Python Style

- Python 3.11+
- Type hints on all public functions and method signatures
- Docstrings on all public classes and functions (Google style)
- No magic numbers — all constants come from `config/settings.yaml`
- Maximum function length: 40 lines (extract helpers if longer)
- Maximum file length: 300 lines (split module if longer)

### Naming

```python
# Classes: PascalCase
class RegimeDetector:
class HestonCalibrator:
class PutCreditSpread:

# Functions/methods: snake_case
def compute_realized_vol(close: pd.Series, window: int) -> pd.Series:
def find_strike_by_delta(S: float, T: float, r: float, sigma: float, target_delta: float) -> float:

# Constants: UPPER_SNAKE_CASE
MAX_CONTRACTS_PAPER = 50
FELLER_CONDITION_ENFORCED = True

# Config keys: snake_case in YAML, accessed via dot notation or dict
config['risk']['vol_scaling']['target_vol']  # 0.12

# Files: snake_case.py
vol_scaling.py
fft_pricer.py
daily_pipeline.py
```

### Imports

```python
# Standard library first
import sqlite3
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path

# Third-party second
import numpy as np
import pandas as pd
from scipy.optimize import minimize, differential_evolution
from loguru import logger

# Project imports last
from src.data.models import OptionsChain, OptionQuote
from src.regime.detector import RegimeDetector, RegimePrediction
from src.pricing.vol_surface import VolSurface
```

### Error Handling

```python
# DO: Use specific exceptions, log with context
try:
    result = calibrator.calibrate(chain)
except CalibrationError as e:
    logger.warning(f"Heston calibration failed: {e}. Using fallback.")
    result = self._fallback_calibration()

# DO: Fail explicitly on critical issues
if data is None and cache is None:
    raise DataUnavailableError(f"No SPX data for {date}, cache also empty")

# DON'T: Silent failures
try:
    result = calibrator.calibrate(chain)
except:  # Never bare except
    pass  # Never silent pass

# DON'T: Return None without logging
def get_price(self) -> float:
    # Bad: returns None silently if connection is down
    # Good: raises ConnectionError or returns with WARNING log
```

### Configuration Access

```python
# Load config once at startup, pass to constructors
import yaml

def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

# DO: Accept config in constructor
class VolScaler:
    def __init__(self, target_vol: float, max_leverage: float, min_leverage: float):
        self.target_vol = target_vol
        self.max_leverage = max_leverage
        self.min_leverage = min_leverage

# DON'T: Read config inside business logic
class VolScaler:
    def compute(self):
        config = yaml.safe_load(open("config/settings.yaml"))  # Wrong
        target = config['risk']['vol_scaling']['target_vol']    # Wrong
```

## Testing

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_pricing/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

### Test Conventions

```python
# File naming: test_{module}.py mirrors src/{module}.py
# Function naming: test_{class}_{method}_{scenario}

def test_vol_scaler_calm_market():
    """σ_p = 0.06, target = 0.12 → f_vol = 1.5 (clipped to max)"""
    scaler = VolScaler(target_vol=0.12, max_leverage=1.5, min_leverage=0.3)
    assert scaler.compute(portfolio_vol=0.06) == 1.5

def test_vol_scaler_volatile_market():
    """σ_p = 0.24, target = 0.12 → f_vol = 0.5"""
    scaler = VolScaler(target_vol=0.12, max_leverage=1.5, min_leverage=0.3)
    assert scaler.compute(portfolio_vol=0.24) == 0.5

# Numerical tolerance for floats
def test_bs_put_price():
    """Known BS put price."""
    pricer = BSPricer()
    price = pricer.put_price(S=100, K=95, T=0.25, r=0.05, sigma=0.20)
    assert abs(price - EXPECTED_VALUE) < 1e-4  # Use exact expected from docs
```

### Test Data

- Use `tests/fixtures/` for sample data files
- Use `conftest.py` for shared fixtures (sample chains, feature vectors)
- Never call real APIs in unit tests — mock all external calls
- Integration tests (marked with `@pytest.mark.integration`) may call real APIs

### What to Test

Every public method needs at least one test. Numerical functions need tests with exact expected values from the phase documents. For example:

- `phase1.md` Sprint 3 defines: σ_p=0.06 → f_vol=1.5. This becomes an assert.
- `phase1.md` Sprint 2 defines: 2008-09 to 2009-03 → >80% High-Vol. This becomes an assert.
- `mathematical_design_production.md` defines: f_final = min(f_vol, f_kelly, f_dd). This becomes multiple asserts covering each binding case.

## Git Workflow

### Commit Convention

```
S{sprint}-T{task}: {description}

Examples:
S1-T3: parquet cache layer
S2-T2: 3-state HMM with centroid anchoring
S4-T6: Phase 1 verdict — GO
S6-T4: Heston calibrator with fallback chain
```

### Branching

```
main              # Always working, passes all tests
├── phase-1       # Phase 1 development (merge to main after GO verdict)
├── phase-2       # Phase 2 development
├── phase-3       # Phase 3 development
└── phase-4       # Phase 4 config changes only
```

### Per-Task Workflow

```
1. Read task spec in implementation_roadmap.md
2. Read relevant contracts in contracts.md
3. Implement
4. Write tests (or run existing test cases from the task spec)
5. Run: pytest tests/test_{module}/ -v
6. If all pass: git add, git commit with S{n}-T{n} prefix, git push
7. If any fail: fix before committing
```

### Tag After Each Phase Verdict

```bash
git tag -a phase-1-verified -m "Phase 1 GO: Sharpe=X.XX, MDD=X.X%"
git tag -a phase-2-verified -m "Phase 2 GO: Sharpe=X.XX, MDD=X.X%, WinRate=X%"
```

## Build Order

Follow `implementation_blueprint.md` Section 2.2 strictly. Bottom-up, most-depended-on first:

```
Phase 1: S1 (data) → S2 (regime) → S3 (risk) → S4 (backtest)
          S2 and S3 can be parallel after S1

Phase 2: S5 (Polygon) → S6 (pricing) → S7 (strategy) → S8 (backtest)
          S7 partially parallel with S6

Phase 3: S9 (IBKR) → S10 (orchestration) → S11 (alerts)
          Sequential — each depends on previous
```

Never skip ahead. Never implement a Phase 2 module during Phase 1 sprints. If Phase 1 returns NO-GO, Phase 2 code is wasted effort.

## Critical Implementation Notes

### HMM Filtering (Most Common Bug Source)

`hmmlearn`'s `predict_proba()` returns **smoothed** posteriors (uses future data). The system MUST use **filtered** probabilities only. Extract forward variables via `_do_forward_pass()` and normalize manually. See `mathematical_design_production.md` Section 3.

This is the single most likely source of look-ahead bias in backtesting. Verify by checking that filtered P(HV) on 2020-03-10 differs from smoothed P(HV) on 2020-03-10.

### min-Chain is min(), Not Product

```python
# CORRECT
f_final = min(f_vol, f_kelly, f_dd)

# WRONG — this was a previous design that was explicitly corrected
f_final = min(f_vol, f_kelly) * f_dd
```

The min-chain uses `min()` across all three risk factors. Never multiply. See `mathematical_design_production.md` Section 6.4.

### Heston Feller Condition

Always enforce $2\kappa\theta > \sigma_v^2$ as a hard constraint in the optimizer. If violated, the variance process can hit zero and cause numerical instability. This is a bound constraint in differential evolution, not a post-hoc check.

### Kelly Adaptive α

The Kelly shrinkage weight α is NOT constant. It changes on regime transitions:
- Steady state (regime unchanged ≥ 5 days): α = 0.6
- Emergency (transition to High-Vol < 5 days): α = 0.9
- Other transition (< 5 days): α = 0.75

This ensures the conservative prior (μ = 2% for HV) dominates immediately during crisis.

### SPX Strike Spacing

SPX options have $5 strike increments. The strike selector outputs a theoretical 10-delta strike, which must be rounded to the nearest $5. Always round to the nearest available tradeable strike, not the nearest $5 in a specific direction.

### Point-in-Time Everything

Every feature, every regime prediction, every risk calculation uses ONLY data available at time t. No `shift(-1)` mistakes, no accidental use of today's close for today's signal. The backtest engine iterates day-by-day and passes `data[:t+1]` to each function.

### Phase 3 Paper Mode Guard

IBKRBroker in Phase 3 must assert `mode == 'paper'`. The live mode confirmation prompt ("CONFIRM LIVE") is a Phase 4 feature only. If you're working on Phase 3 code, the broker should never accept `mode='live'`.

## Current Phase

Check `config/settings.yaml` → `system.phase` to know which phase is active. Only implement and test modules needed for the current phase. The module activation map in `implementation_blueprint.md` Section 2.3 shows exactly which files are active per phase.

## When in Doubt

1. Check `mathematical_design_production.md` for formulas and parameters
2. Check `contracts.md` for interface contracts
3. Check `implementation_roadmap.md` for the current task's test cases
4. Check the relevant phase doc for GO/NO-GO criteria
5. If still unclear, ask — don't guess
