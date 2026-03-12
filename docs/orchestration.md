# Orchestration Design

**Scheduling, Dependency Management, Failure Handling, and System Lifecycle**

> This document defines how the VRP system's components coordinate in time.
> Covers: what runs when, in what order, what happens when things fail, and how the system recovers.
> References: `pipeline_design.md` (module architecture), `phase3.md` (operational details), `phase4.md` (live procedures).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Scheduler Architecture](#2-scheduler-architecture)
3. [Daily Pipeline](#3-daily-pipeline)
4. [Weekly Pipeline](#4-weekly-pipeline)
5. [Monthly Pipeline](#5-monthly-pipeline)
6. [Dependency Graph](#6-dependency-graph)
7. [Failure Handling Framework](#7-failure-handling-framework)
8. [State Management](#8-state-management)
9. [Market Calendar](#9-market-calendar)
10. [Logging & Observability](#10-logging--observability)
11. [System Lifecycle](#11-system-lifecycle)

---

## 1. Overview

### 1.1 Design Principles

**Sequential within a pipeline, independent across pipelines.** Each pipeline (daily, weekly, monthly) is a sequence of dependent steps. But daily and weekly pipelines don't block each other — the weekly pipeline reads the daily pipeline's outputs but doesn't wait for it in real-time.

**Idempotent where possible.** Re-running a pipeline step with the same inputs produces the same outputs. This enables safe retries and manual re-runs after failures.

**Fail-safe, not fail-fast.** When a step fails, the system degrades gracefully rather than halting entirely. Downstream steps use fallbacks (cached data, previous parameters) and continue. Only truly unrecoverable failures (no data at all, IBKR down for execution) halt the pipeline.

**Observable by default.** Every step logs its start, end, duration, status, and outputs. Failures log the full exception. The daily report summarizes all pipeline activity. Nothing runs silently.

### 1.2 Module Structure

```
src/orchestrator/
├── __init__.py
├── scheduler.py            # APScheduler configuration and job registration
├── daily_pipeline.py       # DailyPipeline: data → features → pricing → regime → monitor
├── weekly_pipeline.py      # WeeklyPipeline: entry → strike → sizing → execute
├── monthly_pipeline.py     # MonthlyPipeline: HMM refit → cleanup
├── failure_handler.py      # Retry logic, fallback selection, alert escalation
├── state_manager.py        # Pipeline state persistence (SQLite)
├── market_calendar.py      # US market holidays, early closes, trading day logic
└── pipeline_context.py     # Shared context object passed between steps
```

---

## 2. Scheduler Architecture

### 2.1 APScheduler Configuration

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BlockingScheduler(
    timezone='US/Eastern',
    job_defaults={
        'coalesce': True,          # If multiple missed fires, run once
        'max_instances': 1,         # Never run same job concurrently
        'misfire_grace_time': 3600, # Allow 1 hour late start
    }
)

# Daily pipeline — every weekday at 16:30 ET
scheduler.add_job(
    daily_pipeline.run,
    CronTrigger(day_of_week='mon-fri', hour=16, minute=30),
    id='daily_pipeline',
    name='Daily EOD Pipeline',
)

# Weekly pipeline — Tuesday at 17:15 ET
scheduler.add_job(
    weekly_pipeline.run,
    CronTrigger(day_of_week='tue', hour=17, minute=15),
    id='weekly_pipeline',
    name='Weekly Entry Pipeline',
)

# Monthly pipeline — 1st of each month at 18:00 ET
scheduler.add_job(
    monthly_pipeline.run,
    CronTrigger(day=1, hour=18, minute=0),
    id='monthly_pipeline',
    name='Monthly Refit Pipeline',
)
```

### 2.2 Misfire Handling

If the machine was off during a scheduled time:

| Job | Misfire Behavior | Rationale |
|-----|-----------------|-----------|
| Daily pipeline | Run on next startup (coalesce) | Stale data is better than no data. Will use cache. |
| Weekly pipeline | Run on next startup IF still Tuesday. Skip if another day. | Entry should only happen on Tuesday. |
| Monthly pipeline | Run on next startup within same month. Skip if month passed. | HMM refit can wait a month. |

```python
# Weekly pipeline misfire guard
class WeeklyPipeline:
    def run(self):
        if datetime.now(ET).weekday() != 1:  # Not Tuesday
            logger.info("Weekly pipeline skipped: not Tuesday (misfire from earlier)")
            return PipelineResult(status='SKIPPED', reason='not_tuesday')
        if not market_calendar.is_trading_day(date.today()):
            logger.info("Weekly pipeline skipped: market holiday")
            return PipelineResult(status='SKIPPED', reason='holiday')
        # ... proceed with entry logic
```

### 2.3 Concurrency Control

```
Rule: No two pipelines run simultaneously.
Implementation: APScheduler max_instances=1 per job.
Edge case: Weekly pipeline starts at 17:15 while daily pipeline
           is still running (delayed start or slow calibration).
Solution: Weekly pipeline checks daily pipeline lock.
          If daily still running, weekly waits up to 15 minutes.
          If daily hasn't finished by 17:30, weekly runs anyway
          using cached daily outputs (regime, pricing from previous day).
```

```python
class WeeklyPipeline:
    def run(self):
        # Wait for daily pipeline if it's still running
        waited = 0
        while state_manager.is_running('daily_pipeline') and waited < 900:
            time.sleep(60)
            waited += 60

        if state_manager.is_running('daily_pipeline'):
            logger.warning("Daily pipeline still running after 15min wait. "
                          "Using cached outputs.")
            context = state_manager.get_latest_context('daily_pipeline')
        else:
            context = state_manager.get_latest_context('daily_pipeline')

        # ... proceed with context
```

---

## 3. Daily Pipeline

### 3.1 Step Definitions

```
DAILY PIPELINE (16:30 ET, weekdays)
│
├─ Step 1: IBKR Connect (Phase 3+ only)
│   timeout: 60s │ retry: 3x/60s │ fallback: skip execution steps
│
├─ Step 2: Data Fetch
│   ├─ 2a: SPX OHLCV (Yahoo Finance)
│   │   timeout: 30s │ retry: 3x/300s │ fallback: cache (prev day)
│   ├─ 2b: VIX, VIX3M, risk-free rate (FRED)
│   │   timeout: 30s │ retry: 3x/300s │ fallback: cache (prev day)
│   ├─ 2c: VVIX (CBOE)
│   │   timeout: 30s │ retry: 3x/300s │ fallback: cache (prev day)
│   └─ 2d: Options chain (Polygon.io) — Phase 2+ only
│       timeout: 60s │ retry: 3x/600s │ fallback: skip pricing update
│
├─ Step 3: Feature Computation
│   depends: Step 2 │ fallback: forward-fill NaN │ no retry (deterministic)
│
├─ Step 4: Heston Calibration — Phase 2+ only
│   depends: Step 2d + Step 3 │ timeout: 30s
│   fallback chain: DE-only → prev day params → BS
│
├─ Step 5: Regime Detection
│   depends: Step 3 │ fallback: prev day regime │ no retry (deterministic)
│
├─ Step 6: Position Monitoring
│   depends: Step 4 (pricing) + Step 5 (regime)
│   ├─ Update Greeks (from vol surface or BS)
│   ├─ Update mark-to-market P&L
│   ├─ Check exit triggers
│   └─ If trigger fired → Step 7
│
├─ Step 7: Execute Exits (if triggered)
│   depends: Step 6 + Step 1 (IBKR connection)
│   retry: 3x/60s │ fallback: CRITICAL alert, manual exit required
│
├─ Step 8: Daily Report
│   depends: all above │ no fallback (must send, even if partial)
│
└─ Step 9: IBKR Disconnect + State Save
    always runs │ saves pipeline context to SQLite
```

### 3.2 Implementation

```python
@dataclass
class PipelineContext:
    """Shared state passed between pipeline steps."""
    trade_date: date
    spx_close: float = None
    vix: float = None
    vix3m: float = None
    vvix: float = None
    risk_free_rate: float = None
    options_chain: OptionsChain = None
    features: pd.Series = None
    calibration: CalibrationResult = None
    vol_surface: VolSurface = None
    regime: RegimePrediction = None
    exits_triggered: list = field(default_factory=list)
    step_results: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)

class DailyPipeline:
    def __init__(self, config, failure_handler, state_manager,
                 alert_manager, data_fetchers, regime_detector,
                 calibrator, position_manager, broker=None):
        self.config = config
        self.fh = failure_handler
        self.state = state_manager
        self.alerts = alert_manager
        # ... store all dependencies

    def run(self) -> PipelineResult:
        ctx = PipelineContext(trade_date=date.today())
        self.state.mark_running('daily_pipeline')

        try:
            # Check market calendar
            if not market_calendar.is_trading_day(ctx.trade_date):
                return self._skip("Market holiday")

            # Step 1: IBKR (Phase 3+)
            ctx.step_results['ibkr'] = self._connect_ibkr(ctx)

            # Step 2: Data
            ctx.step_results['data'] = self._fetch_data(ctx)
            if ctx.step_results['data'].severity == 'CRITICAL':
                return self._abort(ctx, "Critical data failure")

            # Step 3: Features
            ctx.step_results['features'] = self._compute_features(ctx)

            # Step 4: Pricing (Phase 2+)
            if self.config.phase >= 2:
                ctx.step_results['pricing'] = self._calibrate(ctx)

            # Step 5: Regime
            ctx.step_results['regime'] = self._detect_regime(ctx)

            # Step 6: Position monitoring
            ctx.step_results['monitor'] = self._monitor_positions(ctx)

            # Step 7: Execute exits
            if ctx.exits_triggered:
                ctx.step_results['exits'] = self._execute_exits(ctx)

            # Step 8: Daily report
            self._send_report(ctx)

            # Step 9: State save
            self._save_state(ctx)

            return PipelineResult(status='OK', context=ctx)

        except Exception as e:
            self.alerts.send('EMERGENCY', 'Pipeline crash', str(e))
            logger.exception("Daily pipeline crashed")
            return PipelineResult(status='CRASH', error=str(e))

        finally:
            self._disconnect_ibkr()
            self.state.mark_complete('daily_pipeline')
```

### 3.3 Step Detail: Data Fetch

```python
def _fetch_data(self, ctx: PipelineContext) -> StepResult:
    results = {}

    # 2a: SPX — required
    spx = self.fh.retry(
        lambda: self.data.fetch_spx_ohlcv(ctx.trade_date, ctx.trade_date),
        max_retries=3, delay=300, fallback=self._cache_spx
    )
    if spx.from_cache and spx.cache_age_days > 1:
        return StepResult('CRITICAL', 'SPX data stale > 1 day')
    ctx.spx_close = spx.data['Close'].iloc[-1]

    # 2b: VIX — required
    vix = self.fh.retry(
        lambda: self.data.fetch_vix(ctx.trade_date, ctx.trade_date),
        max_retries=3, delay=300, fallback=self._cache_vix
    )
    if vix.from_cache and vix.cache_age_days > 1:
        return StepResult('CRITICAL', 'VIX data stale > 1 day')
    ctx.vix = vix.data.iloc[-1]

    # 2c: VIX3M, VVIX — degraded OK
    ctx.vix3m = self.fh.retry(
        lambda: self.data.fetch_vix3m(...),
        max_retries=3, delay=300, fallback=self._cache_vix3m
    ).data.iloc[-1]

    ctx.vvix = self.fh.retry(
        lambda: self.data.fetch_vvix(...),
        max_retries=3, delay=300, fallback=self._cache_vvix
    ).data.iloc[-1]

    # 2d: Options chain (Phase 2+) — degraded OK
    if self.config.phase >= 2:
        chain = self.fh.retry(
            lambda: self.polygon.fetch_options_chain('SPX', ctx.trade_date),
            max_retries=3, delay=600, fallback=lambda: None
        )
        ctx.options_chain = chain.data  # May be None

    return StepResult('OK')
```

### 3.4 Timing Budget

| Step | Expected Duration | Max Allowed | If Exceeds |
|------|------------------|-------------|-----------|
| IBKR Connect | 2s | 60s | Skip IBKR, WARNING |
| SPX fetch | 2s | 30s + 3 retries | Cache fallback |
| VIX/VIX3M/VVIX fetch | 3s | 30s + 3 retries per source | Cache fallback |
| Options chain fetch | 5s | 60s + 3 retries | Skip pricing update |
| Feature computation | <1s | 5s | Should never fail |
| Heston calibration | 5-15s | 30s | Fallback chain |
| Regime detection | <1s | 5s | Prev day fallback |
| Position monitoring | 1-2s | 10s | Should never fail |
| Exit execution | 2-30s | 120s | CRITICAL alert |
| Report generation | 1-2s | 10s | Best effort |
| **Total pipeline** | **~30s-60s** | **~20min (with retries)** | Partial completion |

---

## 4. Weekly Pipeline

### 4.1 Step Definitions

```
WEEKLY PIPELINE (Tuesday 17:15 ET)
│
├─ Pre-check: Is today Tuesday? Is it a trading day?
│   If no → skip (return immediately)
│
├─ Pre-check: Did daily pipeline complete today?
│   If no → wait up to 15min, then use cached context
│
├─ Pre-check: Is there an open position?
│   If yes → skip entry (no position stacking)
│
├─ Step 1: Load Daily Context
│   source: state_manager.get_latest_context('daily_pipeline')
│   required: regime prediction, VRP z-score, vol surface (Phase 2+)
│
├─ Step 2: Entry Decision
│   inputs: regime, z_VRP, premium_ratio
│   output: EntryResult (enter/skip, scale, reason)
│   no retry (deterministic) │ no fallback (skip is safe)
│
├─ Step 3: Strike Selection — only if Step 2 = ENTER
│   input: vol_surface (or BS approximation in Phase 1)
│   output: K1 (short), K2 (long)
│   no retry │ fallback: skip entry this week
│
├─ Step 4: Spread Construction — only if Step 3 succeeded
│   output: PutCreditSpread with premium, Greeks, max_loss
│
├─ Step 5: Risk Sizing
│   inputs: leverage_chain components + account value
│   output: f_final, n_contracts
│
├─ Step 6: Order Execution — Phase 3+ only
│   timeout: 120s │ retry: 3x/60s
│   fallback: cancel, skip entry, CRITICAL alert
│
├─ Step 7: Fill Confirmation — Phase 3+ only
│   timeout: 300s │ if no fill: cancel order, skip, WARNING
│
└─ Step 8: Log Trade + Update State
    always runs (even if skipped — logs the skip reason)
```

### 4.2 Implementation

```python
class WeeklyPipeline:
    def run(self) -> PipelineResult:
        # Pre-checks
        if not self._is_valid_entry_day():
            return PipelineResult(status='SKIPPED', reason='not_entry_day')

        if self.position_manager.has_open_position():
            return PipelineResult(status='SKIPPED', reason='position_open')

        # Load daily context
        ctx = self._load_daily_context()

        # Step 2: Entry decision
        entry = self.entry_decision.should_enter(
            regime=ctx.regime,
            vrp_zscore=ctx.features['z_vrp'],
            premium_ratio=self._estimate_premium_ratio(ctx)
        )

        if not entry.enter:
            self._log_skip(entry.reason)
            return PipelineResult(status='SKIPPED', reason=entry.reason)

        # Step 3-4: Strike + Spread
        spread = self._construct_spread(ctx, entry)
        if spread is None:
            self._log_skip('spread_construction_failed')
            return PipelineResult(status='SKIPPED',
                                 reason='spread_construction_failed')

        # Step 5: Sizing
        leverage = self.leverage_chain.compute(
            portfolio_vol=ctx.features['rv_21'] / 100,
            portfolio_return=self._rolling_return_60d(),
            regime=ctx.regime,
            current_dd=self.state.get_current_dd(),
            regime_age_days=self.state.get_regime_age()
        )
        n_contracts = self._size_position(leverage, spread, entry.position_scale)

        if n_contracts == 0:
            self._log_skip('position_size_zero')
            return PipelineResult(status='SKIPPED', reason='zero_size')

        # Step 6-7: Execute (Phase 3+)
        if self.config.phase >= 3:
            order = self._execute_entry(spread, n_contracts)
            if order.status != 'FILLED':
                return PipelineResult(status='EXECUTION_FAILED',
                                     reason=order.failure_reason)

        # Step 8: Log
        self._log_trade(spread, n_contracts, leverage, entry, ctx)

        return PipelineResult(status='ENTERED',
                             spread=spread, n_contracts=n_contracts)
```

### 4.3 Premium Ratio Estimation

Before constructing the full spread, estimate if premium will be sufficient:

```python
def _estimate_premium_ratio(self, ctx: PipelineContext) -> float:
    """Quick estimate of Π/W without full spread construction.
    Phase 1: Use VIX-based heuristic.
    Phase 2+: Use vol surface for actual estimate."""

    if self.config.phase == 1:
        # Rough heuristic: premium ratio scales with VIX
        # At VIX=15: ~12%, at VIX=25: ~18%, at VIX=10: ~8%
        return ctx.vix / 100 * 0.8  # Approximate

    # Phase 2+: actual estimate from vol surface
    K1 = self.strike_selector.find_10delta(ctx.vol_surface, ...)
    K2 = K1 - self.config.spread_width
    premium = (ctx.vol_surface.put_price(K1) - ctx.vol_surface.put_price(K2))
    return premium / self.config.spread_width
```

---

## 5. Monthly Pipeline

### 5.1 Step Definitions

```
MONTHLY PIPELINE (1st of month, 18:00 ET)
│
├─ Pre-check: Is today a trading day?
│   If no → defer to next trading day
│
├─ Step 1: HMM Refit
│   input: full feature history (expanding window)
│   output: new HMM model + new labels
│   timeout: 300s │ no retry │ fallback: keep previous model
│
├─ Step 2: Label Stability Check
│   compare: new labels vs old labels on overlap period
│   threshold: >= 90% agreement
│   if fail → reject new model, keep old, WARNING alert
│
├─ Step 3: XGBoost Retrain (if Step 2 passed)
│   input: new HMM labels as targets
│   output: new XGBoost model
│   validation: Brier score < 0.25
│   if Brier >= 0.25 → reject, keep old model, WARNING
│
├─ Step 4: Centroid Update
│   update reference centroids if state structure changed
│   (rare — usually centroids are stable)
│
├─ Step 5: Cache Cleanup
│   remove raw data cache files older than 90 days
│   keep processed features indefinitely
│
├─ Step 6: Data Integrity Check
│   verify: no gaps in daily_snapshots table for past month
│   verify: all trades have complete entry + exit records
│   verify: cache files exist for all trading days
│
└─ Step 7: Monthly Summary Report
    aggregate: monthly return, trades, regime distribution
    append to monthly_reports table in SQLite
```

### 5.2 XGBoost Weekly Retrain

In addition to the monthly HMM refit, XGBoost is retrained weekly (within the daily pipeline, on Fridays):

```python
# Inside DailyPipeline, Friday-only logic:
if ctx.trade_date.weekday() == 4:  # Friday
    self._retrain_xgboost(ctx)

def _retrain_xgboost(self, ctx):
    """Weekly XGBoost retrain using existing HMM labels.
    Does NOT refit HMM — just updates XGBoost with latest data."""
    labels = self.regime_detector.hmm.get_labels()
    features = self.feature_store.get_all()
    brier = self.regime_detector.retrain_xgboost(features, labels)

    if brier >= 0.25:
        logger.warning(f"XGBoost retrain Brier={brier:.3f} >= 0.25, "
                      "keeping previous model")
        self.alerts.send('WARNING', 'XGBoost retrain degraded',
                        f'Brier={brier:.3f}')
```

---

## 6. Dependency Graph

### 6.1 Intra-Pipeline Dependencies

```
DAILY PIPELINE:

  IBKR Connect ─────────────────────────────────┐
                                                 │
  SPX Fetch ──┐                                  │
  VIX Fetch ──┼── Features ──┬── Regime ─────────┤
  VIX3M Fetch ┤              │                   │
  VVIX Fetch ──┘              │                   │
                              │                   │
  Chain Fetch ── Heston Cal ──┘                   │
                    │                             │
                    └── Vol Surface ──┐           │
                                     │           │
                    Position Monitor ─┤           │
                         │            │           │
                    Exit Triggers ────┼── Execute Exits
                                     │           │
                                     └── Daily Report
```

### 6.2 Inter-Pipeline Dependencies

```
DAILY (16:30) ──outputs──→ state_manager ──reads──→ WEEKLY (17:15 Tue)
     │                                                    │
     │                                                    │
     └── regime, features, vol surface, pricing ──────────┘

DAILY (Fri) ──XGB retrain──→ regime_detector (updated model)

MONTHLY (1st) ──HMM refit──→ regime_detector (updated labels + model)
     │
     └── New HMM labels → next XGB retrain uses these
```

### 6.3 Data Flow Between Pipelines

| Producer | Consumer | Data | Mechanism |
|----------|----------|------|-----------|
| Daily | Weekly | Regime prediction | state_manager (SQLite) |
| Daily | Weekly | VRP z-score | state_manager |
| Daily | Weekly | Vol surface / calibration | state_manager (pickled) |
| Daily | Weekly | Account value, DD | state_manager |
| Daily (Fri) | Daily (next week) | Updated XGBoost | In-memory model swap |
| Monthly | Daily | Updated HMM + labels | In-memory model swap |
| Monthly | Daily (next Fri) | New HMM labels | Used in XGB retrain |

---

## 7. Failure Handling Framework

### 7.1 FailureHandler

```python
class FailureHandler:
    def retry(self, func: Callable, max_retries: int = 3,
              delay_sec: int = 300,
              fallback: Callable = None) -> RetryResult:
        """
        Attempts func up to max_retries times with delay between attempts.
        If all retries fail and fallback is provided, calls fallback.
        Returns RetryResult with data, source ('live' or 'fallback'),
        and attempt count.
        """
        for attempt in range(1, max_retries + 1):
            try:
                result = func()
                return RetryResult(data=result, source='live', attempts=attempt)
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    time.sleep(delay_sec)

        # All retries exhausted
        if fallback:
            try:
                result = fallback()
                return RetryResult(data=result, source='fallback',
                                  attempts=max_retries)
            except Exception as e:
                logger.error(f"Fallback also failed: {e}")
                return RetryResult(data=None, source='failed',
                                  attempts=max_retries, error=str(e))

        return RetryResult(data=None, source='failed',
                          attempts=max_retries)
```

### 7.2 Failure Classification

| Severity | Definition | Pipeline Action | Alert |
|----------|-----------|----------------|-------|
| DEGRADED | Step used fallback but pipeline continues | Continue | WARNING |
| IMPAIRED | Step failed, downstream quality reduced | Continue with caveat | WARNING |
| BLOCKED | Step failed, downstream step cannot run | Skip downstream | CRITICAL |
| FATAL | Pipeline cannot continue at all | Abort pipeline | EMERGENCY |

### 7.3 Complete Failure Matrix

| Step | Failure Mode | Severity | Retry | Fallback | Downstream Impact |
|------|-------------|----------|-------|----------|-------------------|
| **IBKR Connect** | Timeout | BLOCKED | 3x/60s | Skip execution | Monitoring OK, exits impossible |
| **IBKR Connect** | Auth failure | FATAL | No | None | All execution blocked |
| **SPX Fetch** | API timeout | DEGRADED | 3x/300s | Cache (prev day) | Features use stale close |
| **SPX Fetch** | Cache miss + API fail | FATAL | — | None | Abort: no price data |
| **VIX Fetch** | API timeout | DEGRADED | 3x/300s | Cache (prev day) | VRP proxy stale |
| **VIX3M Fetch** | API timeout | DEGRADED | 3x/300s | Cache (prev day) | TS feature stale |
| **VVIX Fetch** | API timeout | DEGRADED | 3x/300s | Cache (prev day) | VVIX feature stale |
| **Chain Fetch** | Polygon timeout | IMPAIRED | 3x/600s | Skip pricing | No Heston update today |
| **Chain Fetch** | Polygon down | IMPAIRED | 3x/600s | Skip pricing | No Heston for multiple days |
| **Features** | NaN in output | DEGRADED | No | Forward-fill | Regime input slightly stale |
| **Heston Cal** | LM fails | DEGRADED | No | DE-only result | Slightly less accurate surface |
| **Heston Cal** | DE fails | DEGRADED | No | Prev day params | Surface may be stale |
| **Heston Cal** | Both fail | BLOCKED | No | BS fallback | No vol surface, basic Greeks only |
| **Heston Cal** | 3 consecutive | FATAL | — | Halt new entries | CRITICAL alert, manual review |
| **Regime** | XGB error | DEGRADED | No | Prev day regime | Regime may be stale |
| **Position Mon** | No pricing data | IMPAIRED | No | Use BS Greeks | Greeks less accurate |
| **Exit Execution** | IBKR down | BLOCKED | 3x/60s | Manual exit | EMERGENCY alert |
| **Exit Execution** | Order rejected | DEGRADED | 1x adjusted | Cancel, retry next day | WARNING |
| **Entry Execution** | IBKR down | BLOCKED | 3x/60s | Skip entry | CRITICAL, try next week |
| **Entry Execution** | No fill 5min | DEGRADED | No | Cancel order | Skip this week |
| **Report** | Email send fail | DEGRADED | 2x/60s | Log only | Operator won't see report |
| **HMM Refit** | Non-convergence | DEGRADED | No | Keep prev model | HMM stale for 1 month |
| **HMM Refit** | Stability < 90% | DEGRADED | No | Reject new model | HMM stale, investigate |
| **XGB Retrain** | Brier >= 0.25 | DEGRADED | No | Keep prev model | XGB stale for 1 week |

### 7.4 Escalation Logic

```python
class AlertEscalation:
    def __init__(self):
        self.consecutive_warnings = defaultdict(int)

    def process(self, step: str, severity: str):
        if severity == 'DEGRADED':
            self.consecutive_warnings[step] += 1
            if self.consecutive_warnings[step] >= 3:
                # 3 consecutive degraded → escalate to CRITICAL
                self.alerts.send('CRITICAL',
                    f'{step} degraded 3 consecutive days',
                    'Investigate root cause')
                self.consecutive_warnings[step] = 0
        else:
            self.consecutive_warnings[step] = 0  # Reset on success
```

---

## 8. State Management

### 8.1 StateManager

```python
class StateManager:
    """Persists pipeline state between runs. Uses SQLite."""

    def mark_running(self, pipeline_id: str) -> None:
        """Record that a pipeline is currently executing."""

    def mark_complete(self, pipeline_id: str) -> None:
        """Record pipeline completion."""

    def is_running(self, pipeline_id: str) -> bool:
        """Check if a pipeline is currently running.
        Also handles stale locks (if a pipeline crashed without completing,
        lock expires after 1 hour)."""

    def save_context(self, pipeline_id: str, ctx: PipelineContext) -> None:
        """Save pipeline outputs for consumption by other pipelines."""

    def get_latest_context(self, pipeline_id: str) -> PipelineContext:
        """Load most recent pipeline context."""

    def get_current_dd(self) -> float:
        """Current drawdown from daily_snapshots table."""

    def get_regime_age(self) -> int:
        """Days since last regime transition."""

    def get_hwm(self) -> float:
        """High water mark from daily_snapshots."""
```

### 8.2 Stale Lock Recovery

```python
def is_running(self, pipeline_id: str) -> bool:
    row = self.db.execute(
        "SELECT started_at FROM pipeline_locks WHERE id = ? AND completed = 0",
        (pipeline_id,)
    ).fetchone()

    if row is None:
        return False

    # Stale lock detection: if started > 1 hour ago, assume crash
    started = datetime.fromisoformat(row['started_at'])
    if datetime.now() - started > timedelta(hours=1):
        logger.warning(f"Stale lock detected for {pipeline_id}, clearing")
        self.db.execute(
            "UPDATE pipeline_locks SET completed = 1 WHERE id = ?",
            (pipeline_id,)
        )
        return False

    return True
```

### 8.3 SQLite Schema for State

```sql
CREATE TABLE pipeline_locks (
    id TEXT PRIMARY KEY,
    started_at TEXT,
    completed INTEGER DEFAULT 0,
    completed_at TEXT
);

CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id TEXT,
    run_date TEXT,
    status TEXT,           -- OK, SKIPPED, DEGRADED, FAILED, CRASH
    duration_sec REAL,
    step_results TEXT,     -- JSON: {"data": "OK", "regime": "OK", ...}
    context_blob BLOB,     -- Pickled PipelineContext (for inter-pipeline use)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 9. Market Calendar

### 9.1 Implementation

```python
class MarketCalendar:
    """US equity options market calendar."""

    HOLIDAYS_2026 = [
        date(2026, 1, 1),   # New Year's
        date(2026, 1, 19),  # MLK Jr.
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 7, 3),   # Independence Day (observed)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25), # Christmas
    ]

    EARLY_CLOSES_2026 = [
        date(2026, 11, 27), # Day after Thanksgiving (13:00 ET)
        date(2026, 12, 24), # Christmas Eve (13:00 ET)
    ]

    def is_trading_day(self, d: date) -> bool:
        """True if US equity markets are open."""
        if d.weekday() >= 5:  # Weekend
            return False
        if d in self.HOLIDAYS_2026:
            return False
        return True

    def is_early_close(self, d: date) -> bool:
        return d in self.EARLY_CLOSES_2026

    def market_close_time(self, d: date) -> time:
        if self.is_early_close(d):
            return time(13, 0)  # 13:00 ET
        return time(16, 0)      # 16:00 ET

    def next_trading_day(self, d: date) -> date:
        """Next trading day after d."""
        candidate = d + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate
```

### 9.2 Calendar Maintenance

The holiday calendar must be updated annually. Add a January task to the operational checklist:

```
[] January each year: update MarketCalendar with new year's holidays
   Source: NYSE holiday calendar (https://www.nyse.com/markets/hours-calendars)
```

### 9.3 Early Close Handling

On early close days, the daily pipeline runs earlier:

```python
def _get_pipeline_time(self, d: date) -> time:
    if market_calendar.is_early_close(d):
        return time(13, 30)  # 30 min after early close
    return time(16, 30)      # 30 min after normal close
```

APScheduler doesn't natively support variable run times. Solution: schedule at earliest possible time (13:30) and check market close at runtime:

```python
# Scheduled at 13:30 every day
def daily_pipeline_wrapper():
    today = date.today()
    if not market_calendar.is_trading_day(today):
        return  # Holiday

    if market_calendar.is_early_close(today):
        daily_pipeline.run()  # Run now (13:30)
    else:
        # Normal day — wait until 16:30
        # APScheduler's main job at 16:30 will handle this
        return
```

Alternative (simpler): run two scheduler jobs — one at 13:30 for early close days, one at 16:30 for normal days. Each checks the calendar and skips if not applicable.

---

## 10. Logging & Observability

### 10.1 Logging Configuration

```python
from loguru import logger

# Console + file logging
logger.add("logs/vrp_{time:YYYY-MM-DD}.log",
           rotation="1 day",
           retention="90 days",
           format="{time:HH:mm:ss} | {level} | {module}:{function} | {message}")

# Separate error log
logger.add("logs/errors_{time:YYYY-MM-DD}.log",
           level="WARNING",
           rotation="1 day",
           retention="180 days")
```

### 10.2 Structured Log Events

Every significant event is logged with structured data:

```python
# Pipeline start
logger.info("pipeline.start", pipeline="daily", date=str(date.today()))

# Step completion
logger.info("step.complete", step="heston_calibration",
            status="OK", rmse=0.003, duration_sec=8.2,
            params={"v0": 0.024, "kappa": 2.1})

# Failure with retry
logger.warning("step.retry", step="data_fetch_vix",
               attempt=2, max_attempts=3, error="Timeout")

# Trade execution
logger.info("trade.entered", short_strike=5200, long_strike=5100,
            premium=7.20, n_contracts=5, f_final=0.82)

# Alert sent
logger.info("alert.sent", level="CRITICAL", title="DD > 5%",
            channel="email")
```

### 10.3 Metrics Dashboard (SQLite Queries)

Key queries for notebook-based monitoring:

```sql
-- Pipeline success rate (last 30 days)
SELECT status, COUNT(*) as count
FROM pipeline_runs
WHERE pipeline_id = 'daily_pipeline' AND run_date > date('now', '-30 days')
GROUP BY status;

-- Calibration health trend
SELECT run_date,
       json_extract(step_results, '$.pricing') as cal_status
FROM pipeline_runs
WHERE pipeline_id = 'daily_pipeline'
ORDER BY run_date DESC LIMIT 30;

-- Alert frequency by level
SELECT level, COUNT(*) as count
FROM alerts
WHERE timestamp > date('now', '-30 days')
GROUP BY level;

-- Average pipeline duration trend
SELECT strftime('%W', run_date) as week, AVG(duration_sec) as avg_sec
FROM pipeline_runs
WHERE pipeline_id = 'daily_pipeline'
GROUP BY week ORDER BY week;
```

---

## 11. System Lifecycle

### 11.1 Startup Sequence

```
1. Load config/settings.yaml
2. Initialize SQLite database (create tables if not exist)
3. Initialize data fetchers (FRED, Yahoo, Polygon)
4. Initialize regime detector (load latest HMM + XGBoost from disk)
5. Initialize pricing engine (Heston calibrator, BS pricer)
6. Initialize risk management chain
7. Initialize alert system (test email delivery)
8. Initialize IBKR broker (Phase 3+: connect and verify)
9. Register scheduler jobs
10. Start scheduler

Output: "VRP System started. Mode: {paper|live}. Phase: {1|2|3|4}."
```

### 11.2 Graceful Shutdown

```
1. Stop scheduler (no new jobs)
2. Wait for any running pipeline to complete (up to 5 min)
3. Disconnect IBKR (if connected)
4. Save final state to SQLite
5. Send INFO alert: "System shutting down gracefully"
6. Close database connections
7. Exit

Trigger: SIGTERM, SIGINT, or scripts/kill.py
```

### 11.3 Crash Recovery

```
On startup, check for stale state:
1. Any pipeline_locks with completed=0?
   → Clear stale locks (see Section 8.2)
   → Log WARNING: "Recovered from previous crash"

2. Any incomplete trades (entry logged, no exit)?
   → Check IBKR for actual position state
   → Reconcile: if position exists in IBKR but not in DB, add to DB
   → If position in DB but not in IBKR, mark as manually closed
   → CRITICAL alert: "Position reconciliation required"

3. Continue normal operation from next scheduled job.
```

### 11.4 Mode Transitions

```
Phase 1 → Phase 2:
  Config change: phase = 2
  New: Polygon.io API key, pricing modules activated
  Restart system.

Phase 2 → Phase 3:
  Config change: phase = 3, execution.mode = paper
  New: IBKR paper connection, orchestrator + alerts activated
  First run: verify IBKR connection, send test alert
  Restart system.

Phase 3 → Phase 4:
  Config change: execution.mode = live, execution.ibkr.port = 7496
  Config change: risk parameters tightened (Stage 1)
  Restart system.
  CONFIRMATION REQUIRED on startup (interactive "CONFIRM LIVE" prompt).

Phase 4 Stage 1 → Stage 2:
  Config change: risk parameters restored to standard
  Git commit with rationale.
  Restart system.
```
