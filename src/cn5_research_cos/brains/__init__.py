"""Brain interfaces + deterministic stub factory (injection hook)."""
from .interfaces import Brains
from .stubs import MAX_CONCURRENT, STALE_AFTER, build_brains

__all__ = ["Brains", "build_brains", "MAX_CONCURRENT", "STALE_AFTER"]
