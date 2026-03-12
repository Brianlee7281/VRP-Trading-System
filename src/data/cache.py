"""Source-tagged parquet cache.

File path pattern: {base_dir}/{source}/{key}.parquet
See docs/contracts.md Section 3.3 for specification.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from src.exceptions import CacheError


class DataCache:
    """Source-tagged parquet cache."""

    def __init__(self, base_dir: str = "data/raw"):
        self._base = Path(base_dir)

    def _path(self, source: str, key: str) -> Path:
        """Resolve cache file path."""
        return self._base / source / f"{key}.parquet"

    def read(self, source: str, key: str) -> Optional[pd.DataFrame]:
        """Read cached data. Returns None if not found."""
        path = self._path(source, key)
        if not path.exists():
            return None
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except Exception as e:
            logger.warning(f"Cache read failed for {path}: {e}")
            return None

    def write(self, source: str, key: str, data: pd.DataFrame) -> None:
        """Write data to cache. Overwrites if exists.

        Raises:
            CacheError: Disk write failure.
        """
        path = self._path(source, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data.to_parquet(path, engine="pyarrow")
        except Exception as e:
            raise CacheError(f"Cache write failed for {path}: {e}") from e

    def exists(self, source: str, key: str) -> bool:
        """Check if cache entry exists."""
        return self._path(source, key).exists()

    def age_days(self, source: str, key: str) -> Optional[int]:
        """Days since cache entry was last written. None if not found."""
        path = self._path(source, key)
        if not path.exists():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return (now - mtime).days

    def cleanup(self, max_age_days: int = 90) -> int:
        """Delete cache entries older than max_age_days. Returns count deleted."""
        if not self._base.exists():
            return 0
        now = datetime.now(tz=timezone.utc)
        deleted = 0
        for path in self._base.rglob("*.parquet"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if (now - mtime).days >= max_age_days:
                path.unlink()
                logger.info(f"Deleted stale cache: {path}")
                deleted += 1
        return deleted
