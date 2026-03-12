"""Tests for src/data/models.py dataclasses."""

import dataclasses
from datetime import date

import pytest

from src.data.models import (
    FeatureVector,
    MarketData,
    OptionQuote,
    OptionsChain,
)


@pytest.fixture
def sample_put() -> OptionQuote:
    return OptionQuote(
        strike=4200.0,
        expiry=date(2024, 3, 15),
        option_type='put',
        bid=5.50,
        ask=6.00,
        mid=5.75,
        implied_vol=0.18,
        delta=-0.10,
        gamma=0.002,
        theta=-0.15,
        vega=3.50,
        volume=1200,
        open_interest=5000,
    )


@pytest.fixture
def sample_call() -> OptionQuote:
    return OptionQuote(
        strike=4600.0,
        expiry=date(2024, 3, 15),
        option_type='call',
        bid=4.00,
        ask=4.50,
        mid=4.25,
        implied_vol=0.16,
        delta=0.10,
        gamma=0.001,
        theta=-0.12,
        vega=2.80,
        volume=800,
        open_interest=3000,
    )


@pytest.fixture
def sample_chain(sample_put: OptionQuote, sample_call: OptionQuote) -> OptionsChain:
    return OptionsChain(
        underlying_price=4400.0,
        trade_date=date(2024, 2, 20),
        quotes=(sample_put, sample_call),
        risk_free_rate=0.05,
    )


class TestOptionQuote:
    def test_instantiation_all_fields(self, sample_put: OptionQuote) -> None:
        assert sample_put.strike == 4200.0
        assert sample_put.expiry == date(2024, 3, 15)
        assert sample_put.option_type == 'put'
        assert sample_put.bid == 5.50
        assert sample_put.ask == 6.00
        assert sample_put.mid == 5.75
        assert sample_put.implied_vol == 0.18
        assert sample_put.delta == -0.10
        assert sample_put.gamma == 0.002
        assert sample_put.theta == -0.15
        assert sample_put.vega == 3.50
        assert sample_put.volume == 1200
        assert sample_put.open_interest == 5000

    def test_optional_greeks_none(self) -> None:
        quote = OptionQuote(
            strike=4200.0,
            expiry=date(2024, 3, 15),
            option_type='put',
            bid=5.50,
            ask=6.00,
            mid=5.75,
            implied_vol=0.18,
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
            volume=1200,
            open_interest=None,
        )
        assert quote.delta is None
        assert quote.gamma is None
        assert quote.theta is None
        assert quote.vega is None
        assert quote.open_interest is None

    def test_frozen_prevents_mutation(self, sample_put: OptionQuote) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            sample_put.strike = 4300.0  # type: ignore[misc]


class TestOptionsChain:
    def test_puts_filters_correctly(self, sample_chain: OptionsChain) -> None:
        puts = sample_chain.puts()
        assert len(puts) == 1
        assert all(q.option_type == 'put' for q in puts)
        assert puts[0].strike == 4200.0

    def test_puts_empty_when_no_puts(self, sample_call: OptionQuote) -> None:
        chain = OptionsChain(
            underlying_price=4400.0,
            trade_date=date(2024, 2, 20),
            quotes=(sample_call,),
            risk_free_rate=0.05,
        )
        assert chain.puts() == ()

    def test_get_by_strike_expiry_found(
        self, sample_chain: OptionsChain, sample_put: OptionQuote
    ) -> None:
        result = sample_chain.get_by_strike_expiry(
            strike=4200.0, expiry=date(2024, 3, 15), option_type='put'
        )
        assert result is sample_put

    def test_get_by_strike_expiry_not_found(self, sample_chain: OptionsChain) -> None:
        result = sample_chain.get_by_strike_expiry(
            strike=9999.0, expiry=date(2024, 3, 15), option_type='put'
        )
        assert result is None

    def test_get_by_strike_expiry_wrong_type(self, sample_chain: OptionsChain) -> None:
        result = sample_chain.get_by_strike_expiry(
            strike=4200.0, expiry=date(2024, 3, 15), option_type='call'
        )
        assert result is None

    def test_frozen_prevents_mutation(self, sample_chain: OptionsChain) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            sample_chain.underlying_price = 4500.0  # type: ignore[misc]


class TestMarketData:
    def test_full_data(self) -> None:
        md = MarketData(
            trade_date=date(2024, 2, 20),
            spx_close=4400.0,
            vix=16.5,
            vix3m=18.0,
            vvix=85.0,
            risk_free_rate=0.05,
        )
        assert md.spx_close == 4400.0
        assert md.vix3m == 18.0
        assert md.vvix == 85.0

    def test_pre_2007_data_none_optionals(self) -> None:
        md = MarketData(
            trade_date=date(2006, 6, 15),
            spx_close=1250.0,
            vix=12.0,
            vix3m=None,
            vvix=None,
            risk_free_rate=0.045,
        )
        assert md.vix3m is None
        assert md.vvix is None

    def test_frozen_prevents_mutation(self) -> None:
        md = MarketData(
            trade_date=date(2024, 2, 20),
            spx_close=4400.0,
            vix=16.5,
            vix3m=18.0,
            vvix=85.0,
            risk_free_rate=0.05,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            md.vix = 20.0  # type: ignore[misc]


class TestFeatureVector:
    def test_full_feature_vector(self) -> None:
        fv = FeatureVector(
            rv_5=0.12,
            rv_21=0.15,
            rv_63=0.14,
            vix=16.5,
            vix3m=18.0,
            vvix=85.0,
            ts=0.09,
            dvol_5=-0.20,
            vrp_proxy=0.0003,
            z_vrp=0.85,
        )
        assert fv.rv_5 == 0.12
        assert fv.z_vrp == 0.85

    def test_optional_fields_none(self) -> None:
        fv = FeatureVector(
            rv_5=0.12,
            rv_21=0.15,
            rv_63=0.14,
            vix=16.5,
            vix3m=None,
            vvix=None,
            ts=None,
            dvol_5=None,
            vrp_proxy=0.0003,
            z_vrp=0.85,
        )
        assert fv.vix3m is None
        assert fv.ts is None

    def test_frozen_prevents_mutation(self) -> None:
        fv = FeatureVector(
            rv_5=0.12, rv_21=0.15, rv_63=0.14, vix=16.5,
            vix3m=None, vvix=None, ts=None, dvol_5=None,
            vrp_proxy=0.0003, z_vrp=0.85,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            fv.rv_5 = 0.20  # type: ignore[misc]
