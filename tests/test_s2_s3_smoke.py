"""Import smoke tests for optional S2/S3 package surfaces."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "module_name",
    (
        "hl3.stereo.match",
        "hl3.pipeline.dic3d",
        "hl3.uq",
        "hl3.cli.validate",
    ),
)
def test_s2_s3_module_import(module_name: str) -> None:
    """Import each future surface when its implementation is available."""
    pytest.importorskip(
        module_name,
        reason=f"{module_name} is not implemented in the current stage",
    )
