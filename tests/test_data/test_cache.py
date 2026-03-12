"""Tests for src/data/cache.py."""

from pathlib import Path

import pandas as pd
import pytest

from src.data.cache import DataCache


@pytest.fixture
def cache(tmp_path: Path) -> DataCache:
    return DataCache(base_dir=str(tmp_path / "data" / "raw"))


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
    )


class TestDataCache:
    def test_write_then_read_roundtrip(
        self, cache: DataCache, sample_df: pd.DataFrame
    ) -> None:
        cache.write("yahoo", "spx_ohlcv", sample_df)
        result = cache.read("yahoo", "spx_ohlcv")
        assert result is not None
        pd.testing.assert_frame_equal(result, sample_df)

    def test_exists_true_after_write(
        self, cache: DataCache, sample_df: pd.DataFrame
    ) -> None:
        cache.write("yahoo", "spx_ohlcv", sample_df)
        assert cache.exists("yahoo", "spx_ohlcv") is True

    def test_exists_false_for_missing(self, cache: DataCache) -> None:
        assert cache.exists("yahoo", "nonexistent") is False

    def test_age_days_zero_for_just_written(
        self, cache: DataCache, sample_df: pd.DataFrame
    ) -> None:
        cache.write("yahoo", "spx_ohlcv", sample_df)
        age = cache.age_days("yahoo", "spx_ohlcv")
        assert age == 0

    def test_age_days_none_for_missing(self, cache: DataCache) -> None:
        assert cache.age_days("yahoo", "nonexistent") is None

    def test_read_returns_none_for_nonexistent(self, cache: DataCache) -> None:
        assert cache.read("yahoo", "nonexistent") is None

    def test_cleanup_deletes_with_zero_max_age(
        self, cache: DataCache, sample_df: pd.DataFrame
    ) -> None:
        cache.write("yahoo", "spx_ohlcv", sample_df)
        assert cache.exists("yahoo", "spx_ohlcv") is True
        deleted = cache.cleanup(max_age_days=0)
        assert deleted == 1
        assert cache.exists("yahoo", "spx_ohlcv") is False

    def test_cleanup_preserves_fresh_files(
        self, cache: DataCache, sample_df: pd.DataFrame
    ) -> None:
        cache.write("yahoo", "spx_ohlcv", sample_df)
        deleted = cache.cleanup(max_age_days=90)
        assert deleted == 0
        assert cache.exists("yahoo", "spx_ohlcv") is True
