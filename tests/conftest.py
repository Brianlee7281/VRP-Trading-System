"""Shared test fixtures for VRP Trading System."""

import pytest
import pandas as pd
import numpy as np
from datetime import date


@pytest.fixture
def sample_spx_close():
    """SPX close prices for testing (2020-01-02 to 2020-01-10)."""
    dates = pd.to_datetime([
        "2020-01-02", "2020-01-03", "2020-01-06",
        "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
    ])
    prices = [3257.85, 3234.85, 3246.28, 3237.18, 3253.05, 3274.70, 3265.35]
    return pd.Series(prices, index=dates, name="Close")


@pytest.fixture
def sample_vix():
    """VIX values for testing."""
    dates = pd.to_datetime([
        "2020-01-02", "2020-01-03", "2020-01-06",
        "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
    ])
    values = [12.47, 13.35, 13.62, 13.26, 12.83, 12.42, 12.56]
    return pd.Series(values, index=dates, name="VIX")


@pytest.fixture
def sample_config():
    """Minimal config dict for unit tests."""
    return {
        "system": {"phase": 1},
        "features": {
            "rv_windows": [5, 21, 63],
            "vrp_zscore_window": 252,
            "vol_acceleration_window": 5,
        },
        "regime": {
            "hmm": {
                "n_states": 3,
                "n_init": 10,
                "n_iter": 200,
                "min_training_days": 504,
                "stability_threshold": 0.90,
            },
        },
        "risk": {
            "vol_scaling": {
                "target_vol": 0.12,
                "max_leverage": 1.5,
                "min_leverage": 0.3,
                "vol_window": 20,
            },
            "kelly": {
                "shrinkage_alpha_steady": 0.6,
                "shrinkage_alpha_hv_transition": 0.9,
                "shrinkage_alpha_other_transition": 0.75,
                "transition_window_days": 5,
                "mu_prior": {"low_vol": 0.15, "normal_vol": 0.08, "high_vol": 0.02},
                "rolling_window": 60,
                "f_min": 0.2,
                "f_max": 2.0,
            },
            "drawdown": {"warn": 0.05, "reduce": 0.05, "kill": 0.10},
        },
    }
