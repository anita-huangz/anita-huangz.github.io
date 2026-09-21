"""Treasury curve analytics: what moves the curve, and what a trade on it earns."""

from .data import MAX_GAP_DAYS, TENORS, Curve, SchemaError, load, validate

__all__ = [
    "MAX_GAP_DAYS",
    "TENORS",
    "Curve",
    "SchemaError",
    "load",
    "validate",
]

__version__ = "0.1.0"
