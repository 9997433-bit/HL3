"""HL3 -- open-core digital image correlation toolkit.

Deliberately minimal: subpackages are imported explicitly (for example
``from hl3 import correlate``) so that adding a module never forces an import
of every other one.
"""

from __future__ import annotations

__version__ = "0.0.1.dev0"

__all__ = ["__version__", "correlate"]
