"""Shared data types for the VRP Trading System.

Immutable dataclasses used across module boundaries.
See docs/contracts.md Section 2 for specifications.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class OptionQuote:
    """Single option contract quote."""

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
    """Collection of option quotes for a single underlying on a single date."""

    underlying_price: float
    trade_date: date
    quotes: tuple[OptionQuote, ...]   # immutable tuple, not list
    risk_free_rate: float

    def puts(self) -> tuple[OptionQuote, ...]:
        """Filter to put options only."""
        return tuple(q for q in self.quotes if q.option_type == 'put')

    def get_by_strike_expiry(
        self, strike: float, expiry: date, option_type: str = 'put'
    ) -> Optional[OptionQuote]:
        """Lookup a specific contract. Returns None if not found."""
        for q in self.quotes:
            if q.strike == strike and q.expiry == expiry and q.option_type == option_type:
                return q
        return None


@dataclass(frozen=True)
class MarketData:
    """Daily market snapshot."""

    trade_date: date
    spx_close: float
    vix: float
    vix3m: Optional[float]        # None before 2007-12
    vvix: Optional[float]         # None before 2007-01
    risk_free_rate: float


@dataclass(frozen=True)
class FeatureVector:
    """Feature set for regime detection and signal generation."""

    rv_5: float
    rv_21: float
    rv_63: float
    vix: float
    vix3m: Optional[float]
    vvix: Optional[float]
    ts: Optional[float]           # VIX term structure
    dvol_5: Optional[float]       # 5-day vol acceleration
    vrp_proxy: float
    z_vrp: float
