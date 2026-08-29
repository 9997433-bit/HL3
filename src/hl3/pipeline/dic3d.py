# SPDX-License-Identifier: Apache-2.0
"""Stereo-DIC sequence orchestration: two views in, ``U, V, W`` in world units.

This is the S2--S6 chain of spec ``.agent_workspace/round1/R1-O2-hl3-3d-spec.md``
assembled from parts that already exist:

* **S2, reference stereo match.** Left reference POIs are matched into the
  right reference image once. :mod:`hl3.stereo.match` owns this when it is
  importable; until it lands the module falls back to its own epipolar depth
  search plus an IC-GN refinement (:func:`match_reference_stereo`), so the 3D
  chain is testable end to end today and swaps over without a call-site change.
* **S4, temporal match.** Each view is tracked independently by
  :func:`hl3.pipeline.dic2d.run_sequence`, which is the same 2D pipeline the
  monocular chain uses -- seeds, reference updates and status bookkeeping
  included. Nothing about correlation is reimplemented here.
* **S3/S5, triangulation.** Reference and deformed correspondences go through
  the :mod:`hl3.stereo.triangulate` rungs; the default is the linear DLT and
  the other three rungs of spec S6.1 are one enum value away.
* **S6, displacement.** ``U, V, W = X_def - X_ref`` in the *world* frame
  (spec S7.1), together with the magnitude ``|A|`` that the Stereo-DIC
  Challenge used precisely because it survives a misaligned coordinate system.

Two properties are worth stating because they are easy to lose:

*The reference pairing is solved once.* A material point is identified by its
left-image POI for the whole run, and its right-image partner is found in the
reference frame only. Re-matching stereo every frame would let a point drift
onto a different piece of material and would make ``W`` a function of the
matcher's mood rather than of the specimen.

*The four-way loop residual is computed, not assumed.* Spec S6.4 closes
``left_ref -> right_ref -> right_def -> left_def -> left_ref`` and measures the
pixel error of the round trip. It is the only quality figure in the whole chain
that needs no ground truth and no artefact, so it is on by default; rejecting
points on it is opt-in via :attr:`Dic3DConfig.max_loop_px`. Legs three and four
are seeded from quantities inside the loop, never from the left temporal match
they are meant to audit.

Lens distortion is absent at every level, because the pinhole L0 model is all
:mod:`hl3.stereo` currently implements; the stereo-microscope distortion layer
of spec S4.1 L6 is not implemented anywhere in this repository and is not
implemented here either (spec S10.4 blocks it behind a written clearance
opinion). What this module adds on top of pinhole geometry is bookkeeping,
gating and provenance -- no new optics.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..correlate import BSplineInterpolator, ICGNParams, Status, icgn, make_grid
from ..stereo.triangulate import (
    cheirality_mask,
    fundamental_from_projections,
    position_sigma,
    project,
    reprojection_residuals,
    sampson_distance,
    triangulate_dlt,
    triangulate_midpoint,
    triangulate_nonlinear,
    triangulate_optimal,
    triangulation_covariance,
)
from .dic2d import (
    Dic2DConfig,
    Dic2DRun,
    ReferenceMode,
    SeedMode,
    StrainMode,
    lattice_shape,
)
from .dic2d import run_sequence as run_sequence_2d

__all__ = [
    "Dic3DConfig",
    "Dic3DRun",
    "Frame3D",
    "MatchMode",
    "MatchOutcome",
    "MatchUnavailableError",
    "RejectReason",
    "Triangulator",
    "correlate_stereo_pair",
    "match_reference_stereo",
    "resolve_match_backend",
    "run_stereo_sequence",
    "triangulate_correspondence",
]


class MatchMode(enum.Enum):
    """Where the reference stereo correspondence comes from."""

    #: Use :mod:`hl3.stereo.match` when it is importable and usable, and the
    #: built-in epipolar search both when it is not *and* for the points it
    #: left unmatched. Completing the field is not second-guessing the
    #: backend -- no match it produced is overridden -- it is the cheap-global,
    #: expensive-local ordering of spec S5.1 stages A to C.
    AUTO = "auto"
    #: Always use the built-in matcher, even when :mod:`hl3.stereo.match` is
    #: available. Reproduces a run bit for bit across that module landing.
    INTERNAL = "internal"
    #: The module or nothing: no fallback, and no completion of its misses.
    REQUIRED = "required"


class Triangulator(enum.Enum):
    """Which rung of spec S6.1 turns a correspondence into a world point."""

    MIDPOINT = "midpoint"
    DLT = "dlt"
    #: Iterated Sampson correction followed by DLT; L2-optimal for two views.
    OPTIMAL = "optimal"
    #: Gauss--Newton reprojection minimisation, initialised from the DLT.
    NONLINEAR = "nonlinear"


class RejectReason(enum.IntEnum):
    """Why a point carries no 3D result, in the order the gates are applied.

    This is deliberately *not* :class:`hl3.correlate.Status`: a point can have
    three perfectly converged correlations and still be unusable because its
    rays are nearly parallel or because it triangulated behind a camera.
    Folding those cases into a correlation status code would misattribute a
    geometry failure to the correlator.
    """

    NONE = 0
    #: The reference stereo match did not converge; the point never had a
    #: right-image partner, so no frame of it can be triangulated.
    NO_STEREO_MATCH = 1
    #: The reference correspondence is too far off its epipolar line.
    EPIPOLAR = 2
    LEFT_MATCH = 3
    RIGHT_MATCH = 4
    #: The triangulator returned a non-finite point.
    TRIANGULATION = 5
    #: The point lies behind at least one camera.
    CHEIRALITY = 6
    #: Predicted position uncertainty above ``max_position_sigma_mm``.
    UNCERTAINTY = 7
    #: Four-way loop residual above ``max_loop_px``.
    LOOP_CLOSURE = 8


class MatchUnavailableError(RuntimeError):
    """Raised only under :attr:`MatchMode.REQUIRED`."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dic3DConfig:
    """Everything the stereo pipeline needs beyond images and cameras.

    ``icgn`` drives the per-view temporal correlation and, unless
    ``stereo_icgn`` overrides it, the stereo match as well. Spec S5.1 makes the
    second-order shape function the default for *stereo* matching, because the
    two views see a genuinely different perspective of the same surface; that
    is one field away here (``stereo_icgn=replace(icgn, shape_order=2)``) and
    is left off by default only so that a run costs what a reader expects.
    """

    icgn: ICGNParams = field(default_factory=ICGNParams)
    #: Correlation parameters for the stereo legs; ``None`` reuses ``icgn``.
    stereo_icgn: ICGNParams | None = None
    reference_index: int = 0
    reference_mode: ReferenceMode = ReferenceMode.FIXED
    reference_zncc: float = 0.85
    reference_every_n: int = 10
    seed_mode: SeedMode = SeedMode.PREV_FRAME
    margin: int | None = None
    match_mode: MatchMode = MatchMode.AUTO
    #: Explicit matcher, bypassing the :mod:`hl3.stereo.match` lookup.
    match_backend: Callable[..., Any] | None = None
    #: Range along the left viewing ray, in world units, swept by the built-in
    #: matcher. ``None`` derives it from where the two optical axes converge.
    depth_range_mm: tuple[float, float] | None = None
    #: Target spacing of consecutive sweep candidates in the right image. The
    #: sample count follows from it and the rig geometry; setting
    #: ``depth_samples`` overrides both.
    depth_step_px: float = 2.0
    depth_samples: int | None = None
    max_depth_samples: int = 4096
    #: Half-width of the derived range, as a fraction of the convergence
    #: distance. 0.35 covers a +-35% depth-of-field, which is far more than any
    #: stereo rig has in focus.
    depth_span: float = 0.35
    #: Coarse-search ZNCC floor. A point whose best epipolar candidate scores
    #: below this gets no seed at all rather than a confident wrong one.
    seed_zncc_min: float = 0.5
    triangulator: Triangulator = Triangulator.DLT
    #: Image-plane noise assumed when propagating match noise into the 3x3
    #: position covariance (spec S6.6, match term only).
    sigma_px: float = 1.0
    max_position_sigma_mm: float = math.inf
    max_epipolar_px: float = math.inf
    max_loop_px: float = math.inf
    #: Compute the spec S6.4 four-way loop residual. Costs two extra
    #: correlations per frame; reporting it is the default, gating on it is not.
    loop_closure: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.icgn, ICGNParams):
            raise TypeError("icgn must be an ICGNParams instance")
        if self.stereo_icgn is not None and not isinstance(
            self.stereo_icgn, ICGNParams
        ):
            raise TypeError("stereo_icgn must be an ICGNParams instance or None")
        if self.reference_index < 0:
            raise ValueError("reference_index must be >= 0")
        if self.reference_every_n < 1:
            raise ValueError("reference_every_n must be >= 1")
        if not -1.0 <= self.reference_zncc <= 1.0:
            raise ValueError("reference_zncc must lie in [-1, 1]")
        if self.margin is not None and self.margin < 0:
            raise ValueError("margin must be >= 0")
        if self.match_backend is not None and not callable(self.match_backend):
            raise TypeError("match_backend must be callable")
        if self.depth_samples is not None and self.depth_samples < 2:
            raise ValueError("depth_samples must be >= 2 or None")
        if not self.depth_step_px > 0.0:
            raise ValueError("depth_step_px must be positive")
        if self.max_depth_samples < 2:
            raise ValueError("max_depth_samples must be >= 2")
        if not 0.0 < self.depth_span < 1.0:
            raise ValueError("depth_span must lie in (0, 1)")
        if not -1.0 <= self.seed_zncc_min <= 1.0:
            raise ValueError("seed_zncc_min must lie in [-1, 1]")
        if self.depth_range_mm is not None:
            low, high = (float(value) for value in self.depth_range_mm)
            if not 0.0 < low < high or not math.isfinite(high):
                raise ValueError(
                    "depth_range_mm must be a finite (near, far) pair with "
                    f"0 < near < far, got {self.depth_range_mm}"
                )
        if not self.sigma_px > 0.0:
            raise ValueError("sigma_px must be positive")
        for name in ("max_position_sigma_mm", "max_epipolar_px", "max_loop_px"):
            if not getattr(self, name) > 0.0:
                raise ValueError(f"{name} must be positive")
        if (
            self.reference_mode is not ReferenceMode.FIXED
            and self.reference_index != 0
        ):
            raise ValueError(
                "reference updates require reference_index == 0; frames before "
                "the reference cannot be reached by forward accumulation"
            )

    @property
    def stereo_params(self) -> ICGNParams:
        """Correlation parameters for the stereo legs."""
        return self.stereo_icgn if self.stereo_icgn is not None else self.icgn

    @property
    def subset_size(self) -> int:
        return self.icgn.subset_size

    @property
    def step(self) -> int:
        return self.icgn.step

    def temporal_config(self) -> Dic2DConfig:
        """The 2D configuration each view is tracked with.

        Strain is switched off: surface strain on a curved 3D surface is spec
        S7 work on the world-frame field, and a per-view 2D strain would be a
        different, misleading quantity that happens to have the same name.
        """
        return Dic2DConfig(
            icgn=self.icgn,
            reference_index=self.reference_index,
            reference_mode=self.reference_mode,
            reference_zncc=self.reference_zncc,
            reference_every_n=self.reference_every_n,
            seed_mode=self.seed_mode,
            margin=self.margin,
            strain_mode=StrainMode.OFF,
        )


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class MatchOutcome:
    """The reference-frame stereo correspondence and how it was obtained."""

    points: np.ndarray  # (n, 2) left reference pixels
    x_right: np.ndarray  # (n, 2) right reference pixels, NaN where unmatched
    zncc: np.ndarray  # (n,)
    status: np.ndarray  # (n,) hl3.correlate.Status
    backend: str
    reason: str
    #: ZNCC of the best coarse epipolar candidate, when a search was run.
    seed_zncc: np.ndarray | None = None

    @property
    def valid(self) -> np.ndarray:
        return self.status == int(Status.CONVERGED)

    @property
    def n_points(self) -> int:
        return int(self.points.shape[0])

    @property
    def matched_fraction(self) -> float:
        if self.n_points == 0:
            return 0.0
        return float(np.count_nonzero(self.valid)) / self.n_points


@dataclass(frozen=True, eq=False)
class Frame3D:
    """One frame of a stereo run: where the surface is, and how far it moved.

    Every array is indexed by the reference-frame POI, so ``frames[i].X[k]``
    and ``frames[j].X[k]`` are the same material point. Rows where ``valid`` is
    false are NaN in the float fields rather than stale: a 3D coordinate that
    silently keeps last frame's value is the single most expensive kind of
    wrong number this pipeline could return.
    """

    index: int
    frame_index: int
    x_left: np.ndarray  # (n, 2)
    x_right: np.ndarray  # (n, 2)
    X: np.ndarray  # (n, 3) world coordinates
    displacement: np.ndarray  # (n, 3) U, V, W
    valid: np.ndarray  # (n,) bool
    reject: np.ndarray  # (n,) RejectReason
    status_left: np.ndarray  # (n,) hl3.correlate.Status
    status_right: np.ndarray  # (n,)
    zncc_left: np.ndarray  # (n,)
    zncc_right: np.ndarray  # (n,)
    position_sigma_mm: np.ndarray  # (n,)
    reprojection_px: np.ndarray  # (n,)
    loop_px: np.ndarray  # (n,) NaN when the loop was not computed
    timestamp_s: float | None = None

    @property
    def u(self) -> np.ndarray:
        return self.displacement[:, 0]

    @property
    def v(self) -> np.ndarray:
        return self.displacement[:, 1]

    @property
    def w(self) -> np.ndarray:
        return self.displacement[:, 2]

    @property
    def magnitude(self) -> np.ndarray:
        """``|A| = sqrt(U^2 + V^2 + W^2)`` (spec S7.1)."""
        return np.sqrt(np.sum(self.displacement**2, axis=1))

    @property
    def n_points(self) -> int:
        return int(self.X.shape[0])

    @property
    def valid_fraction(self) -> float:
        if self.n_points == 0:
            return 0.0
        return float(np.count_nonzero(self.valid)) / self.n_points

    def reject_counts(self) -> dict[RejectReason, int]:
        return {
            reason: int(np.count_nonzero(self.reject == int(reason)))
            for reason in RejectReason
            if np.any(self.reject == int(reason))
        }


@dataclass(frozen=True, eq=False)
class Dic3DRun:
    """Shape, 3D displacement and quality for a whole stereo sequence."""

    points: np.ndarray  # (n, 2) left reference POIs
    grid_shape: tuple[int, int] | None
    match: MatchOutcome
    #: Sampson distance of the reference correspondence, in pixels (spec S4.3).
    epipolar_px: np.ndarray
    X_ref: np.ndarray  # (n, 3) reference shape, NaN where unusable
    frames: tuple[Frame3D, ...]
    config: Dic3DConfig
    projections: tuple[np.ndarray, np.ndarray]
    left: Dic2DRun
    right: Dic2DRun | None
    provenance: dict[str, Any]

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def n_points(self) -> int:
        return int(self.points.shape[0])

    def shape_field(self) -> np.ndarray:
        """Reference surface as ``(ny, nx, 3)`` on a lattice, else ``(n, 3)``.

        Points with no usable correspondence are already NaN in
        :attr:`X_ref`, so there is nothing to mask here.
        """
        if self.grid_shape is None:
            return self.X_ref.copy()
        return self.X_ref.reshape(self.grid_shape + (3,))

    def valid_mask(self) -> np.ndarray:
        if not self.frames:
            return np.zeros((0, 0), dtype=bool)
        return self._shape(np.stack([f.valid for f in self.frames]))

    def field(self, name: str, masked: bool = True) -> np.ndarray:
        """A ``(n_frames, ny, nx)`` field, or ``(n_frames, n)`` off-lattice."""
        if name not in _FIELD_GETTERS:
            raise ValueError(
                f"unknown field {name!r}; expected one of "
                + ", ".join(sorted(_FIELD_GETTERS))
            )
        getter = _FIELD_GETTERS[name]
        if not self.frames:
            return np.zeros((0, 0), dtype=np.float64)
        stacked = np.stack([getter(f) for f in self.frames])
        if masked and name not in _INTEGER_FIELDS:
            stacked = stacked.astype(np.float64, copy=True)
            stacked[~np.stack([f.valid for f in self.frames])] = np.nan
        return self._shape(stacked)

    def _shape(self, stacked: np.ndarray) -> np.ndarray:
        if self.grid_shape is None or stacked.ndim != 2:
            return stacked
        if stacked.shape[1] != self.n_points:
            return stacked
        return stacked.reshape((stacked.shape[0],) + self.grid_shape)


_FIELD_GETTERS: dict[str, Callable[[Frame3D], np.ndarray]] = {
    "u": lambda f: f.displacement[:, 0],
    "v": lambda f: f.displacement[:, 1],
    "w": lambda f: f.displacement[:, 2],
    "magnitude": lambda f: f.magnitude,
    "x": lambda f: f.X[:, 0],
    "y": lambda f: f.X[:, 1],
    "z": lambda f: f.X[:, 2],
    "zncc_left": lambda f: f.zncc_left,
    "zncc_right": lambda f: f.zncc_right,
    "position_sigma_mm": lambda f: f.position_sigma_mm,
    "reprojection_px": lambda f: f.reprojection_px,
    "loop_px": lambda f: f.loop_px,
    "reject": lambda f: f.reject,
    "status_left": lambda f: f.status_left,
    "status_right": lambda f: f.status_right,
}

_INTEGER_FIELDS = frozenset({"reject", "status_left", "status_right"})


# --------------------------------------------------------------------------
# Cameras
# --------------------------------------------------------------------------


def _as_projection(camera: Any, name: str) -> np.ndarray:
    """A ``(3, 4)`` projection matrix from a matrix, a ``Camera`` or a rig side."""
    raw = getattr(camera, "P", camera)
    P = np.asarray(raw, dtype=np.float64)
    if P.size != 12:
        raise ValueError(
            f"{name} must be a 3x4 projection matrix or an object exposing one "
            f"as .P, got shape {P.shape}"
        )
    P = P.reshape(3, 4)
    if not np.all(np.isfinite(P)):
        raise ValueError(f"{name} contains non-finite entries")
    if abs(np.linalg.det(P[:, :3])) <= 0.0:
        raise ValueError(f"{name} has a singular leading 3x3 block")
    return P


def _projections(cameras: Any) -> tuple[np.ndarray, np.ndarray]:
    """Accept a :class:`hl3.stereo.StereoRig`, a camera pair or a matrix pair."""
    left = getattr(cameras, "left", None)
    right = getattr(cameras, "right", None)
    if left is None or right is None:
        try:
            items = list(cameras)
        except TypeError as error:
            raise TypeError(
                "cameras must be a StereoRig, or a pair of cameras / 3x4 "
                f"projection matrices, got {type(cameras).__name__}"
            ) from error
        if len(items) != 2:
            raise ValueError(
                f"cameras must supply exactly two views, got {len(items)}"
            )
        left, right = items
    return _as_projection(left, "left camera"), _as_projection(right, "right camera")


def _camera_center(P: np.ndarray) -> np.ndarray:
    return -np.linalg.solve(P[:, :3], P[:, 3])


def _principal_axis(P: np.ndarray) -> np.ndarray:
    """Unit world-frame direction the camera looks along."""
    M = P[:, :3]
    axis = np.sign(np.linalg.det(M)) * M[2, :]
    return axis / np.linalg.norm(axis)


def _viewing_rays(P: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Unit world-frame rays through ``points``, oriented towards the scene."""
    M = P[:, :3]
    homogeneous = np.column_stack([points, np.ones(points.shape[0])])
    d = np.linalg.solve(M, homogeneous.T).T
    d = d / np.linalg.norm(d, axis=1, keepdims=True)
    flip = (d @ P[2, :3]) < 0.0
    d[flip] *= -1.0
    return d


def _convergence_range(P_left: np.ndarray, P_right: np.ndarray) -> float | None:
    """Range along the left optical axis where the two axes come closest.

    For a converged stereo rig this is the standoff distance, recovered from
    the calibration alone -- no metadata, no user input. Returns ``None`` for a
    parallel rig, where the axes never approach and the caller must say what
    depth range to search instead of being handed a guess.
    """
    C1, C2 = _camera_center(P_left), _camera_center(P_right)
    d1, d2 = _principal_axis(P_left), _principal_axis(P_right)
    c = float(d1 @ d2)
    det = 1.0 - c * c
    if abs(det) < 1e-9:
        return None
    e = C1 - C2
    s = float((-(d1 @ e) + c * (d2 @ e)) / det)
    return s if s > 0.0 else None


# --------------------------------------------------------------------------
# Built-in reference stereo matcher
# --------------------------------------------------------------------------


def _subset_offsets(radius: int) -> tuple[np.ndarray, np.ndarray]:
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    dx, dy = np.meshgrid(offsets, offsets)
    return dx.ravel(), dy.ravel()


def _inside(
    centres: np.ndarray, shape: tuple[int, int], radius: int
) -> np.ndarray:
    """Centres whose whole subset, plus interpolation support, is on the image."""
    height, width = shape
    keep = np.all(np.isfinite(centres), axis=1)
    margin = radius + 2
    with np.errstate(invalid="ignore"):
        keep &= centres[:, 0] >= margin
        keep &= centres[:, 0] <= width - 1 - margin
        keep &= centres[:, 1] >= margin
        keep &= centres[:, 1] <= height - 1 - margin
    return keep


def _zero_mean(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    centred = values - values.mean(axis=1, keepdims=True)
    return centred, np.sqrt(np.sum(centred**2, axis=1))


def _sample_subsets(
    interp: BSplineInterpolator,
    centres: np.ndarray,
    dx: np.ndarray,
    dy: np.ndarray,
) -> np.ndarray:
    """Sample one subset per centre; centres must already be finite."""
    xs = centres[:, 0:1] + dx[None, :]
    ys = centres[:, 1:2] + dy[None, :]
    return interp.sample(xs, ys)


def _sweep_samples(
    P_right: np.ndarray,
    centre: np.ndarray,
    rays: np.ndarray,
    depth_range_mm: tuple[float, float],
    depth_samples: int | None,
    depth_step_px: float,
    max_depth_samples: int,
) -> np.ndarray:
    """Ranges to try, spaced so consecutive candidates are ~``depth_step_px`` apart.

    Spacing is uniform in *inverse* range because image displacement is linear
    in inverse range: uniform spacing in range would step by a fraction of a
    pixel in the far field and by tens of pixels near the camera, which is the
    one part of the sweep where a subset-based score has no peak to find.

    The sample count is derived from the geometry rather than configured,
    because the right number is a property of the rig: a 254 mm baseline at
    650 mm sweeps thousands of pixels across a +-35% depth range, and any fixed
    count that is right for one rig is wrong for the next.
    """
    near, far = depth_range_mm
    if depth_samples is not None:
        count = int(depth_samples)
    else:
        span = project(P_right, centre[None, :] + near * rays) - project(
            P_right, centre[None, :] + far * rays
        )
        path = _nanmax(np.linalg.norm(span, axis=1))
        if not math.isfinite(path):
            path = 0.0
        count = math.ceil(path / float(depth_step_px)) + 1
        count = min(max(count, 2), int(max_depth_samples))
    if count < 2:
        raise ValueError(f"depth_samples must be >= 2, got {count}")
    return 1.0 / np.linspace(1.0 / far, 1.0 / near, count)


def epipolar_depth_search(
    left: np.ndarray,
    right: np.ndarray,
    points: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    radius: int,
    depth_range_mm: tuple[float, float],
    depth_samples: int | None = None,
    depth_step_px: float = 2.0,
    max_depth_samples: int = 4096,
) -> tuple[np.ndarray, np.ndarray]:
    """Spec S5.1 stage B: scan the epipolar curve for the best ZNCC.

    Rather than walking a line in the right image, the search walks the left
    viewing ray through the world and projects each sample into the right
    camera. For a pinhole rig the two are the same curve, but the world
    parameterisation is the one that survives a distortion model (spec S6.3:
    the epipolar line is not straight then), and it gives every candidate a
    physical meaning -- a range -- instead of an abscissa.

    Two things keep the sweep affordable. Candidates whose subset falls off the
    right sensor are skipped before any pixel is touched, which for a converged
    rig is most of the sweep; and the score itself is evaluated on a decimated
    subset, since this stage only has to identify the basin that the IC-GN
    refinement will then descend.

    Returns ``(best_pixel, best_zncc)``; a point whose whole sweep leaves the
    right image comes back as NaN with a ZNCC of ``-1``.
    """
    near, far = (float(value) for value in depth_range_mm)
    if not 0.0 < near < far:
        raise ValueError(
            f"depth_range_mm must satisfy 0 < near < far, got {depth_range_mm}"
        )
    radius = int(radius)
    if radius < 1:
        raise ValueError(f"radius must be >= 1, got {radius}")

    stride = 2 if radius >= 6 else 1
    offsets = np.arange(-radius, radius + 1, stride, dtype=np.float64)
    dx, dy = (grid.ravel() for grid in np.meshgrid(offsets, offsets))

    n_points = int(points.shape[0])
    best = np.full((n_points, 2), np.nan)
    best_zncc = np.full(n_points, -1.0)

    on_left = np.flatnonzero(_inside(points, left.shape, radius))
    if on_left.size == 0:
        return best, best_zncc
    ref_centred, ref_norm = _zero_mean(
        _sample_subsets(BSplineInterpolator(left), points[on_left], dx, dy)
    )

    right_interp = BSplineInterpolator(right)
    centre = _camera_center(P_left)
    rays = _viewing_rays(P_left, points[on_left])
    ranges = _sweep_samples(
        P_right,
        centre,
        rays,
        (near, far),
        depth_samples,
        depth_step_px,
        max_depth_samples,
    )

    for distance in ranges:
        candidate = project(P_right, centre[None, :] + distance * rays)
        visible = np.flatnonzero(_inside(candidate, right.shape, radius))
        if visible.size == 0:
            continue
        centred, norm = _zero_mean(
            _sample_subsets(right_interp, candidate[visible], dx, dy)
        )
        scale = ref_norm[visible] * norm
        with np.errstate(invalid="ignore", divide="ignore"):
            zncc = np.where(
                scale > 0.0,
                np.sum(ref_centred[visible] * centred, axis=1) / scale,
                -1.0,
            )
        rows = on_left[visible]
        better = zncc > best_zncc[rows]
        improved = rows[better]
        best_zncc[improved] = zncc[better]
        best[improved] = candidate[visible][better]
    return best, best_zncc


def match_reference_stereo(
    left: np.ndarray,
    right: np.ndarray,
    points: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    params: ICGNParams | None = None,
    *,
    depth_range_mm: tuple[float, float] | None = None,
    depth_step_px: float = 2.0,
    depth_samples: int | None = None,
    max_depth_samples: int = 4096,
    depth_span: float = 0.35,
    seed_zncc_min: float = 0.5,
    guess: np.ndarray | None = None,
) -> MatchOutcome:
    """Match left POIs into the right image: epipolar sweep, then IC-GN.

    This is the fallback for :mod:`hl3.stereo.match` (spec S5.1 stages B--D
    without the feature-based stage A). It is a complete matcher, not a stub:
    the sweep supplies an initial guess good to a pixel or so anywhere in the
    stated depth range, and the IC-GN solve then owns the sub-pixel answer, so
    the accuracy is the reference kernel's rather than the search's.

    ``guess`` short-circuits the sweep with a caller-supplied ``(n, 2)`` array
    of right-image positions -- a previous run's correspondence, a CAD-derived
    prediction, or the output of a matcher that only produces integer results.
    """
    params = params or ICGNParams()
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    if left.shape != right.shape:
        raise ValueError(
            "the two views must share a pixel grid for the reference kernel, "
            f"got {left.shape} and {right.shape}"
        )
    n_points = int(points.shape[0])

    if guess is not None:
        seed = np.asarray(guess, dtype=np.float64)
        if seed.shape != (n_points, 2):
            raise ValueError(
                f"guess must have shape ({n_points}, 2), got {seed.shape}"
            )
        seed_zncc = None
        seeded = _inside(seed, right.shape, params.subset_radius)
    else:
        if depth_range_mm is None:
            converged = _convergence_range(P_left, P_right)
            if converged is None:
                raise ValueError(
                    "the two optical axes do not converge, so no depth range "
                    "can be derived; pass depth_range_mm explicitly"
                )
            depth_range_mm = (
                converged * (1.0 - depth_span),
                converged * (1.0 + depth_span),
            )
        seed, seed_zncc = epipolar_depth_search(
            left,
            right,
            points,
            P_left,
            P_right,
            params.subset_radius,
            depth_range_mm,
            depth_samples=depth_samples,
            depth_step_px=depth_step_px,
            max_depth_samples=max_depth_samples,
        )
        seeded = seed_zncc >= seed_zncc_min

    x_right = np.full((n_points, 2), np.nan)
    zncc = np.full(n_points, -1.0)
    status = np.full(n_points, int(Status.NO_INITIAL_GUESS), dtype=np.int32)

    selected = np.flatnonzero(seeded)
    if selected.size:
        solved = icgn(
            left,
            right,
            points[selected],
            params,
            seed[selected] - points[selected],
        )
        moved = np.column_stack([solved.u, solved.v]) + points[selected]
        status[selected] = solved.status
        zncc[selected] = solved.zncc
        converged = solved.status == int(Status.CONVERGED)
        x_right[selected[converged]] = moved[converged]

    return MatchOutcome(
        points=points.copy(),
        x_right=x_right,
        zncc=zncc,
        status=status,
        backend="hl3.pipeline.dic3d.match_reference_stereo",
        reason=(
            "built-in epipolar depth search + IC-GN"
            if guess is None
            else "built-in IC-GN refinement of a caller-supplied guess"
        ),
        seed_zncc=seed_zncc,
    )


# --------------------------------------------------------------------------
# hl3.stereo.match hand-off
# --------------------------------------------------------------------------

#: Entry points looked up in :mod:`hl3.stereo.match`, in order of preference.
#: ``match_stereo_pair`` is the one that module actually exposes; the rest are
#: kept because this pipeline has to run against the module as it is *and* as
#: it was before it landed, and a renamed entry point must degrade to the
#: built-in search rather than break the run.
MATCH_ENTRY_POINTS: tuple[str, ...] = (
    "match_stereo_pair",
    "match_reference_stereo",
    "match_stereo",
    "stereo_match",
    "match_epipolar",
    "epipolar_match",
    "match_points",
    "match",
)

#: Parameter classes a matcher module may want its settings wrapped in.
MATCH_PARAM_CLASSES: tuple[str, ...] = ("StereoMatchParams", "MatchParams")


def resolve_match_backend(
    override: Callable[..., Any] | None = None,
) -> tuple[Callable[..., Any] | None, str | None, str]:
    """Find a stereo matcher. Returns ``(callable, name, reason)``."""
    if override is not None:
        name = getattr(override, "__name__", repr(override))
        return override, name, f"using the caller-supplied backend {name!r}"

    try:
        module = importlib.import_module("hl3.stereo.match")
    except Exception as error:  # noqa: BLE001
        detail = f"{type(error).__name__}: {error}"
        return (
            None,
            None,
            (
                f"hl3.stereo.match is not importable ({detail}); using the "
                "built-in epipolar search"
            ),
        )

    for attribute in MATCH_ENTRY_POINTS:
        candidate = getattr(module, attribute, None)
        if callable(candidate):
            name = f"hl3.stereo.match.{attribute}"
            return candidate, name, name
    return (
        None,
        None,
        "hl3.stereo.match exposes none of the expected entry points ("
        + ", ".join(MATCH_ENTRY_POINTS)
        + "); using the built-in epipolar search",
    )


def _accepted(
    backend: Callable[..., Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Drop payload keys the backend does not declare.

    A ``**kwargs`` backend gets the canonical subset rather than every alias:
    handing it ``left``, ``left_image`` and ``reference`` for the same array
    would be three chances for it to bind the wrong one.
    """
    try:
        signature = inspect.signature(backend)
    except (TypeError, ValueError):
        return {key: payload[key] for key in _CANONICAL_MATCH_KEYS if key in payload}

    parameters = list(signature.parameters.values())
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
        return {key: payload[key] for key in _CANONICAL_MATCH_KEYS if key in payload}
    names = {
        p.name
        for p in parameters
        if p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in payload.items() if key in names}


#: What a ``**kwargs`` backend is given: the arguments whose meaning is fixed
#: by their name, and no aliases. ``rig`` and the two ``P`` matrices carry the
#: same geometry under different spellings and are all unambiguous, so both
#: conventions are supplied.
_CANONICAL_MATCH_KEYS = (
    "left",
    "right",
    "points",
    "rig",
    "P_left",
    "P_right",
    "params",
)

#: Attribute / key names a backend may use for the matched right-image points.
_RIGHT_POINT_KEYS = (
    "right_xy",
    "x_right",
    "points_right",
    "right_points",
    "x2",
    "xr",
    "matches",
    "points",
)


def _backend_params(backend: Callable[..., Any], config: Dic3DConfig) -> Any:
    """Wrap this pipeline's settings in whatever the backend's module expects.

    :func:`hl3.stereo.match.match_stereo_pair` takes a ``StereoMatchParams``,
    not the bare :class:`~hl3.correlate.ICGNParams` a matcher without a
    parameter class would want. Building it here keeps one policy in one place:
    the pipeline's correlation settings *and* its epipolar ceiling are handed
    down, rather than the backend quietly applying its own default Sampson gate
    underneath a run that reports ``max_epipolar_px`` as its gate.

    Anything that goes wrong raises, and the caller records a fallback.
    Substituting the backend's own defaults instead would silently match with a
    different subset size from the one the run reports.
    """
    module = sys.modules.get(getattr(backend, "__module__", ""))
    factory = None
    for name in MATCH_PARAM_CLASSES:
        factory = getattr(module, name, None)
        if factory is not None:
            break
    if factory is None:
        return config.stereo_params

    wanted = {
        "icgn": config.stereo_params,
        # The backend's geometric gate is switched off, not handed this run's
        # ceiling: the pipeline measures the Sampson distance itself and gates
        # on it in one place, so a rejected point is attributed to
        # ``RejectReason.EPIPOLAR`` instead of being indistinguishable from a
        # correlation failure -- and a backend default cannot quietly tighten
        # a run that reports ``max_epipolar_px`` as its only epipolar gate.
        "max_sampson_px": math.inf,
        "margin": config.margin,
    }
    return factory(**_accepted(factory, wanted))


def _match_payload(
    left: np.ndarray,
    right: np.ndarray,
    points: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    params: Any,
    config: Dic3DConfig,
    depth_range_mm: tuple[float, float] | None,
    guess: np.ndarray | None,
) -> dict[str, Any]:
    """Every spelling of the arguments a stereo matcher might declare.

    A caller-supplied correspondence reaches an external backend as a
    *disparity* seed, which is the form both this package's kernel and
    :func:`hl3.stereo.match.match_stereo_pair` take. Dropping it on the way to
    the backend would quietly ignore the one thing the caller stated outright.
    """
    disparity = None if guess is None else guess - points
    return {
        "left": left,
        "right": right,
        "left_image": left,
        "right_image": right,
        "reference": left,
        "target": right,
        "points": points,
        "points_left": points,
        "x_left": points,
        "x1": points,
        "rig": (P_left, P_right),
        "P_left": P_left,
        "P_right": P_right,
        "P1": P_left,
        "P2": P_right,
        "params": params,
        "icgn": config.stereo_params,
        "initial_guess": disparity,
        "guess": guess,
        "depth_range_mm": depth_range_mm,
        "depth_step_px": config.depth_step_px,
        "depth_samples": config.depth_samples,
        "seed_zncc_min": config.seed_zncc_min,
    }


def _normalise_match_output(result: Any, n_points: int) -> MatchOutcome:
    """Turn whatever a matcher returned into a :class:`MatchOutcome`."""
    if isinstance(result, MatchOutcome):
        if result.n_points != n_points:
            raise ValueError(
                f"matcher returned {result.n_points} points, expected {n_points}"
            )
        return result
    if isinstance(result, np.ndarray):
        lookup: Callable[[str], Any] = {"right_xy": result}.get
    elif isinstance(result, Mapping) or hasattr(result, "__dict__") or hasattr(
        result, "_asdict"
    ):
        lookup = _field_lookup(result)
    else:
        raise TypeError(
            "stereo matcher must return an (n, 2) array, a mapping or an "
            f"object carrying one, got {type(result).__name__}"
        )

    x_right = None
    for key in _RIGHT_POINT_KEYS:
        candidate = lookup(key)
        if candidate is None:
            continue
        array = np.asarray(candidate, dtype=np.float64)
        if array.shape == (n_points, 2):
            x_right = array.copy()
            break
    if x_right is None:
        raise ValueError(
            f"stereo matcher returned no ({n_points}, 2) array of right-image "
            "points under any of " + ", ".join(_RIGHT_POINT_KEYS)
        )

    zncc = _optional_vector(lookup, ("zncc", "score"), n_points)
    status = _optional_vector(lookup, ("status",), n_points)
    finite = np.all(np.isfinite(x_right), axis=1)
    if status is None:
        status = np.where(finite, int(Status.CONVERGED), int(Status.NOT_CONVERGED))
    status = status.astype(np.int32)

    accepted = _optional_vector(lookup, ("accepted", "valid", "mask"), n_points)
    if accepted is not None:
        # A point the backend's own quality gate dropped did not fail to
        # correlate, it was excluded, so it is reported as MASKED rather than
        # as a solver failure it never suffered.
        gated = (status == int(Status.CONVERGED)) & ~accepted.astype(bool)
        status[gated] = int(Status.MASKED)
    status[(status == int(Status.CONVERGED)) & ~finite] = int(Status.NOT_CONVERGED)
    x_right[status != int(Status.CONVERGED)] = np.nan
    return MatchOutcome(
        points=np.zeros((n_points, 2)),
        x_right=x_right,
        zncc=np.full(n_points, np.nan) if zncc is None else zncc,
        status=status,
        backend="",
        reason="",
    )


def _field_lookup(result: Any) -> Callable[[str], Any]:
    """Read a named field off a mapping, a namedtuple or a plain object.

    Attributes are consulted after ``__dict__`` so that a dataclass exposing
    ``status`` and ``zncc`` as *properties* over a nested correlation result --
    which is exactly how :class:`hl3.stereo.match.StereoMatchResult` is built
    -- is read as completely as a flat mapping would be.
    """
    if isinstance(result, Mapping):
        fields: Mapping[str, Any] = result
    elif hasattr(result, "_asdict"):
        fields = result._asdict()
    else:
        fields = vars(result)

    def lookup(key: str) -> Any:
        value = fields.get(key)
        return getattr(result, key, None) if value is None else value

    return lookup


def _optional_vector(
    lookup: Callable[[str], Any], keys: Sequence[str], n_points: int
) -> np.ndarray | None:
    for key in keys:
        value = lookup(key)
        if value is None:
            continue
        array = np.asarray(value).reshape(-1)
        if array.size == n_points:
            return array
    return None


def _reference_match(
    left: np.ndarray,
    right: np.ndarray,
    points: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    config: Dic3DConfig,
    guess: np.ndarray | None,
) -> MatchOutcome:
    """Run the reference stereo match through whichever backend is available."""
    depth_range = config.depth_range_mm
    fallback_reason = ""
    if config.match_mode is not MatchMode.INTERNAL:
        backend, name, reason = resolve_match_backend(config.match_backend)
        if backend is None:
            if config.match_mode is MatchMode.REQUIRED:
                raise MatchUnavailableError(reason)
            fallback_reason = reason
        else:
            try:
                payload = _match_payload(
                    left,
                    right,
                    points,
                    P_left,
                    P_right,
                    _backend_params(backend, config),
                    config,
                    depth_range,
                    guess,
                )
                outcome = _normalise_match_output(
                    backend(**_accepted(backend, payload)), points.shape[0]
                )
            except (TypeError, ValueError) as error:
                detail = f"{name} failed: {type(error).__name__}: {error}"
                if config.match_mode is MatchMode.REQUIRED:
                    raise MatchUnavailableError(detail) from error
                fallback_reason = detail
            else:
                merged = MatchOutcome(
                    points=points.copy(),
                    x_right=outcome.x_right,
                    zncc=outcome.zncc,
                    status=outcome.status,
                    backend=name or outcome.backend,
                    reason=reason,
                    seed_zncc=outcome.seed_zncc,
                )
                if config.match_mode is MatchMode.REQUIRED:
                    return merged
                return _complete_match(
                    merged, left, right, P_left, P_right, config, guess
                )

    internal = _internal_match(left, right, points, P_left, P_right, config, guess)
    if not fallback_reason:
        return internal
    return MatchOutcome(
        points=internal.points,
        x_right=internal.x_right,
        zncc=internal.zncc,
        status=internal.status,
        backend=internal.backend,
        reason=f"{fallback_reason}; fell back to {internal.reason}",
        seed_zncc=internal.seed_zncc,
    )


def _internal_match(
    left: np.ndarray,
    right: np.ndarray,
    points: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    config: Dic3DConfig,
    guess: np.ndarray | None,
) -> MatchOutcome:
    return match_reference_stereo(
        left,
        right,
        points,
        P_left,
        P_right,
        config.stereo_params,
        depth_range_mm=config.depth_range_mm,
        depth_step_px=config.depth_step_px,
        depth_samples=config.depth_samples,
        max_depth_samples=config.max_depth_samples,
        depth_span=config.depth_span,
        seed_zncc_min=config.seed_zncc_min,
        guess=guess,
    )


def _complete_match(
    outcome: MatchOutcome,
    left: np.ndarray,
    right: np.ndarray,
    P_left: np.ndarray,
    P_right: np.ndarray,
    config: Dic3DConfig,
    guess: np.ndarray | None,
) -> MatchOutcome:
    """Search for the points the backend left unmatched, keeping the ones it got.

    A matcher seeded from a nominal plane -- which is what
    :func:`hl3.stereo.match.match_stereo_pair` does -- loses the parts of a
    tilted or curved surface that sit far enough off that plane for the seed to
    fall outside the solver's convergence radius. Those points are exactly what
    an explicit depth sweep is for, and running it only where the cheap stage
    failed is the whole point of a hierarchical matcher.

    No accepted match is touched, so this cannot silently change a number the
    backend produced; it can only fill in ones it did not. Points the backend
    *excluded* -- reported as :attr:`hl3.correlate.Status.MASKED` -- are left
    alone too: a quality judgement is not a gap to be filled.
    """
    missing = np.flatnonzero(~outcome.valid & (outcome.status != int(Status.MASKED)))
    if missing.size == 0:
        return outcome

    points = outcome.points
    try:
        recovered = _internal_match(
            left,
            right,
            points[missing],
            P_left,
            P_right,
            config,
            None if guess is None else guess[missing],
        )
    except ValueError as error:
        return _reasoned(
            outcome,
            f"{outcome.reason}; {missing.size} unmatched points were left as "
            f"they are ({type(error).__name__}: {error})",
        )

    x_right = outcome.x_right.copy()
    zncc = outcome.zncc.copy()
    status = outcome.status.copy()
    filled = recovered.valid
    x_right[missing[filled]] = recovered.x_right[filled]
    zncc[missing[filled]] = recovered.zncc[filled]
    status[missing[filled]] = recovered.status[filled]

    seed_zncc = outcome.seed_zncc
    if recovered.seed_zncc is not None:
        seed_zncc = np.full(points.shape[0], np.nan)
        seed_zncc[missing] = recovered.seed_zncc
    return MatchOutcome(
        points=points,
        x_right=x_right,
        zncc=zncc,
        status=status,
        backend=outcome.backend,
        reason=(
            f"{outcome.reason}; the built-in epipolar search recovered "
            f"{int(np.count_nonzero(filled))} of its {missing.size} "
            "unmatched points"
        ),
        seed_zncc=seed_zncc,
    )


def _reasoned(outcome: MatchOutcome, reason: str) -> MatchOutcome:
    return MatchOutcome(
        points=outcome.points,
        x_right=outcome.x_right,
        zncc=outcome.zncc,
        status=outcome.status,
        backend=outcome.backend,
        reason=reason,
        seed_zncc=outcome.seed_zncc,
    )


# --------------------------------------------------------------------------
# Triangulation
# --------------------------------------------------------------------------


def triangulate_correspondence(
    P_left: np.ndarray,
    P_right: np.ndarray,
    x_left: np.ndarray,
    x_right: np.ndarray,
    method: Triangulator = Triangulator.DLT,
) -> np.ndarray:
    """One rung of spec S6.1, with unobserved points filtered out first.

    Every rung is fed only the points that are finite in both views. The
    pooled estimators (DLT, Gauss--Newton) would otherwise have to defend
    themselves against a single dropped POI turning a batched SVD or solve into
    an exception for the whole field.
    """
    x_left = np.asarray(x_left, dtype=np.float64)
    x_right = np.asarray(x_right, dtype=np.float64)
    if x_left.shape != x_right.shape or x_left.ndim != 2 or x_left.shape[1] != 2:
        raise ValueError(
            "x_left and x_right must both be (n, 2) arrays, got "
            f"{x_left.shape} and {x_right.shape}"
        )
    out = np.full((x_left.shape[0], 3), np.nan)
    observed = np.all(np.isfinite(x_left), axis=1) & np.all(
        np.isfinite(x_right), axis=1
    )
    if not observed.any():
        return out
    left, right = x_left[observed], x_right[observed]

    if method is Triangulator.MIDPOINT:
        X = triangulate_midpoint(P_left, P_right, left, right)
    elif method is Triangulator.DLT:
        X = triangulate_dlt(P_left, P_right, left, right)
    elif method is Triangulator.OPTIMAL:
        X = triangulate_optimal(P_left, P_right, left, right)
    elif method is Triangulator.NONLINEAR:
        X = triangulate_nonlinear([P_left, P_right], [left, right])
    else:  # pragma: no cover - the enum is closed
        raise ValueError(f"unknown triangulator {method!r}")
    out[observed] = X
    return out


def _per_point_reprojection(
    P_left: np.ndarray,
    P_right: np.ndarray,
    x_left: np.ndarray,
    x_right: np.ndarray,
    X: np.ndarray,
) -> np.ndarray:
    """RMS reprojection residual per point over the two views, in pixels."""
    finite = np.all(np.isfinite(X), axis=1)
    out = np.full(X.shape[0], np.nan)
    if not finite.any():
        return out
    residuals = reprojection_residuals(
        [P_left, P_right], [x_left[finite], x_right[finite]], X[finite]
    )
    out[finite] = np.sqrt(np.mean(residuals**2, axis=(0, 2)) * 2.0)
    return out


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def run_stereo_sequence(
    left_images: Any,
    right_images: Any,
    cameras: Any,
    config: Dic3DConfig | None = None,
    *,
    points: np.ndarray | None = None,
    right_points: np.ndarray | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Dic3DRun:
    """Correlate a stereo sequence into world-frame ``U, V, W``.

    Parameters
    ----------
    left_images, right_images:
        Two synchronised sequences of the same length: arrays, lists of arrays,
        or iterables of capture frames, exactly as
        :func:`hl3.pipeline.dic2d.run_sequence` accepts. Frame ``i`` of each
        must be the same instant -- this pipeline has no way to detect, and
        makes no attempt to repair, a synchronisation error.
    cameras:
        A :class:`hl3.stereo.StereoRig`, a pair of :class:`hl3.stereo.Camera`,
        or a pair of ``(3, 4)`` projection matrices.
    points:
        ``(n, 2)`` left-image POI centres in the reference frame; a regular
        grid from :func:`hl3.correlate.make_grid` is built when omitted.
    right_points:
        Known reference correspondence, if there is one. Supplying it skips the
        epipolar search entirely and the IC-GN refinement starts from it.
    progress:
        Called as ``progress(done, total)`` after each frame is triangulated.

    The reference frame is processed like any other and comes back with
    displacement identically zero, because both views correlate the reference
    against itself and the two triangulations are then the same computation on
    the same inputs. That zero is a useful assertion, not a special case: any
    departure from it would mean the two paths were not in fact the same.
    """
    config = config or Dic3DConfig()
    P_left, P_right = _projections(cameras)

    left_items, left_frames = _frames(left_images, "left_images")
    right_items, right_frames = _frames(right_images, "right_images")
    if len(left_frames) != len(right_frames):
        raise ValueError(
            "the two views must supply the same number of frames, got "
            f"{len(left_frames)} and {len(right_frames)}"
        )
    if left_frames[0].shape != right_frames[0].shape:
        raise ValueError(
            "the two views must share a pixel grid, got "
            f"{left_frames[0].shape} and {right_frames[0].shape}"
        )
    n_frames = len(left_frames)
    if config.reference_index >= n_frames:
        raise ValueError(
            f"reference_index {config.reference_index} is outside the "
            f"{n_frames}-frame sequence"
        )

    reference = config.reference_index
    if points is None:
        grid = make_grid(
            left_frames[reference].shape, config.icgn, margin=config.margin
        )
    else:
        grid = np.asarray(points, dtype=np.float64)
        if grid.ndim != 2 or grid.shape[1] != 2:
            raise ValueError(
                f"points must be an (n, 2) array of (x, y), got {grid.shape}"
            )
        if not np.all(np.isfinite(grid)):
            raise ValueError("points must be finite")
        grid = grid.copy()
    n_points = int(grid.shape[0])

    guess = None
    if right_points is not None:
        guess = np.asarray(right_points, dtype=np.float64)
        if guess.shape != (n_points, 2):
            raise ValueError(
                f"right_points must have shape ({n_points}, 2), got {guess.shape}"
            )

    match = _reference_match(
        left_frames[reference],
        right_frames[reference],
        grid,
        P_left,
        P_right,
        config,
        guess,
    )

    epipolar = _epipolar_residual(P_left, P_right, grid, match.x_right)
    matched = match.valid.copy()
    if math.isfinite(config.max_epipolar_px):
        with np.errstate(invalid="ignore"):
            matched &= np.nan_to_num(epipolar, nan=np.inf) <= config.max_epipolar_px

    X_ref = triangulate_correspondence(
        P_left, P_right, grid, np.where(matched[:, None], match.x_right, np.nan),
        config.triangulator,
    )
    base_reject = np.where(
        match.valid, int(RejectReason.NONE), int(RejectReason.NO_STEREO_MATCH)
    ).astype(np.int32)
    base_reject[match.valid & ~matched] = int(RejectReason.EPIPOLAR)
    shape_ok = np.all(np.isfinite(X_ref), axis=1)
    base_reject[matched & ~shape_ok] = int(RejectReason.TRIANGULATION)
    X_ref[~shape_ok] = np.nan

    temporal = config.temporal_config()
    left_run = run_sequence_2d(left_items, temporal, points=grid)
    right_run: Dic2DRun | None = None
    tracked = np.flatnonzero(matched & shape_ok)
    if tracked.size:
        right_run = run_sequence_2d(
            right_items, temporal, points=match.x_right[tracked]
        )

    frames: list[Frame3D] = []
    for index in range(n_frames):
        frames.append(
            _build_frame(
                index=index,
                config=config,
                P_left=P_left,
                P_right=P_right,
                grid=grid,
                match=match,
                X_ref=X_ref,
                base_reject=base_reject,
                tracked=tracked,
                left_run=left_run,
                right_run=right_run,
                left_image=left_frames[index],
                right_image=right_frames[index],
                reference_left=left_frames[reference],
            )
        )
        if progress is not None:
            progress(len(frames), n_frames)

    grid_shape = lattice_shape(grid)
    provenance = _provenance(
        config, match, epipolar, X_ref, frames, grid, grid_shape, P_left, P_right
    )
    return Dic3DRun(
        points=grid,
        grid_shape=grid_shape,
        match=match,
        epipolar_px=epipolar,
        X_ref=X_ref,
        frames=tuple(frames),
        config=config,
        projections=(P_left, P_right),
        left=left_run,
        right=right_run,
        provenance=provenance,
    )


def correlate_stereo_pair(
    left_reference: np.ndarray,
    right_reference: np.ndarray,
    left_deformed: np.ndarray,
    right_deformed: np.ndarray,
    cameras: Any,
    config: Dic3DConfig | None = None,
    *,
    points: np.ndarray | None = None,
    right_points: np.ndarray | None = None,
) -> Dic3DRun:
    """Two-frame convenience wrapper: reference pair in, deformed pair in."""
    return run_stereo_sequence(
        [left_reference, left_deformed],
        [right_reference, right_deformed],
        cameras,
        config,
        points=points,
        right_points=right_points,
    )


def _frames(images: Any, name: str) -> tuple[list[Any], list[np.ndarray]]:
    """Materialise an image source into ``(items, arrays)``.

    Deliberately permissive in the same way as the 2D pipeline: a stack, a list
    of arrays, or any iterable of objects carrying an ``image`` attribute. The
    original items are kept alongside the arrays because the 2D sub-runs are
    handed the items and read timestamps and frame indices off them -- and
    because a one-shot iterable must be consumed exactly once, here.
    """
    if isinstance(images, np.ndarray):
        items: list[Any] = (
            [images[i] for i in range(images.shape[0])] if images.ndim == 3
            else [images]
        )
    else:
        try:
            items = list(images)
        except TypeError as error:
            raise TypeError(
                f"{name} must be a 3-D array, a sequence of 2-D arrays or an "
                f"iterable of capture frames, got {type(images).__name__}"
            ) from error

    arrays: list[np.ndarray] = []
    for position, item in enumerate(items):
        array = np.asarray(getattr(item, "image", item), dtype=np.float64)
        if array.ndim != 2:
            raise ValueError(
                f"{name}[{position}] must be a 2-D greyscale image, got "
                f"{array.ndim}-D"
            )
        arrays.append(array)
    if not arrays:
        raise ValueError(f"{name} must contain at least one frame")
    return items, arrays


def _epipolar_residual(
    P_left: np.ndarray, P_right: np.ndarray, x_left: np.ndarray, x_right: np.ndarray
) -> np.ndarray:
    """Sampson distance of the reference correspondence, in pixels."""
    observed = np.all(np.isfinite(x_right), axis=1)
    out = np.full(x_left.shape[0], np.nan)
    if not observed.any():
        return out
    F = fundamental_from_projections(P_left, P_right)
    out[observed] = sampson_distance(F, x_left[observed], x_right[observed])
    return out


def _scatter(
    values: np.ndarray, index: np.ndarray, n_points: int, fill: Any
) -> np.ndarray:
    """Place a tracked-subset array back into full-length POI order."""
    out = np.full((n_points,) + values.shape[1:], fill, dtype=values.dtype)
    out[index] = values
    return out


def _build_frame(
    *,
    index: int,
    config: Dic3DConfig,
    P_left: np.ndarray,
    P_right: np.ndarray,
    grid: np.ndarray,
    match: MatchOutcome,
    X_ref: np.ndarray,
    base_reject: np.ndarray,
    tracked: np.ndarray,
    left_run: Dic2DRun,
    right_run: Dic2DRun | None,
    left_image: np.ndarray,
    right_image: np.ndarray,
    reference_left: np.ndarray,
) -> Frame3D:
    """Assemble one frame: two 2D solutions in, one gated 3D field out."""
    n_points = int(grid.shape[0])
    left_frame = left_run.frames[index]
    reject = base_reject.copy()

    x_left = np.full((n_points, 2), np.nan)
    left_valid = left_frame.valid
    x_left[left_valid] = grid[left_valid] + np.column_stack(
        [left_frame.u[left_valid], left_frame.v[left_valid]]
    )
    reject[(reject == int(RejectReason.NONE)) & ~left_valid] = int(
        RejectReason.LEFT_MATCH
    )

    x_right = np.full((n_points, 2), np.nan)
    zncc_right = np.full(n_points, np.nan)
    status_right = np.full(n_points, int(Status.UNCOMPUTED), dtype=np.int32)
    if right_run is not None:
        right_frame = right_run.frames[index]
        right_valid = _scatter(right_frame.valid, tracked, n_points, False)
        moved = match.x_right[tracked] + np.column_stack(
            [right_frame.u, right_frame.v]
        )
        placed = _scatter(moved, tracked, n_points, np.nan)
        x_right[right_valid] = placed[right_valid]
        zncc_right = _scatter(right_frame.zncc, tracked, n_points, np.nan)
        status_right = _scatter(
            right_frame.status.astype(np.int32), tracked, n_points,
            int(Status.UNCOMPUTED),
        )
    else:
        right_valid = np.zeros(n_points, dtype=bool)
    reject[(reject == int(RejectReason.NONE)) & ~right_valid] = int(
        RejectReason.RIGHT_MATCH
    )

    solvable = reject == int(RejectReason.NONE)
    X = np.full((n_points, 3), np.nan)
    if solvable.any():
        X[solvable] = triangulate_correspondence(
            P_left,
            P_right,
            x_left[solvable],
            x_right[solvable],
            config.triangulator,
        )
    finite = np.all(np.isfinite(X), axis=1)
    reject[solvable & ~finite] = int(RejectReason.TRIANGULATION)

    ahead = np.zeros(n_points, dtype=bool)
    if finite.any():
        ahead[finite] = cheirality_mask([P_left, P_right], X[finite])
    reject[finite & ~ahead] = int(RejectReason.CHEIRALITY)

    sigma = np.full(n_points, np.nan)
    if ahead.any():
        sigma[ahead] = position_sigma(
            triangulation_covariance(
                [P_left, P_right], X[ahead], sigma_px=config.sigma_px
            )
        )
    if math.isfinite(config.max_position_sigma_mm):
        with np.errstate(invalid="ignore"):
            over = ahead & ~(sigma < config.max_position_sigma_mm)
        reject[over] = int(RejectReason.UNCERTAINTY)

    loop = np.full(n_points, np.nan)
    if config.loop_closure:
        loop = _loop_residual(
            config=config,
            grid=grid,
            match=match,
            x_left=x_left,
            x_right=x_right,
            candidates=reject == int(RejectReason.NONE),
            left_image=left_image,
            right_image=right_image,
            reference_left=reference_left,
        )
        if math.isfinite(config.max_loop_px):
            with np.errstate(invalid="ignore"):
                over = (reject == int(RejectReason.NONE)) & ~(
                    loop <= config.max_loop_px
                )
            reject[over] = int(RejectReason.LOOP_CLOSURE)

    valid = reject == int(RejectReason.NONE)
    X[~valid] = np.nan
    displacement = np.full((n_points, 3), np.nan)
    displacement[valid] = X[valid] - X_ref[valid]
    reprojection = _per_point_reprojection(P_left, P_right, x_left, x_right, X)

    return Frame3D(
        index=index,
        frame_index=left_frame.frame_index,
        x_left=x_left,
        x_right=x_right,
        X=X,
        displacement=displacement,
        valid=valid,
        reject=reject,
        status_left=left_frame.status.astype(np.int32),
        status_right=status_right,
        zncc_left=left_frame.zncc.copy(),
        zncc_right=zncc_right,
        position_sigma_mm=sigma,
        reprojection_px=reprojection,
        loop_px=loop,
        timestamp_s=left_frame.timestamp_s,
    )


def _loop_residual(
    *,
    config: Dic3DConfig,
    grid: np.ndarray,
    match: MatchOutcome,
    x_left: np.ndarray,
    x_right: np.ndarray,
    candidates: np.ndarray,
    left_image: np.ndarray,
    right_image: np.ndarray,
    reference_left: np.ndarray,
) -> np.ndarray:
    """Four-way loop residual of spec S6.4, in pixels.

    Legs one and two -- the reference stereo match and the right-view temporal
    match -- are already solved, so only the return path is correlated here:

    ``right_def -> left_def`` (stereo at the deformed frame), seeded with the
    *reference* disparity, and ``left_def -> left_ref`` (the inverse temporal
    match), seeded with the negated first leg. Both seeds come from inside the
    loop, so the residual never consults the left-view temporal solution it
    exists to audit; a systematic error in that solution shows up here instead
    of being absorbed by the seed.
    """
    n_points = int(grid.shape[0])
    out = np.full(n_points, np.nan)
    selected = np.flatnonzero(candidates)
    if selected.size == 0:
        return out

    params = config.stereo_params
    disparity = grid[selected] - match.x_right[selected]
    back = icgn(
        right_image, left_image, x_right[selected], params, disparity
    )
    back_ok = back.status == int(Status.CONVERGED)
    left_def = x_right[selected] + np.column_stack([back.u, back.v])

    index = selected[back_ok]
    if index.size == 0:
        return out
    closed = left_def[back_ok]
    home = icgn(
        left_image, reference_left, closed, params, grid[index] - closed
    )
    home_ok = home.status == int(Status.CONVERGED)
    recovered = closed + np.column_stack([home.u, home.v])
    residual = np.linalg.norm(recovered - grid[index], axis=1)
    out[index[home_ok]] = residual[home_ok]
    return out


def _provenance(
    config: Dic3DConfig,
    match: MatchOutcome,
    epipolar: np.ndarray,
    X_ref: np.ndarray,
    frames: Sequence[Frame3D],
    grid: np.ndarray,
    grid_shape: tuple[int, int] | None,
    P_left: np.ndarray,
    P_right: np.ndarray,
) -> dict[str, Any]:
    """Parameter and quality snapshot for the report (spec S13 / R1-O3)."""
    params = config.icgn
    stereo = config.stereo_params
    valid = [frame.valid_fraction for frame in frames]
    loop = np.concatenate([frame.loop_px for frame in frames]) if frames else (
        np.zeros(0)
    )
    reprojection = (
        np.concatenate([frame.reprojection_px for frame in frames])
        if frames
        else np.zeros(0)
    )
    baseline = float(
        np.linalg.norm(_camera_center(P_left) - _camera_center(P_right))
    )
    return {
        "solver": "hl3.correlate.icgn",
        "stereo_matcher": match.backend,
        "stereo_match_reason": match.reason,
        "temporal_pipeline": "hl3.pipeline.dic2d.run_sequence",
        "triangulator": config.triangulator.value,
        "distortion_model": "pinhole_L0",
        "deterministic": True,
        "backend": "cpu-numpy",
        "n_frames": len(frames),
        "n_points": int(grid.shape[0]),
        "grid_shape": grid_shape,
        "subset_size": params.subset_size,
        "step": params.step,
        "stereo_shape_order": stereo.shape_order,
        "temporal_shape_order": 1,
        "seed_mode": config.seed_mode.value,
        "reference_mode": config.reference_mode.value,
        "reference_index": config.reference_index,
        "baseline_mm": baseline,
        "convergence_range_mm": _convergence_range(P_left, P_right),
        "match_mode": config.match_mode.value,
        "matched_fraction": match.matched_fraction,
        "shape_points": int(np.count_nonzero(np.all(np.isfinite(X_ref), axis=1))),
        "epipolar_sampson_px_median": _nanmedian(epipolar),
        "epipolar_sampson_px_max": _nanmax(epipolar),
        "reprojection_px_median": _nanmedian(reprojection),
        "loop_closure": config.loop_closure,
        "loop_px_median": _nanmedian(loop),
        "loop_px_p95": _nanquantile(loop, 0.95),
        "sigma_px": config.sigma_px,
        "max_position_sigma_mm": config.max_position_sigma_mm,
        "max_epipolar_px": config.max_epipolar_px,
        "max_loop_px": config.max_loop_px,
        "valid_fraction_min": min(valid) if valid else 0.0,
        "valid_fraction_mean": float(np.mean(valid)) if valid else 0.0,
    }


def _finite(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    return array[np.isfinite(array)]


def _nanmedian(values: np.ndarray) -> float:
    finite = _finite(values)
    return float(np.median(finite)) if finite.size else math.nan


def _nanmax(values: np.ndarray) -> float:
    finite = _finite(values)
    return float(finite.max()) if finite.size else math.nan


def _nanquantile(values: np.ndarray, q: float) -> float:
    finite = _finite(values)
    return float(np.quantile(finite, q)) if finite.size else math.nan
