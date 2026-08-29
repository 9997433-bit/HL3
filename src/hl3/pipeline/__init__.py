# SPDX-License-Identifier: Apache-2.0
"""Analysis pipelines: sequence-level orchestration of the HL3 kernels.

:mod:`hl3.pipeline.dic2d` is the 2D chain -- image sequence, POI grid,
first-order IC-GN correlation, reference updates, and an optional hand-off to
:mod:`hl3.strain`. :mod:`hl3.pipeline.dic3d` is the stereo chain built on top
of it -- one reference stereo match, one 2D run per view, triangulation of both
frames, and world-frame ``U, V, W``. The pipeline layer never implements
correlation, triangulation or strain mathematics of its own; it composes,
masks, gates and reshapes what the kernels return.
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
    strain_step_px,
    run_sequence,
    vsg_size_px,
)
from .dic3d import (
    Dic3DConfig,
    Dic3DRun,
    Frame3D,
    MatchMode,
    MatchOutcome,
    MatchUnavailableError,
    RejectReason,
    Triangulator,
    correlate_stereo_pair,
    match_reference_stereo,
    resolve_match_backend,
    run_stereo_sequence,
    triangulate_correspondence,
)

__all__ = [
    "Dic2DConfig",
    "Dic2DRun",
    "Dic3DConfig",
    "Dic3DRun",
    "Frame3D",
    "FrameOutcome",
    "MatchMode",
    "MatchOutcome",
    "MatchUnavailableError",
    "ReferenceMode",
    "RejectReason",
    "SeedMode",
    "StrainMode",
    "StrainOutcome",
    "StrainUnavailableError",
    "Triangulator",
    "compose_total",
    "correlate_pair",
    "correlate_stereo_pair",
    "dic2d",
    "dic3d",
    "lattice_shape",
    "match_reference_stereo",
    "resolve_match_backend",
    "resolve_strain_backend",
    "run_sequence",
    "run_stereo_sequence",
    "strain_step_px",
    "triangulate_correspondence",
    "vsg_size_px",
]
