# Data Directory

This directory is .gitignored (except this README). Data is fetched and cached by the system.

## Structure

```
data/
├── raw/                    # Cached from APIs (source-tagged)
│   ├── fred/               # VIX, VIX3M, rates (parquet)
│   ├── yfinance/           # SPX OHLCV (parquet)
│   ├── cboe/               # VVIX (parquet)
│   └── polygon/            # Options chain snapshots (Phase 2+)
│       └── options/SPX/    # One parquet per trading day
├── processed/              # Computed features and models
│   ├── features/           # Daily feature vectors
│   ├── regime/             # HMM/XGBoost models (pkl)
│   └── calibration/        # Heston parameter history
├── backtest/               # Backtest results
│   └── results/
└── vrp.db                  # SQLite: trades, snapshots, alerts, state
```

## Regenerating

All data can be regenerated from APIs by deleting the relevant cache files and re-running the pipeline. Models (regime/, calibration/) require retraining.
