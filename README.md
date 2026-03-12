# VRP Trading System

**Regime-Conditioned Systematic Short Volatility | SPX Options | Python**

A fully automated trading system that harvests the Variance Risk Premium by selling SPX put credit spreads, governed by HMM + XGBoost regime detection and multi-layer risk management.

> **Status:** Design complete. Implementation starting at Phase 1 (VIX proxy backtest).

> **Target Performance:** Post-cost Sharpe 0.5-0.8 | MDD < 25% | Win Rate > 75%

---

## How It Works

1. **Variance Risk Premium (VRP):** Options markets systematically overprice volatility because institutions must hedge. We collect this insurance premium by selling put spreads.

2. **Regime Detection:** 3-state HMM (Low-Vol / Normal-Vol / High-Vol) + calibrated XGBoost controls position sizing. In High-Vol: reduce or stop. In Low-Vol: full position.

3. **Risk Management:** Three-layer min-chain — volatility scaling, Kelly ceiling, drawdown override. The most conservative layer always wins.

4. **Defined Risk:** Put credit spreads have maximum loss defined at entry. No naked options. No unlimited downside.

---

## Phases

| Phase | What | Status |
|-------|------|--------|
| Phase 1 | VIX proxy backtest (free data) | 🔜 Next |
| Phase 2 | Options chain backtest (Polygon.io) | Pending Phase 1 GO |
| Phase 3 | IBKR paper trading | Pending Phase 2 GO |
| Phase 4 | Live trading (staged capital) | Pending Phase 3 GO |

Each phase has a GO/NO-GO gate. If any phase fails, we stop before spending more time or money.

---

## Documentation

All design documents are in `docs/`. Start with:
- `docs/mathematical_design_production.md` — Math foundations
- `docs/pipeline_design.md` — System architecture
- `docs/implementation_roadmap.md` — Sprint-by-sprint plan

---

## License

This project is for personal use and research purposes.
