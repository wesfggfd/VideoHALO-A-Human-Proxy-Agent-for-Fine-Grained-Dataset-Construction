"""Normative name for the frozen core-memory loader."""
from ..policy.loader import CoreMemory, CoreMemoryError, load_core_memory, sha256_file

__all__ = ["CoreMemory", "CoreMemoryError", "load_core_memory", "sha256_file"]
