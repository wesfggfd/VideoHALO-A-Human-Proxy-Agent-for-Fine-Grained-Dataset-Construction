"""VideoHALO system-cognitive and category memory layers."""
from .core_loader import CoreMemory, CoreMemoryError, load_core_memory
from .layers import (
    CATEGORY_MEMORY,
    MEMORY_LAYERS,
    SYSTEM_COGNITIVE_MEMORY,
    DualLayerMemory,
)
from .prompt_assembler import assemble_role_prompt

__all__ = [
    "CoreMemory",
    "CoreMemoryError",
    "load_core_memory",
    "DualLayerMemory",
    "SYSTEM_COGNITIVE_MEMORY",
    "CATEGORY_MEMORY",
    "MEMORY_LAYERS",
    "assemble_role_prompt",
]
