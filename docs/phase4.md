# Phase 4 — Live Trading

**Goal: Make money. Carefully.**

> Phase 4 activates only after Phase 3 GO verdict.
> Switches IBKR from paper to live mode. Real money, real fills, real consequences.
> Starts with minimum capital and scales up gradually based on evidence.
> The question Phase 4 answers: "Does this system generate real profit with acceptable risk?"
> There is no Phase 5. Phase 4 is the steady state. Success means running indefinitely.

---

## Table of Contents

1. [Phase Scope](#1-phase-scope)
2. [Prerequisites](#2-prerequisites)
3. [Capital Staging](#3-capital-staging)
4. [Code Changes from Phase 3](#4-code-changes-from-phase-3)
5. [Risk Parameter Tightening](#5-risk-parameter-tightening)
6. [Operational Procedures](#6-operational-procedures)
7. [Performance Tracking](#7-performance-tracking)
8. [Scaling Criteria](#8-scaling-criteria)
9. [Failure Modes & Emergency Procedures](#9-failure-modes--emergency-procedures)
10. [Ongoing Maintenance](#10-ongoing-maintenance)
11. [When to Stop](#11-when-to-stop)

---

## 1. Phase Scope

### 1.1 What Phase 4 Does

- Switches IBKR broker mode from `paper` to `live`
- Trades with real capital, starting at minimum viable size
- Tracks real P&L, real slippage, real commissions
- Compares live performance against Phase 2 backtest expectations
- Scales capital gradually based on evidence (3-stage ramp)
- Operates indefinitely as the production trading system

### 1.2 What Changes from Phase 3

| Aspect | Phase 3 | Phase 4 |
|--------|---------|---------|
| IBKR mode | Paper (port 7497) | Live (port 7496) |
| Fills | Simulated (instant, no slippage) | Real (market fills, actual slippage) |
| Capital | Arbitrary ($1M paper default) | Real, staged ($5K → $25K → full) |
| P&L | Not evaluated | Primary evaluation metric |
| Risk params | Standard | Tightened for Stage 1 |
| Operational rigor | Learning mode | Production mode |
| Concordance check | vs backtest | vs backtest + vs paper trading record |

### 1.3 What Does NOT Change

- All code modules (data, regime, pricing, strategy, risk, orchestration)
- Daily/weekly/monthly schedule
- Alert system and daily reports
- Failure handling and fallback chains
- Monitoring and logging

The system is identical to Phase 3 except for the broker mode switch and tightened risk parameters.

---

## 2. Prerequisites

### 2.1 Phase 3 Must Be Complete

```
[] Phase 3 verdict = GO (all 17 checks passed)
[] >= 20 trading days of stable paper operation
[] Signal concordance verified (regime > 95%, entry > 95%)
[] All failure recovery tests passed
[] Operational runbooks written and tested
[] No unresolved operational issues
```

### 2.2 IBKR Live Account Ready

```
[] IBKR live account funded with Stage 1 capital ($5K-$10K)
[] Options trading permissions enabled (Level 2+: spreads)
[] SPX options market data subscription active
[] Live trading API enabled in TWS settings (port 7496)
[] Tax reporting setup (Section 1256 for SPX — 60/40 treatment)
[] Understand: Pattern Day Trader rules do NOT apply to options spreads
    on cash-settled index options (SPX), but verify with IBKR
```

### 2.3 Personal Readiness

```
[] Capital is money you can afford to lose entirely
[] You will not panic-sell on a bad week
[] You understand the maximum loss scenario:
    -> Worst case per spread: W - Π (defined at entry)
    -> Worst case for account: DD kill at 10% → max loss ~10% of account
    -> True worst case (kill switch failure + gap): larger, but very unlikely
[] You have reviewed the Phase 2 crisis analysis and accept the risk profile
[] Daily 2-minute commitment for report review is sustainable
```

---

## 3. Capital Staging

### 3.1 Three-Stage Ramp

Real money is deployed in three stages. Each stage requires evidence before advancing.

**Stage 1: Minimum Viable ($5K-$10K)**

```
Duration: 4-8 weeks minimum
Position size: 1-3 spreads per entry
Purpose: Verify real execution matches paper
Evaluate: Real slippage, real fills, real commissions
Risk params: TIGHTENED (see Section 5)
```

**Stage 2: Intermediate ($15K-$25K)**

```
Duration: 2-3 months minimum
Position size: 3-8 spreads per entry
Purpose: Verify P&L trajectory matches backtest expectations
Evaluate: Sharpe, MDD, win rate against Phase 2 benchmarks
Risk params: STANDARD (same as Phase 2 backtest)
```

**Stage 3: Full Capital ($50K+)**

```
Duration: Indefinite (production steady state)
Position size: 8-20+ spreads per entry (depends on account size)
Purpose: Full-scale operation
Evaluate: Ongoing quarterly review
Risk params: STANDARD
```

### 3.2 Why Start Small

SPX put spreads have a minimum viable size. A single $50-wide spread has max loss of ~$4,300. With $5K capital and f_final = 0.5, that's 0-1 spreads. This is intentionally tiny.

The purpose is NOT to make money in Stage 1. It's to verify:
- Real IBKR fills match paper fills in price and timing
- Real slippage is within the model's 25% bid-ask assumption
- Real commissions match $0.65/contract expectation
- The system doesn't break when real money is on the line
- You don't make emotional decisions that override the system

Stage 1 might lose money simply due to small sample size (1-3 trades per month). That's expected and acceptable.

---

## 4. Code Changes from Phase 3

### 4.1 Broker Mode Switch

```python
# config/settings.yaml
execution:
  mode: "live"        # Changed from "paper"
  ibkr:
    port: 7496        # Changed from 7497
    client_id: 1
```

```python
# Safety: require explicit confirmation
class IBKRBroker:
    def __init__(self, mode: str):
        if mode == 'live':
            confirm = input("LIVE TRADING MODE. Type 'CONFIRM LIVE' to proceed: ")
            assert confirm == 'CONFIRM LIVE', "Live mode not confirmed"
        self.port = 7496 if mode == 'live' else 7497
```

### 4.2 Stage-Aware Safety Guards

```python
# Safety guards adjust by stage
STAGE_LIMITS = {
    'stage_1': {
        'max_contracts': 3,
        'max_notional': 15_000,
        'max_weekly_trades': 1,
    },
    'stage_2': {
        'max_contracts': 10,
        'max_notional': 50_000,
        'max_weekly_trades': 1,
    },
    'stage_3': {
        'max_contracts': 50,
        'max_notional': 250_000,
        'max_weekly_trades': 2,     # Allow rolling + new entry
    },
}
```

### 4.3 Enhanced Logging

Live trading adds extra logging that paper didn't need:

```python
# Every order gets a detailed audit trail
class LiveAuditLog:
    def log_order(self, order, decision_context):
        """Logs:
        - Full decision chain (regime, VRP, entry decision, risk sizing)
        - Order details (strikes, premium, contracts)
        - Pre-trade account state
        - Market conditions at order time
        - Timestamp to millisecond
        """

    def log_fill(self, fill, expected_price):
        """Logs:
        - Fill price vs expected (slippage measurement)
        - Fill time
        - Post-fill account state
        """
```

---

## 5. Risk Parameter Tightening

### 5.1 Stage 1: Conservative Overrides

During Stage 1, risk parameters are tighter than backtest-optimal to provide extra cushion while verifying real-world behavior.

| Parameter | Backtest (Phase 2) | Stage 1 | Stage 2+ |
|-----------|-------------------|---------|----------|
| σ_target | 12% | 8% | 12% |
| DD reduce | 5% | 3% | 5% |
| DD kill | 10% | 7% | 10% |
| Max contracts | Per sizing | 3 | Per sizing |
| Kelly clip max | 2.0 | 1.0 | 2.0 |
| Min premium ratio | 10% | 12% | 10% |
| P_HV skip threshold | 0.5 | 0.4 | 0.5 |

Rationale: Stage 1 intentionally trades less, with smaller size, and exits earlier. This sacrifices returns for safety while verifying that real execution works.

### 5.2 Restoring Standard Parameters

Stage 1 → Stage 2 transition restores standard parameters. This is a config change, not a code change:

```yaml
# config/settings.yaml — Stage 2
risk:
  vol_scaling:
    target_vol: 0.12      # Restored from 0.08
  drawdown:
    reduce: 0.05           # Restored from 0.03
    kill: 0.10             # Restored from 0.07
```

Document the change with a git commit: `"Phase 4: Stage 1 → Stage 2, restore standard risk params"`

---

## 6. Operational Procedures

### 6.1 Daily Routine (2 minutes)

```
17:00 ET — Daily report email arrives

READ:
  1. Pipeline status: all steps OK?
  2. Regime: any transition today?
  3. Position: P&L, Greeks, exit trigger proximity
  4. Risk: DD level, binding constraint
  5. Action required: any?

IF all OK → done (2 minutes)
IF WARNING → investigate within 4 hours
IF CRITICAL → investigate within 1 hour
IF EMERGENCY → investigate immediately
```

### 6.2 Weekly Review (15 minutes, after Tuesday entry)

```
Tuesday evening or Wednesday morning:

  1. Did the system enter a trade? If so:
     [] Strike reasonable for current VIX level?
     [] Premium ratio within expected range?
     [] n_contracts matches expected sizing?
     [] Fill price close to mid (slippage check)?

  2. If skipped, was the reason correct?
     [] Check regime, VRP, premium — does skip make sense?

  3. Open position status:
     [] Greeks within risk limits?
     [] Profit trajectory on track?
     [] Any exit trigger approaching?

  4. Concordance check:
     [] Run scripts/concordance_check.py
     [] Any regime or entry disagreements this week?
```

### 6.3 Monthly Review (1 hour, 1st weekend of month)

```
  1. Performance summary:
     [] Monthly return
     [] Running Sharpe (since Phase 4 start)
     [] Current DD from HWM
     [] Comparison against Phase 2 backtest for same calendar period

  2. HMM refit results:
     [] Label stability >= 90%?
     [] If refit deferred, why?

  3. Calibration quality:
     [] Heston success rate this month
     [] Any fallback events?
     [] RMSE trend (stable or degrading?)

  4. Execution quality:
     [] Average slippage vs model assumption (25%)
     [] Commission total vs expectation
     [] Any rejected or failed orders?

  5. Operational health:
     [] Pipeline success rate
     [] Alert count by level
     [] Any unresolved issues?
```

### 6.4 Quarterly Review (half day)

```
  1. Deep performance analysis:
     [] Sharpe ratio (annualized from Phase 4 start)
     [] MDD, CVaR(95%), worst month
     [] Compare against Phase 2 backtest:
        -> Live Sharpe within 70% of backtest Sharpe?
        -> Live MDD within 1.5x of backtest MDD?

  2. Strategy review:
     [] Is VRP still positive on average? (structural premise intact?)
     [] Regime detection still adding value? (compare vs naive)
     [] Any market structure changes? (regulatory, product changes)

  3. Parameter review:
     [] Should any parameters be adjusted based on live evidence?
     [] WARNING: Do not optimize to recent performance.
        Only adjust if there's a structural reason (not a P&L reason).

  4. Decision:
     [] Continue as-is
     [] Adjust parameters (with documented rationale)
     [] Scale up (if criteria met, see Section 8)
     [] Scale down (if performance degrading)
     [] Stop (if strategy is broken, see Section 11)
```

---

## 7. Performance Tracking

### 7.1 Metrics Tracked

Continuously logged in SQLite, reviewed at monthly/quarterly cadence:

```
Per trade:
  entry_date, exit_date, duration
  short_strike, long_strike, expiry, width
  n_contracts, premium, exit_price, pnl
  entry_slippage, exit_slippage, total_commission
  regime_at_entry, regime_at_exit
  exit_reason
  f_vol, f_kelly, f_dd, f_final at entry

Per day:
  account_value, drawdown_from_hwm
  regime probabilities
  vix, rv_21, vrp_proxy, z_vrp
  calibration_status, calibration_rmse
  open_position_pnl, open_position_greeks

Per month:
  monthly_return, cumulative_return
  sharpe (rolling), mdd
  cvar_95, worst_day
  n_trades, win_rate, avg_win, avg_loss
  total_commission, total_slippage
  skip_rate, regime_distribution
```

### 7.2 Backtest Comparison

Every month, compute Phase 2 backtest metrics for the same calendar period and compare:

```
| Metric | Phase 2 Backtest | Phase 4 Live | Ratio |
|--------|-----------------|-------------|-------|
| Monthly return | X% | Y% | Y/X |
| Sharpe (annualized) | A | B | B/A |
| MDD | C% | D% | D/C |
| Win rate | E% | F% | F/E |
| Avg slippage | G bps | H bps | H/G |
```

**Expected:** Live performance is worse than backtest. The question is how much worse.

| Live / Backtest Ratio | Interpretation |
|----------------------|----------------|
| > 0.8 | Excellent — live closely matches backtest |
| 0.6 - 0.8 | Acceptable — costs and real-world friction explain the gap |
| 0.4 - 0.6 | Concerning — investigate slippage, timing, execution quality |
| < 0.4 | Strategy may not work in practice despite good backtest |

### 7.3 Regime Attribution

Track performance by regime at entry:

```
| Regime at Entry | Trades | Win Rate | Avg P&L | Contribution |
|----------------|--------|----------|---------|-------------|
| Low-Vol | N | X% | $Y | Z% of total |
| Normal-Vol | N | X% | $Y | Z% of total |
| High-Vol | N | X% | $Y | Z% of total |
```

This tells you whether the regime filter is adding value in practice, not just in backtest.

---

## 8. Scaling Criteria

### 8.1 Stage 1 → Stage 2

**Minimum duration:** 4 weeks (approximately 4-6 trades)

**ALL must pass:**

| # | Check | Criterion |
|---|-------|-----------|
| 1 | Operational stability | Zero crashes during Stage 1 |
| 2 | Real slippage | Within 1.5x of model assumption (37.5% vs 25%) |
| 3 | Real commissions | Within 20% of model ($0.65/contract) |
| 4 | Fill quality | All orders filled within 2 minutes |
| 5 | No manual interventions | System ran autonomously for full Stage 1 |
| 6 | Emotional check | Did you override any system decision? If yes, why? |

**Note:** P&L is NOT a Stage 1 → Stage 2 criterion. With 1-3 spreads over 4 weeks, the sample is too small for statistical significance. A losing Stage 1 does not mean the strategy is broken.

### 8.2 Stage 2 → Stage 3

**Minimum duration:** 2 months (approximately 8-16 trades)

**ALL must pass:**

| # | Check | Criterion |
|---|-------|-----------|
| 1 | Cumulative P&L | Positive (any amount) |
| 2 | Win rate | > 65% (lower than backtest due to small sample, but must be majority wins) |
| 3 | MDD | < 15% |
| 4 | Live / Backtest Sharpe ratio | > 0.5 |
| 5 | No operational incidents | Zero CRITICAL+ alerts in Stage 2 |
| 6 | Regime detection value | At least 1 instance where regime filter avoided a loss |

### 8.3 Stage 3 Steady State

No further scaling criteria — Stage 3 is the production steady state. Capital can be increased within Stage 3 based on quarterly reviews, but this is a personal financial decision, not a system decision.

**Guardrail:** Never allocate more than 20% of total investable assets to this single strategy. Diversification across strategies and asset classes is outside this system's scope but essential for personal risk management.

---

## 9. Failure Modes & Emergency Procedures

### 9.1 Severity Classification

| Level | Definition | Response Time | Example |
|-------|-----------|---------------|---------|
| INFO | Normal operation | Review daily | "Trade entered: 5 spreads SPX 5200/5100" |
| WARNING | Degraded, auto-recovered | 4 hours | "Heston calibration used DE-only" |
| CRITICAL | Requires attention | 1 hour | "DD > 5%, position reduced" |
| EMERGENCY | Immediate action | 15 minutes | "IBKR disconnected during exit order" |

### 9.2 Emergency Procedures

**EMERGENCY: IBKR Disconnection During Open Order**

```
1. DO NOT PANIC.
2. Log in to IBKR TWS directly (not through the bot).
3. Check: is the order filled, partially filled, or unfilled?
4. If filled: update SQLite manually, system will sync on next run.
5. If partially filled: decide whether to complete or cancel remainder.
6. If unfilled: cancel the order, system will retry next pipeline run.
7. Document the event in the alert log.
8. Investigate root cause (network? TWS crash? API issue?).
```

**EMERGENCY: DD Kill Triggered**

```
1. System has set f_final = 0 and attempted to close all positions.
2. Verify in IBKR TWS: are all positions actually closed?
3. If yes: system is now in cash. It will stay in cash until DD recovers below 5%.
4. If positions remain open (exit order failed): close manually via TWS.
5. DO NOT override the kill switch to re-enter. Wait for DD recovery.
6. Review: was the DD caused by a single event or gradual decay?
7. If single event (e.g., flash crash): likely recoverable, wait.
8. If gradual: review quarterly — is the strategy still working?
```

**EMERGENCY: Heston Calibration Fails for 3+ Consecutive Days**

```
1. System has fallen back to BS pricing (CRITICAL alert should have fired).
2. BS pricing is less accurate but functional for basic delta/Greeks.
3. Investigate: is Polygon data available? Is the options chain normal?
4. If data issue: fix data pipeline, recalibrate.
5. If Heston genuinely can't fit the market: vol surface may be unusual.
   -> Consider: skip entry this week (manual override).
   -> Do NOT force calibration with bad parameters.
6. If persists > 1 week: this is a system issue, not a market issue.
   -> Halt new entries until calibration is restored.
```

**EMERGENCY: System Discovers a Bug in Live Trading**

```
1. IMMEDIATELY halt new entries (set mode to "pause" in settings.yaml).
2. Do NOT close existing positions unless they pose immediate risk.
3. Assess the bug:
   -> Does it affect position monitoring? If yes, monitor manually via TWS.
   -> Does it affect risk management? If yes, tighten DD kill to 5% manually.
   -> Does it affect data? If yes, verify positions against TWS directly.
4. Fix the bug in code.
5. Run Phase 2 backtest with the fix to verify no regression.
6. Run 3 days of paper trading with the fix.
7. Resume live trading.
8. Document the bug, root cause, fix, and prevention in incident log.
```

### 9.3 Manual Override Protocol

Sometimes you need to override the system. Rules for doing so:

```
1. NEVER override to enter a trade the system skipped.
   The system skipped for a reason (regime, VRP, premium). Trust it.

2. You MAY override to skip a trade the system wants to enter.
   Reason: external information the system doesn't have
   (e.g., Fed announcement tomorrow, known market event).
   Log the override with reason.

3. You MAY override to close a position early.
   Reason: personal risk tolerance, external information.
   Log the override with reason.

4. You MAY NOT change risk parameters intraday.
   Parameter changes happen at monthly/quarterly review only.

5. Every override is logged in the alerts table with level=WARNING
   and reason documented.

6. If you find yourself overriding more than once per month,
   the system parameters need adjustment — not more overrides.
```

---

## 10. Ongoing Maintenance

### 10.1 Regular Maintenance Schedule

| Task | Frequency | Duration | Notes |
|------|-----------|----------|-------|
| Read daily report | Daily | 2 min | Check for anomalies |
| Weekly trade review | Weekly | 15 min | Verify entries/exits |
| Concordance check | Weekly | 5 min | Run script, review |
| Monthly performance review | Monthly | 1 hour | Full metrics analysis |
| HMM refit review | Monthly | 10 min | Check stability |
| Quarterly deep review | Quarterly | Half day | Strategy health check |
| Polygon.io billing | Monthly | 1 min | Verify subscription active |
| IBKR data subscription | Monthly | 1 min | Verify market data active |
| Software updates | Quarterly | 1 hour | Python packages, ib_insync |
| Server/machine maintenance | Quarterly | 1 hour | OS updates, disk space |

### 10.2 Data & Model Staleness

| Component | Refresh Frequency | If Stale |
|-----------|-------------------|----------|
| Market data | Daily (automatic) | Pipeline fails, uses cache |
| Regime features | Daily (automatic) | Regime detection unreliable |
| Heston calibration | Daily (automatic) | Greeks inaccurate |
| XGBoost model | Weekly (automatic) | Regime predictions degrade |
| HMM labels | Monthly (automatic) | Underlying regime structure drifts |
| Settings/parameters | Manual only | No auto-update, reviewed quarterly |

### 10.3 What To Do After Extended Absence

If you can't monitor the system for an extended period (vacation, etc.):

```
Option A: Let it run.
  -> System is designed to be autonomous.
  -> DD kill switch protects against catastrophic loss.
  -> Daily reports accumulate in email for review on return.
  -> Suitable for: 1-2 weeks absence.

Option B: Pause new entries.
  -> Set mode to "monitor_only" in settings.yaml.
  -> System still monitors open positions and sends reports.
  -> No new trades entered.
  -> Suitable for: 2-4 weeks absence.

Option C: Close everything and stop.
  -> Close all open positions.
  -> Stop the scheduler.
  -> Restart when you return.
  -> Suitable for: > 1 month absence.
```

---

## 11. When to Stop

### 11.1 Automatic Stops (System Enforced)

```
DD ≥ 10% → Kill switch. Automatic full exit. Wait for recovery.
3 consecutive calibration failures → Halt new entries (CRITICAL alert).
IBKR disconnected > 1 trading day → Halt new entries (CRITICAL alert).
```

### 11.2 Discretionary Stops (Human Decision)

Evaluate at quarterly review:

**Red Flags (consider stopping or major revision):**

```
[] Live Sharpe < 0 over 6+ months (strategy not working)
[] Live / Backtest ratio < 0.3 (execution gap too large)
[] VRP proxy is negative for 3+ consecutive months
   (structural premium may have disappeared)
[] Regime detection adds no value over naive for 6+ months
[] Multiple consecutive DD kill events (3+ in a year)
[] Market structure change:
   -> SPX options become illiquid
   -> CBOE changes settlement rules
   -> Regulatory change affects short options
```

**Yellow Flags (monitor closely, don't stop yet):**

```
[] Live Sharpe < 0.3 over 3 months (below expectation but not broken)
[] Slippage consistently 2x+ model assumption
[] Win rate < 65% over 3+ months
[] Heston calibration success rate < 90% for a month
```

### 11.3 Decision Framework

```
At quarterly review:

Is the strategy structurally sound?
  └─ VRP still positive on average? Regime detection still adding value?
  └─ YES → Continue. Market goes through periods.
  └─ NO → Investigate. Has something fundamental changed?
       └─ Temporary (e.g., unusual Fed policy) → Reduce size, wait.
       └─ Permanent (e.g., market structure change) → Stop.

Is the execution working?
  └─ Slippage, commissions, fills within expectations?
  └─ YES → Continue.
  └─ NO → Fix execution layer. Don't blame strategy for execution issues.

Am I following the system?
  └─ Did I override more than twice this quarter?
  └─ YES → Am I adding value with overrides, or am I panic-trading?
       └─ If overrides improved outcomes → Consider formalizing into rules.
       └─ If overrides hurt outcomes → Stop overriding. Trust the system.
  └─ NO → Good. The system is working as designed.
```

### 11.4 Shutting Down Gracefully

If the decision is to stop:

```
1. Stop new entries (mode = "monitor_only")
2. Let open positions reach natural exit (profit target, DTE, stop)
   -> Do NOT close everything at market to "stop immediately"
   -> Unless there's an emergency (DD kill scenario)
3. After all positions closed:
   -> Stop scheduler
   -> Cancel Polygon.io subscription
   -> Withdraw capital from IBKR (or redeploy elsewhere)
4. Preserve all data and logs (for potential restart or research use)
5. Write post-mortem: what worked, what didn't, what you'd change
```

---

## Appendix: Phase 4 Checklist Summary

### Pre-Launch

```
[] Phase 3 GO verdict (all 17 checks)
[] IBKR live account funded (Stage 1 capital)
[] Options permissions enabled
[] Live API port (7496) configured
[] Stage 1 risk parameters set in settings.yaml
[] Emergency procedures printed/bookmarked
[] Tax reporting setup confirmed
```

### Stage 1 Duration (4-8 weeks)

```
[] 4+ weeks of live operation
[] Real slippage within 1.5x model
[] Real commissions within 20% of model
[] All orders filled within 2 minutes
[] No manual interventions required
[] If all pass → advance to Stage 2 (restore standard risk params)
```

### Stage 2 Duration (2-3 months)

```
[] Cumulative P&L positive
[] Win rate > 65%
[] MDD < 15%
[] Live/Backtest Sharpe > 0.5
[] Zero CRITICAL+ incidents
[] If all pass → advance to Stage 3 (full capital)
```

### Stage 3: Steady State

```
[] Ongoing quarterly reviews
[] Never > 20% of investable assets in this strategy
[] Follow When to Stop criteria
[] Enjoy the returns (or accept the losses gracefully)
```
