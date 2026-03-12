# Phase 3 — Paper Trading

**Goal: Prove the system operates correctly in real-time before risking real money.**

> Phase 3 activates only after Phase 2 GO verdict.
> Connects to IBKR paper trading account. Real market data, simulated fills.
> Orchestration, alerts, and daily reports go live for the first time.
> The question Phase 3 answers: "Does the system run reliably day after day, and do live signals match backtest signals?"
> Phase 3 is NOT about P&L. It's about operational reliability.
> Minimum duration: 4 weeks. Do not rush to Phase 4.

---

## Table of Contents

1. [Phase Scope](#1-phase-scope)
2. [Prerequisites](#2-prerequisites)
3. [Module Activation Map](#3-module-activation-map)
4. [IBKR Setup](#4-ibkr-setup)
5. [Task Breakdown](#5-task-breakdown)
6. [Orchestration & Daily Operations](#6-orchestration--daily-operations)
7. [Signal Concordance Testing](#7-signal-concordance-testing)
8. [Operational Validation](#8-operational-validation)
9. [GO / NO-GO Criteria](#9-go--no-go-criteria)
10. [Deliverables & Completion Checklist](#10-deliverables--completion-checklist)

---

## 1. Phase Scope

### 1.1 What Phase 3 Does

- Connects to IBKR paper trading account via `ib_insync`
- Runs the full daily pipeline automatically (data → regime → pricing → monitor → alerts)
- Executes weekly entries and exits on paper account with simulated fills
- Sends daily report emails and critical alerts
- Validates signal concordance: do live signals match what the backtest would have produced?
- Validates operational reliability: does the pipeline run without crashing for 4+ weeks?
- Validates execution mechanics: orders placed correctly, fills tracked, slippage logged
- Validates failure handling: fallbacks work when APIs go down or calibration fails

### 1.2 What Phase 3 Does NOT Do

| Not in Phase 3 | Why | When |
|----------------|-----|------|
| Real money | Must prove reliability first | Phase 4 |
| Full capital sizing | Paper account size is arbitrary | Phase 4 |
| Performance evaluation for P&L | Paper fills are unrealistic for P&L | Phase 4 |
| PINN / Research system | Production must work first | Post Phase 4 |

### 1.3 Key Mindset Shift

Phase 1-2 were batch backtests — run once, analyze results. Phase 3 is a **continuously running system**. This introduces entirely new failure modes:

- API rate limits and timeouts
- Market holidays and early closes
- Data feed gaps and stale quotes
- IBKR disconnections and reconnections
- Overnight parameter staleness
- Scheduler missed jobs (machine sleep, crash, restart)
- Concurrent position monitoring while entering new trades

None of these exist in backtesting. Phase 3 is where they surface.

---

## 2. Prerequisites

### 2.1 Phase 2 Must Be Complete

```
[] Phase 2 verdict = GO (all 16 checks passed)
[] Heston calibration pipeline validated (>95% success rate)
[] Strategy engine validated (entry, strike selection, exits)
[] Transaction cost model validated
[] All Phase 2 code committed and tested
```

### 2.2 IBKR Account Ready

```
[] IBKR account opened and approved
[] Paper trading enabled (separate login credentials)
[] Market data subscriptions active:
    -> US Securities Snapshot & Futures Value Bundle (for SPX)
    -> US Equity and Options Add-On (for SPX options chain)
[] TWS or IB Gateway installed and configured
    -> Paper trading port: 7497
    -> API connections enabled in TWS settings
[] ib_insync tested: can connect, fetch quotes, place test orders
```

### 2.3 Infrastructure Ready

```
[] Dedicated machine (or VM) that runs during market hours
    -> Doesn't need to be 24/7 (options are US market hours only)
    -> Must be reliable 16:00-18:00 ET daily (pipeline window)
    -> Recommendation: always-on desktop or cheap VPS
[] SMTP email configured and tested (for alerts + daily report)
[] SQLite database initialized (trade log, alert history)
```

---

## 3. Module Activation Map

| Module | Phase 2 | Phase 3 | Change |
|--------|---------|---------|--------|
| `src/data/*` | Active | Active | No change |
| `src/regime/*` | Active | Active | No change |
| `src/pricing/*` | Active | Active | No change |
| `src/strategy/*` | Active | Active | No change |
| `src/risk/*` | Active | Active | No change |
| `src/backtest/*` | Active | Active | Used for concordance checks |
| `src/execution/broker.py` | Inactive | **Active** | New: IBKRBroker (paper mode) |
| `src/execution/order_manager.py` | Inactive | **Active** | New: order construction + submission |
| `src/execution/fill_tracker.py` | Inactive | **Active** | New: fill tracking + slippage log |
| `src/execution/paper_trader.py` | Inactive | **Active** | New: paper trade simulation wrapper |
| `src/orchestrator/scheduler.py` | Inactive | **Active** | New: APScheduler job definitions |
| `src/orchestrator/daily_pipeline.py` | Inactive | **Active** | New: EOD pipeline |
| `src/orchestrator/weekly_pipeline.py` | Inactive | **Active** | New: entry/execution pipeline |
| `src/orchestrator/monthly_pipeline.py` | Inactive | **Active** | New: HMM refit pipeline |
| `src/orchestrator/failure_handler.py` | Inactive | **Active** | New: retry/fallback/escalation |
| `alerts/manager.py` | Inactive | **Active** | New: alert routing |
| `alerts/email_sender.py` | Inactive | **Active** | New: SMTP dispatch |

**Every module is now active.** Phase 3 is the first time the complete system runs.

---

## 4. IBKR Setup

### 4.1 Connection Architecture

```
TWS / IB Gateway (paper mode, port 7497)
        |
   ib_insync (Python wrapper)
        |
   IBKRBroker (src/execution/broker.py)
        |
   OrderManager → FillTracker
```

### 4.2 IBKRBroker Interface

```python
class IBKRBroker:
    def __init__(self, mode: str = 'paper'):
        """mode: 'paper' (port 7497) or 'live' (port 7496)
        Phase 3 ALWAYS uses 'paper'. Hard-coded safety check."""
        assert mode == 'paper', "Phase 3 must use paper mode"

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...

    def get_spx_price(self) -> float: ...
    def get_account_value(self) -> float: ...
    def get_positions(self) -> list[Position]: ...

    def get_option_quote(self, strike: float, expiry: date,
                         right: str = 'P') -> OptionQuote: ...

    def place_spread_order(self, short_strike: float, long_strike: float,
                           expiry: date, n_contracts: int,
                           limit_price: float) -> Order: ...

    def close_spread(self, order_id: int, urgency: str = 'normal') -> Order:
        """normal: limit at mid. urgent: market order."""

    def cancel_order(self, order_id: int) -> bool: ...
```

### 4.3 Safety Guards

```python
# Hard-coded in IBKRBroker.__init__():
MAX_CONTRACTS_PAPER = 50          # Never place more than 50 spreads
MAX_ORDER_VALUE_PAPER = 100_000   # Never exceed $100K notional
ALLOWED_UNDERLYINGS = ['SPX']     # Only SPX options
ALLOWED_RIGHTS = ['P']            # Only puts (for put spreads)

# In OrderManager:
def validate_order(self, order) -> bool:
    """Pre-flight checks before any order submission:
    1. mode == 'paper' (Phase 3 guard)
    2. n_contracts <= MAX_CONTRACTS_PAPER
    3. underlying in ALLOWED_UNDERLYINGS
    4. Both legs are puts
    5. Short strike > long strike (valid spread direction)
    6. DTE >= 7 (no last-minute entries)
    7. Limit price > 0 (no zero-credit entries)
    """
```

---

## 5. Task Breakdown

### Sprint 9: IBKR Execution Layer (4-5 days)

**Task 9.1 — IBKRBroker Implementation**

```
Input:  Connection params (host, port, client_id)
Output: Connected broker with paper trading access

Test: Connect to paper TWS on port 7497
  -> is_connected() returns True
Test: get_spx_price()
  -> Returns current SPX level (within market hours)
  -> Returns last close (outside market hours)
Test: get_account_value()
  -> Returns paper account value (default $1M for IBKR paper)
Test: get_option_quote(strike=5200, expiry=date(2026,4,17), right='P')
  -> Returns bid, ask, mid, IV, delta, volume
  -> Bid > 0, Ask > Bid
```

**Task 9.2 — Order Manager**

```
Input:  PutCreditSpread + n_contracts + limit_price
Output: Submitted order with tracking ID

Test: Place paper spread order
  -> Order accepted by IBKR paper engine
  -> Order appears in open orders list
  -> Fill received within seconds (paper fills are instant)
Test: Safety guards reject invalid orders:
  -> n_contracts = 100 -> REJECTED (exceeds MAX_CONTRACTS_PAPER)
  -> underlying = 'AAPL' -> REJECTED (not in ALLOWED_UNDERLYINGS)
  -> short_strike < long_strike -> REJECTED (invalid spread)
```

**Task 9.3 — Fill Tracker**

```
Input:  Submitted order
Output: Fill record with actual prices + slippage calculation

Test: After paper fill:
  -> fill.avg_price recorded
  -> fill.slippage = |fill.avg_price - expected_mid|
  -> Fill logged to SQLite trades table
```

**Task 9.4 — Paper Trader Wrapper**

Coordinates IBKRBroker with strategy decisions.

```
Input:  EntryResult + PutCreditSpread + LeverageResult
Output: Executed paper trade (or documented skip)

Test: Full cycle:
  -> Entry decision = GO, 12 spreads
  -> Order placed at mid-price
  -> Fill received, logged to DB
  -> Position appears in get_positions()
```

### Sprint 10: Orchestration (4-5 days)

**Task 10.1 — Scheduler**

```python
scheduler = APScheduler()

# Daily jobs (market days only)
scheduler.add_job(daily_pipeline.run, 'cron',
                  day_of_week='mon-fri', hour=16, minute=30,
                  timezone='US/Eastern')

# Weekly entry (Tuesday)
scheduler.add_job(weekly_pipeline.run, 'cron',
                  day_of_week='tue', hour=17, minute=15,
                  timezone='US/Eastern')

# Monthly refit (1st trading day)
scheduler.add_job(monthly_pipeline.run, 'cron',
                  day=1, hour=18, minute=0,
                  timezone='US/Eastern')
```

```
Test: Scheduler fires daily job at 16:30 ET on weekdays
Test: Scheduler skips weekends and market holidays
Test: If machine was off during scheduled time, job runs on next startup
      (APScheduler misfire_grace_time configuration)
```

**Task 10.2 — Daily Pipeline**

```python
class DailyPipeline:
    def run(self) -> PipelineResult:
        step_results = {}

        # Step 1: Data fetch
        data = self._fetch_data()
        step_results['data'] = data.status

        # Step 2: Feature computation
        features = self._compute_features(data)
        step_results['features'] = 'OK' if not features.has_nan else 'WARN'

        # Step 3: Heston calibration
        cal = self._calibrate(data.options_chain)
        step_results['calibration'] = cal.status

        # Step 4: Regime detection
        regime = self._detect_regime(features)
        step_results['regime'] = regime.regime

        # Step 5: Position monitoring + exits
        exits = self._monitor_and_exit(regime, cal.vol_surface)
        step_results['exits'] = exits.summary

        # Step 6: Daily report
        self._send_report(step_results)

        # Step 7: Log to DB
        self._log_to_db(step_results)

        return PipelineResult(steps=step_results)
```

```
Test: Run daily pipeline manually
  -> All 7 steps complete without error
  -> Daily report email received
  -> DB entry created
Test: Simulate data fetch failure
  -> Retry 3x, then cache fallback
  -> WARNING alert sent
  -> Downstream steps still run (with cached data)
Test: Simulate Heston calibration failure
  -> Fallback to prev day params
  -> WARNING alert sent
  -> Position monitoring still runs
```

**Task 10.3 — Weekly Pipeline**

```python
class WeeklyPipeline:
    def run(self) -> PipelineResult:
        # Depends on daily pipeline having already run today

        # Step 1: Entry decision
        entry = self._evaluate_entry()
        if not entry.enter:
            return PipelineResult(action='SKIP', reason=entry.reason)

        # Step 2: Strike selection
        spread = self._construct_spread(entry)

        # Step 3: Risk sizing
        leverage = self._compute_leverage()
        n_contracts = self._size_position(leverage, spread)

        # Step 4: Execute via IBKR paper
        order = self._execute(spread, n_contracts)

        # Step 5: Log trade
        self._log_trade(spread, order, leverage)

        return PipelineResult(action='ENTERED', trade=order)
```

```
Test: Weekly pipeline on Tuesday
  -> If entry conditions met: spread order placed, fill logged
  -> If conditions not met: skip logged with reason
Test: Weekly pipeline on non-Tuesday
  -> Does not run (scheduler guard)
Test: If open position exists
  -> Skip entry (no stacking positions in Phase 3)
```

**Task 10.4 — Monthly Pipeline**

```
Tasks: HMM refit, label stability check, cache cleanup

Test: HMM refits with expanded data
  -> Label stability >= 90% (or defers retraining)
  -> XGBoost retrained on new labels
Test: Old cache files cleaned (> 90 days for raw data)
```

**Task 10.5 — Failure Handler**

```python
class FailureHandler:
    def handle(self, step: str, error: Exception) -> FailureAction:
        """Returns: RETRY, FALLBACK, SKIP, HALT, ALERT"""

    def retry(self, func, max_retries=3, delay_sec=300) -> Any: ...
```

```
Test: Data fetch timeout -> retry 3x with 5min delay -> cache fallback
Test: IBKR disconnect during order -> retry 3x with 1min delay -> CRITICAL alert
Test: Pipeline crash -> alert sent, next scheduled run still fires
```

### Sprint 11: Alerts & Monitoring (2-3 days)

**Task 11.1 — Alert Manager**

```python
class AlertManager:
    def send(self, level: str, title: str, body: str) -> None:
        """Routes alert based on level:
        INFO -> DB only
        WARNING -> DB + email
        CRITICAL -> DB + email (+ SMS if configured)
        EMERGENCY -> DB + email + SMS + trigger kill switch review
        """
```

```
Test: INFO alert -> DB entry, no email
Test: WARNING alert -> DB entry + email received
Test: CRITICAL alert -> DB entry + email with [CRITICAL] prefix
```

**Task 11.2 — Daily Report Email**

```
Test: Report email sent at ~17:00 ET
Test: Report contains: regime, VRP, position status, Greeks, DD, risk factors,
      pipeline step status, next action
Test: If no open position: report shows "No position. Next entry: Tuesday."
Test: If position open: report shows M2M P&L, Greeks, exit trigger proximity
```

**Task 11.3 — Trade Logger (SQLite)**

```sql
-- trades table
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    entry_date TEXT,
    exit_date TEXT,
    short_strike REAL,
    long_strike REAL,
    expiry TEXT,
    n_contracts INTEGER,
    entry_premium REAL,
    exit_price REAL,
    pnl REAL,
    exit_reason TEXT,
    regime_at_entry TEXT,
    regime_at_exit TEXT,
    f_final REAL,
    slippage REAL
);

-- daily_snapshots table
CREATE TABLE daily_snapshots (
    date TEXT PRIMARY KEY,
    regime TEXT,
    p_lv REAL, p_nv REAL, p_hv REAL,
    vix REAL, rv_21 REAL, vrp_proxy REAL, z_vrp REAL,
    f_vol REAL, f_kelly REAL, f_dd REAL, f_final REAL,
    account_value REAL, drawdown REAL,
    position_pnl REAL,
    calibration_status TEXT,
    pipeline_status TEXT
);

-- alerts table
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    level TEXT,
    title TEXT,
    body TEXT,
    acknowledged INTEGER DEFAULT 0
);
```

```
Test: After daily pipeline: new row in daily_snapshots
Test: After trade entry: new row in trades (exit fields NULL)
Test: After trade exit: trades row updated with exit fields
Test: Query: SELECT * FROM trades WHERE exit_reason = 'stop_loss'
```

---

## 6. Orchestration & Daily Operations

### 6.1 Daily Schedule

```
16:00 ET  Market closes
16:15     IBKR EOD data available
16:30     === DAILY PIPELINE START ===
16:30       Step 1: Fetch EOD data (SPX, VIX, VIX3M, VVIX)
16:32       Step 2: Fetch options chain (Polygon.io)
16:35       Step 3: Compute features
16:37       Step 4: Heston calibration
16:42       Step 5: Regime detection
16:44       Step 6: Position monitoring + exit triggers
16:46       Step 7: Execute exits (if triggered)
16:50     === DAILY PIPELINE END ===
16:55       Daily report email sent

17:15     === WEEKLY PIPELINE (Tuesday only) ===
17:15       Step 1: Entry decision
17:17       Step 2: Strike selection + spread construction
17:19       Step 3: Risk sizing (min-chain)
17:21       Step 4: Place order via IBKR paper
17:25       Step 5: Wait for fill + log
17:30     === WEEKLY PIPELINE END ===
```

### 6.2 Weekend / Holiday Handling

```
Friday EOD:  Normal daily pipeline runs. If position open, monitoring as usual.
Saturday:    Nothing. Scheduler does not fire.
Sunday:      Nothing.
Monday:      Normal daily pipeline. No weekly entry (Tuesday only).

Market holidays: Scheduler checks market calendar before running.
  -> If holiday: skip all pipelines, log INFO "Market holiday, pipeline skipped."
  -> Half days (early close at 13:00 ET): pipeline runs at 13:30 ET instead.
```

### 6.3 IBKR Connection Management

```
Connection strategy:
  -> Connect at 16:25 ET (5 min before pipeline)
  -> Disconnect at 17:45 ET (after all pipelines complete)
  -> No persistent connection (reduce disconnection risk)

If connection fails at 16:25:
  -> Retry 3x with 1min delay
  -> If still fails: run pipeline WITHOUT execution (data + regime + monitoring only)
  -> CRITICAL alert: "IBKR connection failed. No orders placed."
  -> Manual intervention required before next trading day

If connection drops mid-pipeline:
  -> If during monitoring: complete with cached data, CRITICAL alert
  -> If during order execution: order may be orphaned
     -> On reconnection: check open orders, reconcile with intended trades
     -> EMERGENCY alert: "IBKR disconnected during execution. Reconcile required."
```

### 6.4 Human Operational Duties

Phase 3 is not fully hands-off. Daily operator duties:

```
Daily (2 min):
  -> Read daily report email
  -> Confirm: pipeline OK, no critical alerts
  -> If CRITICAL alert: investigate within 1 hour

Weekly (10 min):
  -> Review week's trades in SQLite
  -> Check: entry/exit reasons reasonable?
  -> Check: slippage within expected range?
  -> Compare: regime transition makes sense given market?

Monthly (30 min):
  -> HMM refit results review
  -> Concordance check (Section 7)
  -> Cumulative operational metrics review
```

---

## 7. Signal Concordance Testing

### 7.1 Purpose

The most important Phase 3 validation: **do live signals match what the backtest would have produced?**

If the live system makes different decisions than the backtest on the same data, something is wrong — look-ahead bias in the backtest, a data timing issue, a code bug in the live pipeline, or a fundamental architecture mismatch.

### 7.2 Methodology

Run Phase 2 backtest engine in parallel on the same dates that the live system is running:

```python
# Every Sunday night, after the week's live trading:
for day in this_week.trading_days:
    # Reconstruct what the backtest would have done
    bt_regime = backtest_engine.compute_regime(day)
    bt_entry = backtest_engine.compute_entry(day)
    bt_strike = backtest_engine.compute_strike(day)

    # Compare against what the live system actually did
    live_regime = db.get_daily_snapshot(day).regime
    live_entry = db.get_trade(day)  # or None if skipped
    live_strike = live_entry.short_strike if live_entry else None

    # Log concordance
    concordance_log.append({
        'date': day,
        'regime_match': bt_regime == live_regime,
        'entry_match': bt_entry.enter == (live_entry is not None),
        'strike_match': bt_strike == live_strike if both exist else N/A,
    })
```

### 7.3 Concordance Metrics

| Metric | Target | Concern if |
|--------|--------|-----------|
| Regime agreement | > 95% of days | < 90% |
| Entry/skip agreement | > 95% of weeks | < 90% |
| Strike agreement (when both enter) | > 90% of entries | < 80% |
| Risk factor (f_final) correlation | > 0.95 | < 0.90 |

### 7.4 Diagnosing Discrepancies

**Regime mismatch:**
- Check: is the feature data identical? (same source, same timestamps)
- Check: XGBoost model is the same version in both
- Most common cause: data timing — live uses 16:00 close, backtest may use different cut

**Entry mismatch:**
- Check: same regime, same VRP z-score, same premium ratio
- Check: is the options chain data identical? (Polygon EOD vs IBKR real-time quote)
- Most common cause: slight bid-ask differences between Polygon historical and IBKR real-time

**Strike mismatch:**
- Check: vol surface calibration produces same parameters
- Check: Newton-Raphson converges to same strike
- Acceptable: ±1 strike increment ($5 for SPX) due to rounding differences

### 7.5 Acceptable Discrepancy Sources

Not all discrepancies indicate bugs:

| Source | Expected? | Action |
|--------|-----------|--------|
| Data timing (16:00 vs 16:15 close) | Yes | Document, don't fix |
| Polygon EOD vs IBKR real-time quote | Yes | Document, use Polygon as reference |
| Strike rounding (±$5) | Yes | Accept if within 1 increment |
| Heston calibration non-determinism | Possible | Check: params within 5% of backtest |
| Different VIX snapshot time | Possible | Standardize to FRED EOD |

---

## 8. Operational Validation

### 8.1 Week 1-2: System Stability

Focus: does the pipeline run without crashing?

```
[] Daily pipeline completes successfully for 10 consecutive trading days
[] No unhandled exceptions in any pipeline step
[] Scheduler fires all jobs within ±5 min of scheduled time
[] IBKR connection succeeds on first attempt > 90% of days
[] Daily report email received every trading day
[] SQLite database growing correctly (new rows daily)
[] No memory leaks (process memory stable over 2 weeks)
[] Log files don't grow unbounded (rotation working)
```

### 8.2 Week 2-3: Execution Mechanics

Focus: do orders work correctly?

```
[] At least 2 spread entries placed and filled on paper
[] At least 1 exit trigger fired (profit target or DTE)
[] Order fill prices logged correctly
[] Position appears in IBKR paper account
[] Position removed after close
[] Slippage calculation produces reasonable numbers
[] Safety guards tested:
    -> Intentionally try to exceed MAX_CONTRACTS -> rejected
    -> Intentionally try live mode -> rejected (assert fails)
```

### 8.3 Week 3-4: Signal Concordance

Focus: live matches backtest.

```
[] Weekly concordance check running
[] Regime agreement > 95%
[] Entry/skip agreement > 95%
[] All discrepancies documented with root cause
[] No unexplained discrepancies remaining
```

### 8.4 Week 4+: Failure Recovery

Focus: does the system handle problems gracefully?

```
[] Intentional tests:
    -> Kill IBKR TWS mid-pipeline -> pipeline completes without crash,
       CRITICAL alert sent, reconnects next day
    -> Block Polygon.io API -> data fetch fails, cache fallback used,
       WARNING alert, pipeline continues
    -> Block FRED API -> same pattern
    -> Set Heston max_iter=1 -> calibration "fails", fallback to prev day,
       WARNING alert
    -> Set DD to 11% manually -> f_dd = 0, kill switch triggers,
       position closed (or would be if open)
    -> Reboot machine during pipeline -> next scheduled run picks up,
       missed job handled by APScheduler misfire grace
[] All failures produce appropriate alerts
[] No failure leaves the system in an undefined state
[] System recovers automatically after transient failures
```

### 8.5 Continuous: Data Consistency

```
[] Polygon.io chain data matches IBKR real-time quotes (within bid-ask)
[] VIX from FRED matches market data (within 0.5%)
[] SPX close from Yahoo matches IBKR (within 0.1%)
[] No stale data used (all timestamps are today's date)
[] Feature computation produces same values as Phase 2 backtest
    for the same date (within floating-point tolerance)
```

---

## 9. GO / NO-GO Criteria

Phase 3 criteria are operational, not performance-based. P&L on paper is NOT evaluated because paper fills are unrealistic.

### 9.1 System Stability (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 1 | Consecutive days without crash | >= 20 | < 20 |
| 2 | Daily pipeline success rate | > 95% | <= 95% |
| 3 | Daily report delivery rate | 100% | < 100% |
| 4 | IBKR connection success rate | > 90% | <= 90% |
| 5 | Unhandled exceptions | 0 | > 0 |

### 9.2 Execution Mechanics (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 6 | Paper trades placed successfully | >= 3 | < 3 |
| 7 | Paper exits executed correctly | >= 1 | 0 |
| 8 | Order safety guards tested | All passed | Any failed |
| 9 | Fill tracking accurate | 100% of trades | < 100% |

### 9.3 Signal Concordance (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 10 | Regime agreement (live vs backtest) | > 95% | <= 90% |
| 11 | Entry/skip agreement | > 95% | <= 90% |
| 12 | Strike agreement (when both enter) | > 90% | <= 80% |
| 13 | All discrepancies explained | Yes | No |

### 9.4 Failure Recovery (ALL must pass)

| # | Check | GO | NO-GO |
|---|-------|-----|-------|
| 14 | IBKR disconnect recovery | Tested + passed | Not tested |
| 15 | Data source failure recovery | Tested + passed | Not tested |
| 16 | Calibration failure fallback | Tested + passed | Not tested |
| 17 | Kill switch (DD override) | Tested + passed | Not tested |

### 9.5 Minimum Duration

| Check | GO | NO-GO |
|-------|-----|-------|
| Total paper trading days | >= 20 trading days (4 weeks) | < 20 |
| Includes at least one period of elevated VIX (>20) | Yes | No* |

*If VIX stays below 20 for the entire Phase 3 period, this check becomes CONDITIONAL — the system hasn't been tested under stress. Either extend Phase 3 until a vol event occurs, or proceed to Phase 4 with extra caution and tighter DD limits.

### 9.6 Verdict Logic

```
if ALL 17 checks pass AND duration >= 20 days:
    VERDICT = GO -> Phase 4 (Live Trading)
    Action: Switch IBKR to live mode, start with minimum capital

elif stability + execution pass but concordance has issues:
    VERDICT = CONDITIONAL
    Action: Fix concordance issues, extend Phase 3 by 2 weeks, re-evaluate

elif any stability or execution check fails:
    VERDICT = NO-GO
    Action: Fix the operational issue. Do not proceed until 20 consecutive
            stable days are achieved.
    This is NOT a strategy failure — it's an engineering failure.
    The strategy may be fine; the system just can't run it reliably yet.
```

---

## 10. Deliverables & Completion Checklist

### 10.1 Code

```
[] src/execution/broker.py         — IBKRBroker with paper mode guard
[] src/execution/order_manager.py  — Order construction + safety validation
[] src/execution/fill_tracker.py   — Fill tracking + slippage logging
[] src/execution/paper_trader.py   — Paper trade coordination
[] src/orchestrator/scheduler.py   — APScheduler job definitions
[] src/orchestrator/daily_pipeline.py  — Full daily EOD pipeline
[] src/orchestrator/weekly_pipeline.py — Tuesday entry pipeline
[] src/orchestrator/monthly_pipeline.py — HMM refit pipeline
[] src/orchestrator/failure_handler.py — Retry/fallback/escalation
[] alerts/manager.py               — Alert routing by severity
[] alerts/email_sender.py          — SMTP email dispatch
[] scripts/run_system.py           — Main entry point (starts scheduler)
[] scripts/concordance_check.py    — Weekly concordance analysis
[] scripts/kill.py                 — CLI emergency kill switch
```

### 10.2 Infrastructure

```
[] SQLite database schema (trades, daily_snapshots, alerts)
[] IBKR TWS/Gateway configuration documented
[] Market holiday calendar integrated
[] Log rotation configured
[] Process monitoring (systemd or equivalent)
```

### 10.3 Analysis

```
[] notebooks/05_live_monitoring.ipynb
    — Equity curve (paper), regime timeline
    — Concordance dashboard (regime, entry, strike agreement %)
    — Operational metrics (pipeline success rate, connection rate)
    — Failure event timeline
    — Data consistency checks

[] Concordance report (generated weekly by scripts/concordance_check.py)
    — Day-by-day comparison: live vs backtest
    — Discrepancy root causes
    — Aggregate agreement metrics
```

### 10.4 Documents

```
[] Phase 3 verdict document (GO / CONDITIONAL / NO-GO)
    — All 17 checks with actual values
    — Duration and market conditions during paper trading
    — Concordance summary
    — Operational incident log
    — If GO: Phase 4 readiness assessment + recommended starting capital
    — If NO-GO: specific engineering fixes required
```

### 10.5 Operational Documentation

```
[] Runbook: how to start/stop the system
[] Runbook: what to do when CRITICAL alert received
[] Runbook: how to manually override a trade decision
[] Runbook: how to update parameters without restarting
[] Runbook: disaster recovery (machine crash, data corruption)
```

### 10.6 Timeline

| Sprint | Tasks | Duration |
|--------|-------|----------|
| Sprint 9 | IBKR execution layer | 4-5 days |
| Sprint 10 | Orchestration (scheduler, pipelines, failure handling) | 4-5 days |
| Sprint 11 | Alerts, daily report, trade logger | 2-3 days |
| Sprint 12 | Paper trading operation (minimum 4 weeks) | 20+ trading days |
| **Total** | | **10-13 days dev + 20+ days operation** |

### 10.7 Dependencies

```
Phase 2 (all) --> Sprint 9 (needs strategy + pricing)
Sprint 9 --> Sprint 10 (orchestration needs execution layer)
Sprint 10 --> Sprint 11 (alerts depend on pipeline events)
Sprint 9 + 10 + 11 --> Sprint 12 (paper trading needs everything)
```

```
Sprint 9 --> Sprint 10 --> Sprint 11 --> Sprint 12 (4+ weeks live)
```

Sprints 9-11 are sequential: each depends on the previous. Sprint 12 (paper trading) is a continuous operational period, not a development sprint.
