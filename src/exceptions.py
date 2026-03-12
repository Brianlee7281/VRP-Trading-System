"""VRP Trading System — Custom Exceptions.

All custom exceptions inherit from VRPError.
See docs/contracts.md Section 1.2 for usage rules.
"""


class VRPError(Exception):
    """Base exception for VRP system."""


class DataFetchError(VRPError):
    """Failed to fetch data from external source."""


class DataValidationError(VRPError):
    """Fetched data failed quality checks."""


class CacheError(VRPError):
    """Cache read/write failure."""


class CalibrationError(VRPError):
    """Heston calibration failed."""


class RegimeError(VRPError):
    """Regime detection failure."""


class StrikeSelectionError(VRPError):
    """Could not find valid strike (Newton-Raphson non-convergence)."""


class ExecutionError(VRPError):
    """Order placement or fill failure."""


class PipelineError(VRPError):
    """Pipeline step failure."""
