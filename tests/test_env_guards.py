"""Execution-policy guards for the open, CPU-only reference CI.

The hosted suite intentionally exercises Linux CPU behavior only. Proprietary
VIC software and Windows evaluation environments are outside this CI boundary;
GPU backends require a separate, explicitly provisioned test lane.
"""

from __future__ import annotations

import os
from pathlib import Path
import platform


def test_runner_is_not_a_windows_vic_environment() -> None:
    """Prevent this open CI lane from becoming a VIC evaluation runner."""

    assert platform.system() != "Windows", (
        "The reference CI must not run on Windows or host VIC software"
    )
    assert not any(
        os.environ.get(name)
        for name in ("HL3_VIC_HOME", "VIC_2D_HOME", "VIC_3D_HOME")
    ), "VIC installation variables must not be present in open CI"


def test_ci_lane_is_explicitly_cpu_only() -> None:
    """Keep CPU results distinct from future optional accelerator results."""

    if os.environ.get("CI"):
        assert os.environ.get("HL3_CI_CPU_ONLY") == "1"
        assert os.environ.get("CUDA_VISIBLE_DEVICES") in {"", "-1"}

    assert not Path("/dev/nvidia0").exists(), (
        "The reference suite requires a CPU-only runner; use a separate GPU lane"
    )
