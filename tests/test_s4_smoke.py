"""Import smoke tests for optional S4 package surfaces."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "module_name",
    (
        "hl3.cli.run",
        "hl3.viz",
        "hl3.fea",
    ),
)
def test_s4_module_import(module_name: str) -> None:
    """Import each S4 surface when its implementation is available."""
    pytest.importorskip(
        module_name,
        reason=f"{module_name} is not implemented in the current stage",
    )
