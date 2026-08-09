"""VideoHALO 3.7 Fixed-8 high-quality construction runtime."""

from .context import VideoHALORuntimeContext
from .policy.loader import CoreMemory, CoreMemoryError, load_core_memory
from .resolvers.taxonomy import FACT_KIND_TO_LEAF, resolve_leaf

__version__ = "3.7.0"

__all__ = [
    "CoreMemory",
    "CoreMemoryError",
    "FACT_KIND_TO_LEAF",
    "VideoHALORuntimeContext",
    "load_core_memory",
    "resolve_leaf",
]
