# SPDX-License-Identifier: Apache-2.0
"""Stereo correspondence in the reference frame: left image POI -> right image.

This module is the S2 half of the HL3-3D chain described in
``.agent_workspace/round1/R1-O2-hl3-3d-spec.md`` section 5: it turns a
*synchronised image pair* into *pixel correspondences plus their epipolar
quality*, and stops there. Triangulation, 3D displacement and surface strain
live downstream (spec sections 6--7, :mod:`hl3.stereo.triangulate` and the 3D
pipeline); nothing here computes a world point.

What it does
------------
1. Seeds each POI with a predicted disparity. Stereo disparity across a
   converged rig is tens to hundreds of pixels, i.e. far outside the IC-GN
   basin of attraction, so an unseeded solve does not merely lose accuracy --
   it answers the wrong question. When a rig is available the seed is the
   disparity a point *on a nominal plane* would have
   (:func:`plane_disparity`), which is the cheap stand-in for the feature +
   disparity-surface stage A of spec section 5.1.
2. Refines every POI with the CPU reference correlator,
   :func:`hl3.correlate.icgn_first_order`. The subset solve is not
   reimplemented, wrapped or tuned here: one call, its numbers kept verbatim.
3. Scores each correspondence against the epipolar geometry *derived from the
   calibration* -- Sampson distance and symmetric point-to-line distance from
   :mod:`hl3.stereo.triangulate`, never a fundamental matrix fitted to the
   matches themselves (spec section 4.3). A match is graded by geometry it did
   not help choose, or the grade is worthless.
4. Reports a quality mask. Raw values and status codes are always kept; the
   mask is an additional array, so a caller can re-gate without re-matching.

Scope of this stage, stated as exclusions
-----------------------------------------
* **No lens distortion of any kind.** Pure L0 pinhole, exactly as in
  :mod:`hl3.stereo.triangulate`. Epipolar *lines* are therefore straight and
  the one-dimensional search of spec section 6.3 along distorted epipolar
  *curves* is not needed yet; it arrives with the distortion model.
* **No non-parametric distortion field and no stereo microscopy** (spec
  section 4.1 L6). That layer stays out of every branch until the written
  patent-clearance opinion required by spec section 10.4 exists. This bullet
  is a scope exclusion, not a description of anything in this file.
* **First-order (affine) shape function only.** Spec section 5.1 argues for
  the quadratic shape function as the stereo *default*, because two converged
  views of a tilted surface differ by a genuinely curved warp and an affine
  subset under-matches it (Schreier & Sutton 2002). The kernel already
  implements it (:func:`hl3.correlate.icgn_second_order`); wiring it in,
  including the automatic order reduction on flat regions, is deferred rather
  than done badly, and :class:`StereoMatchParams` rejects
  ``shape_order != 1`` instead of silently ignoring the field.
* **No adaptive or mask-aware subsets, no learned seeds, no rectification.**
  Spec section 6.2: HL3 works on the original pixel grid throughout.

Failure conventions follow the rest of the package. A broken call raises; a
point the correlator could not solve keeps its status code and is excluded by
the quality mask; a geometrically undefined metric is ``nan`` rather than a
flattering number. Everything is NumPy, single-threaded and free of RNG, so a
match is bit-for-bit reproducible from ``(images, params, points)``.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np

from ..correlate import ICGNParams, ICGNResult, Status, icgn_first_order, make_grid
from .calibrate import StereoRig
from .triangulate import (
    epipolar_distance,
    fundamental_from_projections,
    sampson_correct,
    sampson_distance,
)

__all__ = [
    "EpipolarResiduals",
    "MatchSeed",
    "StereoMatchParams",
    "StereoMatchResult",
    "epipolar_residuals",
    "match_stereo_pair",
    "plane_disparity",
    "rig_fundamental",
]

# Relative floor for "this ray is parallel to the plane". Same rationale as the
# _REL_EPS of the triangulation module: four decades above double-precision
# noise and many decades below any real viewing geometry.
_REL_EPS = 1e-12


# --------------------------------------------------------------------------- #
# Rig plumbing
# --------------------------------------------------------------------------- #


def _as_projection(P: np.ndarray, name: str) -> np.ndarray:
    A = np.asarray(P, dtype=float)
    if A.size != 12:
        raise ValueError(f"{name} must be a 3x4 projection matrix, got shape {A.shape}")
    A = A.reshape(3, 4)
    if not np.all(np.isfinite(A)):
        raise ValueError(f"{name} contains non-finite entries")
    return A


def _projection_pair(
    rig: StereoRig | Sequence[np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Left/right ``(3, 4)`` projection matrices from a rig or an explicit pair."""
    if isinstance(rig, StereoRig):
        return rig.left.P, rig.right.P
    try:
        left, right = rig
    except (TypeError, ValueError):
        raise TypeError(
            "rig must be a StereoRig or a pair of 3x4 projection matrices, got "
            f"{type(rig).__name__}"
        ) from None
    return _as_projection(left, "P_left"), _as_projection(right, "P_right")


def rig_fundamental(rig: StereoRig | Sequence[np.ndarray]) -> np.ndarray:
    """Fundamental matrix of the pair, with ``x_right.T @ F @ x_left == 0``.

    Thin adapter over :func:`hl3.stereo.triangulate.fundamental_from_projections`
    so that callers holding a :class:`~hl3.stereo.calibrate.StereoRig` never
    have to reach for ``.P`` themselves -- and, more to the point, never have to
    be tempted to estimate ``F`` from the correspondences being graded.
    """
    P_left, P_right = _projection_pair(rig)
    return fundamental_from_projections(P_left, P_right)


class EpipolarResiduals(NamedTuple):
    """Per-point epipolar quality of a correspondence set, both in pixels.

    ``sampson_px`` is the first-order distance to the closest pair of exactly
    corresponding points and is the default POI-level quality field of spec
    section 4.3; ``distance_px`` is the symmetric point-to-epipolar-line
    distance, kept because it is the quantity most people can picture.
    Unmatched points (non-finite pixel coordinates) come back as ``nan``.
    """

    sampson_px: np.ndarray
    distance_px: np.ndarray


def epipolar_residuals(
    rig: StereoRig | Sequence[np.ndarray],
    x_left: np.ndarray,
    x_right: np.ndarray,
) -> EpipolarResiduals:
    """Sampson and symmetric epipolar distance for ``(N, 2)`` correspondences."""
    F = rig_fundamental(rig)
    return EpipolarResiduals(
        sampson_px=sampson_distance(F, x_left, x_right),
        distance_px=epipolar_distance(F, x_left, x_right, symmetric=True),
    )


# --------------------------------------------------------------------------- #
# Nominal-plane disparity prediction
# --------------------------------------------------------------------------- #


def _as_plane(plane: Sequence[float]) -> np.ndarray:
    """Validate a plane ``(nx, ny, nz, w)`` with ``n . X + w == 0``."""
    a = np.asarray(plane, dtype=float).reshape(-1)
    if a.size != 4:
        raise ValueError(f"plane must be (nx, ny, nz, w), got {a.size} values")
    if not np.all(np.isfinite(a)):
        raise ValueError("plane must be finite")
    if np.linalg.norm(a[:3]) <= _REL_EPS:
        raise ValueError("plane normal must be a non-zero vector")
    return a


def _as_pixels(x: np.ndarray, name: str) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 2 or a.shape[1] != 2:
        raise ValueError(f"{name} must be an (N, 2) pixel array, got shape {a.shape}")
    return a


def plane_disparity(
    rig: StereoRig | Sequence[np.ndarray],
    points: np.ndarray,
    plane: Sequence[float] = (0.0, 0.0, 1.0, 0.0),
) -> np.ndarray:
    """Disparity ``x_right - x_left`` a point on ``plane`` would show, ``(N, 2)``.

    Each left-image pixel is back-projected onto the world plane
    ``n . X + w == 0`` and the resulting world point is projected into the right
    camera. For a surface that really lies on the plane this is the *exact*
    correspondence, not an approximation, which is what makes it a good IC-GN
    seed: the residual the solver has to remove is only the surface's departure
    from the plane.

    Points whose viewing ray is parallel to the plane, or which land behind
    either camera, have no prediction and come back as ``nan``. That is a
    prediction failure, not a match failure, and
    :func:`match_stereo_pair` degrades those points to a zero seed rather than
    refusing to run.
    """
    P_left, P_right = _projection_pair(rig)
    x = _as_pixels(points, "points")
    n_hat = _as_plane(plane)
    normal, offset = n_hat[:3], n_hat[3]

    M = P_left[:, :3]
    try:
        center = -np.linalg.solve(M, P_left[:, 3])
        rays = np.linalg.solve(M, np.hstack([x, np.ones((x.shape[0], 1))]).T).T
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "degenerate left projection matrix: the leading 3x3 block is "
            "singular, so viewing rays are undefined"
        ) from exc

    along = rays @ normal
    scale = np.maximum(np.linalg.norm(rays, axis=1), _REL_EPS) * np.linalg.norm(normal)
    with np.errstate(invalid="ignore"):
        parallel = ~(np.abs(along) > _REL_EPS * scale)
    lam = -(offset + center @ normal) / np.where(parallel, np.nan, along)
    X = center[None, :] + lam[:, None] * rays

    # Only points in front of both cameras have an image at all; a plane behind
    # the rig would otherwise produce a perfectly finite, perfectly wrong seed.
    with np.errstate(invalid="ignore"):
        depth_left = X @ P_left[2, :3] + P_left[2, 3]
        depth_right = X @ P_right[2, :3] + P_right[2, 3]
        ahead = (depth_left > 0.0) & (depth_right > 0.0)
        u = (X @ P_right[0, :3] + P_right[0, 3]) / depth_right
        v = (X @ P_right[1, :3] + P_right[1, 3]) / depth_right

    predicted = np.column_stack([u, v])
    predicted[~ahead] = np.nan
    return predicted - x


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #


class MatchSeed(enum.Enum):
    """Where each POI's initial disparity comes from (spec section 5.1 A/B)."""

    #: Nominal-plane prediction when a rig is available, otherwise ``SOLVER``.
    AUTO = "auto"
    #: Nominal-plane prediction; requires a rig.
    PLANE = "plane"
    #: Hand the decision to the kernel: FFT-CC when ``icgn.search_radius > 0``.
    SOLVER = "solver"
    #: Start from zero disparity. Only sane for a near-parallel, near-zero
    #: baseline pair, and useful as the control case in tests.
    ZERO = "zero"


@dataclass(frozen=True)
class StereoMatchParams:
    """Everything :func:`match_stereo_pair` needs beyond the images and the rig."""

    #: Passed through to the kernel untouched.
    icgn: ICGNParams = field(default_factory=ICGNParams)
    seed: MatchSeed = MatchSeed.AUTO
    #: World plane ``n . X + w == 0`` used by the ``PLANE`` seed, in mm. The
    #: default is ``z = 0``, the plane :func:`hl3.stereo.make_stereo_rig` aims
    #: both cameras at.
    seed_plane: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 0.0)
    #: Sampson-distance ceiling for the quality mask, in pixels. ``inf``
    #: disables the geometric gate and leaves convergence as the only test.
    max_sampson_px: float = 1.0
    #: Iterations of Sampson correction applied to the accepted matches; 0
    #: skips it and leaves :attr:`StereoMatchResult.left_corrected` unset.
    sampson_iters: int = 10
    #: POI-grid border; ``None`` uses :func:`hl3.correlate.make_grid`'s default.
    margin: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.icgn, ICGNParams):
            raise TypeError("icgn must be an ICGNParams instance")
        if self.icgn.shape_order != 1:
            raise ValueError(
                "stereo matching is first-order only at this stage; got "
                f"shape_order={self.icgn.shape_order}. The quadratic shape "
                "function exists in hl3.correlate.icgn_second_order but is not "
                "wired in here yet, and silently ignoring the field would "
                "misreport which warp produced the result"
            )
        if not isinstance(self.seed, MatchSeed):
            raise TypeError(f"seed must be a MatchSeed, got {type(self.seed).__name__}")
        _as_plane(self.seed_plane)
        if not self.max_sampson_px > 0.0:
            raise ValueError(
                f"max_sampson_px must be positive, got {self.max_sampson_px}"
            )
        if int(self.sampson_iters) < 0:
            raise ValueError(
                f"sampson_iters must be non-negative, got {self.sampson_iters}"
            )
        if self.margin is not None and int(self.margin) < 0:
            raise ValueError(f"margin must be non-negative, got {self.margin}")


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, eq=False)
class StereoMatchResult:
    """Correspondences for one image pair, with their epipolar quality.

    ``left_xy`` and ``right_xy`` hold *raw* values for every POI, including the
    ones that failed: the convention of the rest of the package is that arrays
    carry what the solver produced and :attr:`accepted` says which entries mean
    anything. :meth:`correspondences` is the NaN-masked view, which is also the
    form the triangulation module expects (a non-finite pixel there propagates
    to a ``nan`` world point instead of poisoning its neighbours).

    The epipolar fields are ``None`` when no rig was supplied -- there is no
    geometry to measure against, and filling them with zeros would read as a
    perfect score.
    """

    left_xy: np.ndarray  # (n, 2) reference-configuration POIs in the left image
    right_xy: np.ndarray  # (n, 2) matched pixels in the right image
    correlation: ICGNResult
    accepted: np.ndarray  # (n,) bool quality mask
    params: StereoMatchParams
    provenance: dict[str, Any]
    fundamental: np.ndarray | None = None
    sampson_px: np.ndarray | None = None
    epipolar_px: np.ndarray | None = None
    left_corrected: np.ndarray | None = None
    right_corrected: np.ndarray | None = None

    @property
    def disparity(self) -> np.ndarray:
        """``(n, 2)`` right-minus-left pixel offset."""
        return self.right_xy - self.left_xy

    @property
    def status(self) -> np.ndarray:
        return self.correlation.status

    @property
    def zncc(self) -> np.ndarray:
        return self.correlation.zncc

    @property
    def valid(self) -> np.ndarray:
        """Points the correlator converged on, before the geometric gate."""
        return self.correlation.status == int(Status.CONVERGED)

    @property
    def n_points(self) -> int:
        return int(self.left_xy.shape[0])

    @property
    def n_accepted(self) -> int:
        return int(np.count_nonzero(self.accepted))

    @property
    def accepted_fraction(self) -> float:
        if self.n_points == 0:
            return 0.0
        return self.n_accepted / self.n_points

    def correspondences(
        self, masked: bool = True, corrected: bool = False
    ) -> tuple[np.ndarray, np.ndarray]:
        """``(x_left, x_right)`` ready for :mod:`hl3.stereo.triangulate`.

        With ``masked`` the rejected points are set to ``nan`` in both views.
        With ``corrected`` the Sampson-corrected pair is returned instead: the
        two rays then intersect exactly, which is what makes a subsequent DLT
        the L2-optimal triangulation of the pair (spec section 6.1).
        """
        if corrected:
            if self.left_corrected is None or self.right_corrected is None:
                raise ValueError(
                    "no Sampson-corrected correspondences were computed; they "
                    "need a rig and params.sampson_iters > 0"
                )
            left, right = self.left_corrected, self.right_corrected
        else:
            left, right = self.left_xy, self.right_xy
        if not masked:
            return left.copy(), right.copy()
        left, right = left.copy(), right.copy()
        drop = ~self.accepted
        left[drop] = np.nan
        right[drop] = np.nan
        return left, right

    def status_counts(self) -> dict[Status, int]:
        return self.correlation.status_counts()

    def summary(self) -> dict[str, Any]:
        """Plain numbers for a report: coverage, correlation and geometry."""
        keep = self.accepted
        out: dict[str, Any] = {
            "n_points": self.n_points,
            "n_converged": int(np.count_nonzero(self.valid)),
            "n_accepted": self.n_accepted,
            "accepted_fraction": self.accepted_fraction,
            "zncc_median": _median(self.zncc[keep]),
            "disparity_px_median": _median(
                np.linalg.norm(self.disparity[keep], axis=1)
            ),
            "status_counts": {s.name: n for s, n in self.status_counts().items()},
        }
        if self.sampson_px is None:
            out["sampson_px_rms"] = float("nan")
            out["sampson_px_p95"] = float("nan")
            out["sampson_px_max"] = float("nan")
            return out
        s = self.sampson_px[keep]
        s = s[np.isfinite(s)]
        if s.size == 0:
            out["sampson_px_rms"] = float("nan")
            out["sampson_px_p95"] = float("nan")
            out["sampson_px_max"] = float("nan")
            return out
        out["sampson_px_rms"] = float(np.sqrt(np.mean(s**2)))
        out["sampson_px_p95"] = float(np.percentile(s, 95.0))
        out["sampson_px_max"] = float(np.max(s))
        return out


def _median(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if finite.size else float("nan")


# --------------------------------------------------------------------------- #
# The matcher
# --------------------------------------------------------------------------- #


def match_stereo_pair(
    left: np.ndarray,
    right: np.ndarray,
    rig: StereoRig | Sequence[np.ndarray] | None = None,
    params: StereoMatchParams | None = None,
    *,
    points: np.ndarray | None = None,
    initial_guess: np.ndarray | None = None,
) -> StereoMatchResult:
    """Match a synchronised stereo pair on the reference frame.

    Parameters
    ----------
    left, right:
        2-D greyscale images of identical shape, taken at the same instant by
        the two cameras of the rig.
    rig:
        :class:`~hl3.stereo.calibrate.StereoRig` or a pair of ``(3, 4)``
        projection matrices. Optional: without it the function still returns
        correspondences, but no epipolar quality and no plane seed, so the
        quality mask degrades to "the correlator converged".
    params:
        :class:`StereoMatchParams`; defaults are the kernel's plus a 1 px
        Sampson gate.
    points:
        ``(n, 2)`` POI centres in the *left* image. A regular grid from
        :func:`hl3.correlate.make_grid` is built when omitted.
    initial_guess:
        Passed straight to the kernel, overriding ``params.seed``. ``(n, 2)``
        disparities or ``(n, 6)`` warps.

    The POI grid is defined in the left image and the left image is the IC-GN
    *reference*: the correspondence is therefore one-directional by
    construction, and the right-to-left consistency check that would make it
    symmetric is a separate, later measurement (the four-way loop closure of
    spec section 6.4, which needs the temporal matches too).
    """
    params = params or StereoMatchParams()
    left_image = np.asarray(left, dtype=float)
    right_image = np.asarray(right, dtype=float)
    if left_image.ndim != 2:
        raise ValueError(f"left must be a 2-D greyscale image, got {left_image.ndim}-D")
    if left_image.shape != right_image.shape:
        raise ValueError(
            "left and right must have the same shape, got "
            f"{left_image.shape} and {right_image.shape}"
        )

    if points is None:
        poi = make_grid(left_image.shape, params.icgn, margin=params.margin)
    else:
        poi = _as_pixels(points, "points").copy()
        if not np.all(np.isfinite(poi)):
            raise ValueError("points must be finite")

    projections = None if rig is None else _projection_pair(rig)
    # Derived before the correlation, not after: a rig whose camera centres
    # coincide has no epipolar geometry at all, and that is a configuration
    # error. Discovering it only after every subset has been solved would
    # charge the user the whole run for a mistake visible up front.
    fundamental = None if projections is None else fundamental_from_projections(
        *projections
    )
    guess, seed_used, n_fallback = _resolve_seed(
        params, projections, poi, initial_guess
    )

    correlation = icgn_first_order(
        left_image, right_image, poi, params.icgn, guess
    )
    matched = np.column_stack(
        (
            poi[:, 0] + correlation.p[:, 0],
            poi[:, 1] + correlation.p[:, 3],
        )
    )
    converged = correlation.status == int(Status.CONVERGED)

    sampson_px = None
    epipolar_px = None
    left_corrected = None
    right_corrected = None
    accepted = converged.copy()

    if fundamental is not None:
        # Metrics are measured on the masked pair so that a point the solver
        # never solved cannot contribute a number at all: its stale pixel
        # coordinates would otherwise score like a real, and possibly good,
        # match.
        left_masked, right_masked = _mask_pair(poi, matched, converged)
        sampson_px = sampson_distance(fundamental, left_masked, right_masked)
        epipolar_px = epipolar_distance(
            fundamental, left_masked, right_masked, symmetric=True
        )
        with np.errstate(invalid="ignore"):
            accepted = converged & (sampson_px <= params.max_sampson_px)
        if params.sampson_iters > 0:
            left_corrected, right_corrected = sampson_correct(
                fundamental, left_masked, right_masked, iters=params.sampson_iters
            )

    provenance = _provenance(
        params, rig, projections, left_image, poi, seed_used, n_fallback
    )
    return StereoMatchResult(
        left_xy=poi,
        right_xy=matched,
        correlation=correlation,
        accepted=accepted,
        params=params,
        provenance=provenance,
        fundamental=fundamental,
        sampson_px=sampson_px,
        epipolar_px=epipolar_px,
        left_corrected=left_corrected,
        right_corrected=right_corrected,
    )


def _mask_pair(
    x_left: np.ndarray, x_right: np.ndarray, keep: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    left = x_left.copy()
    right = x_right.copy()
    left[~keep] = np.nan
    right[~keep] = np.nan
    return left, right


def _resolve_seed(
    params: StereoMatchParams,
    projections: tuple[np.ndarray, np.ndarray] | None,
    poi: np.ndarray,
    initial_guess: np.ndarray | None,
) -> tuple[np.ndarray | None, str, int]:
    """Return ``(guess, seed_name, n_fallback)`` for the kernel call.

    ``None`` means "let the kernel decide", which is how its FFT-CC integer
    search stays reachable. ``n_fallback`` counts POIs whose plane prediction
    was undefined and which therefore start from zero disparity: the kernel
    rejects a non-finite seed outright, and taking the whole field down because
    a few rays grazed the plane would be the wrong trade.
    """
    if initial_guess is not None:
        return np.asarray(initial_guess, dtype=float), "explicit", 0

    seed = params.seed
    if seed is MatchSeed.AUTO:
        seed = MatchSeed.PLANE if projections is not None else MatchSeed.SOLVER
    if seed is MatchSeed.SOLVER:
        return None, seed.value, 0
    if seed is MatchSeed.ZERO:
        return np.zeros((poi.shape[0], 2), dtype=float), seed.value, 0

    if projections is None:
        raise ValueError(
            "the PLANE seed needs a rig to back-project through; pass one, or "
            "use MatchSeed.SOLVER / MatchSeed.ZERO"
        )
    predicted = plane_disparity(projections, poi, params.seed_plane)
    undefined = ~np.all(np.isfinite(predicted), axis=1)
    predicted[undefined] = 0.0
    return predicted, seed.value, int(np.count_nonzero(undefined))


def _provenance(
    params: StereoMatchParams,
    rig: StereoRig | Sequence[np.ndarray] | None,
    projections: tuple[np.ndarray, np.ndarray] | None,
    image: np.ndarray,
    poi: np.ndarray,
    seed_used: str,
    n_fallback: int,
) -> dict[str, Any]:
    """The parameter snapshot a stereo result has to travel with."""
    icgn = params.icgn
    out: dict[str, Any] = {
        "stage": "s2_stereo_match",
        "solver": "hl3.correlate.icgn_first_order",
        "shape_function": "first_order_affine",
        "criterion": "znssd",
        "interpolation": "bicubic_bspline",
        "backend": "cpu-numpy",
        "deterministic": True,
        "rectified": False,
        "distortion_model": "none_pinhole_l0",
        "image_shape": tuple(int(n) for n in image.shape),
        "n_points": int(poi.shape[0]),
        "subset_size": icgn.subset_size,
        "step": icgn.step,
        "search_radius": icgn.search_radius,
        "zncc_min": icgn.zncc_min,
        "seed": seed_used,
        "seed_plane": tuple(float(v) for v in params.seed_plane),
        "seed_fallback_points": int(n_fallback),
        "max_sampson_px": float(params.max_sampson_px),
        "sampson_iters": int(params.sampson_iters),
        "has_rig": projections is not None,
        "epipolar_source": (
            "analytic_from_projections" if projections is not None else None
        ),
    }
    if isinstance(rig, StereoRig):
        out["baseline_mm"] = rig.baseline_mm
        out["standoff_mm"] = rig.standoff_mm
    return out
