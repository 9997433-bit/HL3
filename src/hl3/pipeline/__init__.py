# SPDX-License-Identifier: Apache-2.0
"""Analysis pipelines: sequence-level orchestration of the HL3 kernels.

:mod:`hl3.pipeline.dic2d` is the 2D chain -- image sequence, POI grid,
first-order IC-GN correlation, reference updates, and an optional hand-off to
:mod:`hl3.strain`. The pipeline layer never implements correlation or strain
mathematics of its own; it composes, masks and reshapes what the kernels
return.
"""

from __future__ import annotations

from .dic2d import (
    Dic2DConfig,
    Dic2DRun,
    FrameOutcome,
    ReferenceMode,
    SeedMode,
    StrainMode,
    StrainOutcome,
    StrainUnavailableError,
    compose_total,
    correlate_pair,
    lattice_shape,
    resolve_strain_backend,
    run_sequence,
    vsg_size_px,
)

__all__ = [
    "Dic2DConfig",
    "Dic2DRun",
    "FrameOutcome",
    "ReferenceMode",
    "SeedMode",
    "StrainMode",
    "StrainOutcome",
    "StrainUnavailableError",
    "compose_total",
    "correlate_pair",
    "dic2d",
    "lattice_shape",
    "resolve_strain_backend",
    "run_sequence",
    "vsg_size_px",
]
