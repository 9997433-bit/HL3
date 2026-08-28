# SPDX-License-Identifier: Apache-2.0
"""Sequence-level orchestration for HL3-2D: images in, displacement fields out.

This module is the thin layer between an image sequence and the CPU reference
correlator :func:`hl3.correlate.icgn_first_order`. It owns exactly the parts of
spec ``.agent_workspace/round1/R1-O1-hl3-2d-spec.md`` §1.0/§1.5/§2.9 that are
*about the sequence* rather than about a single subset:

* the point grid is built once and kept as the identity of a material point for
  the whole run, so a field is indexable as ``(frame, y, x)``;
* seeds are carried from frame to frame (§2.7 priority 1, ``PREV_FRAME``);
* the reference image can be updated mid-sequence (§2.9 ``FIXED`` /
  ``EVERY_N`` / ``INCREMENTAL``) and the per-segment warps are composed back
  onto the original reference, so the reported displacement always means
  "measured from frame ``reference_index``" no matter how many updates happened;
* strain is *not* computed here. When :mod:`hl3.strain` is importable the
  pipeline hands it the displacement field and stores whatever it returns;
  when it is not, the run still completes and says so in
  :attr:`Dic2DRun.strain`. That degradation is deliberate: the correlation
  result is the expensive part and must not be lost because a downstream
  module is missing.

Nothing in :mod:`hl3.correlate` is reimplemented or wrapped in a way that
changes its numbers -- every subset solve is one call into the reference
kernel, and the pipeline only ever composes, masks and reshapes its output.

The whole pipeline is single-threaded pure NumPy, so a run is bit-for-bit
reproducible from ``(images, config, points)`` alone (spec §5.16).
"""

from __future__ import annotations

import enum
import importlib
import inspect
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ..correlate import ICGNParams, ICGNResult, Status, icgn_first_order, make_grid

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
    "lattice_shape",
    "resolve_strain_backend",
    "run_sequence",
    "vsg_size_px",
]


class ReferenceMode(enum.Enum):
    """Which image plays the role of the reference at each frame (spec §2.9)."""

    FIXED = "fixed"
    EVERY_N = "every_n"
    INCREMENTAL = "incremental"


class SeedMode(enum.Enum):
    """Where the per-point initial guess comes from (spec §2.7)."""

    #: Always start from ``p = 0``; disables the solver's FFT-CC search.
    ZERO = "zero"
    #: Reuse the previous frame's converged warp, ``p = 0`` elsewhere.
    PREV_FRAME = "prev_frame"
    #: Hand the decision to the kernel: FFT-CC when ``search_radius > 0``.
    SOLVER = "solver"


class StrainMode(enum.Enum):
    """How hard the pipeline tries to produce strain."""

    #: Never call :mod:`hl3.strain`.
    OFF = "off"
    #: Use it when it is importable and usable; record why when it is not.
    AUTO = "auto"
    #: Fail the run when strain cannot be produced.
    REQUIRED = "required"


class StrainUnavailableError(RuntimeError):
    """Raised only under :attr:`StrainMode.REQUIRED`."""


def vsg_size_px(subset_size: int, step: int, window: int) -> int:
    """Virtual strain gauge size, iDICs GPG Eq. (7.2).

    ``L_VSG = (L_window - 1) * L_step + L_subset``, with ``L_window`` counted in
    *data points* and everything else in reference-frame pixels. It is reported
    for every run because it, not the subset size, is the spatial resolution a
    strain number actually carries (spec §1.7).
    """
    subset_size = int(subset_size)
    step = int(step)
    window = int(window)
    if subset_size < 1 or step < 1 or window < 1:
        raise ValueError("subset_size, step and window must all be >= 1")
    return (window - 1) * step + subset_size


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dic2DConfig:
    """Everything the pipeline needs beyond the images themselves.

    ``icgn`` is passed straight through to the kernel; the remaining fields are
    sequence-level and have no meaning for a single subset.
    """

    icgn: ICGNParams = field(default_factory=ICGNParams)
    reference_index: int = 0
    reference_mode: ReferenceMode = ReferenceMode.FIXED
    #: ``INCREMENTAL``: update the reference once the median ZNCC drops below.
    reference_zncc: float = 0.85
    #: ``EVERY_N``: number of frames a reference is kept for.
    reference_every_n: int = 10
    seed_mode: SeedMode = SeedMode.PREV_FRAME
    #: Border kept free of POIs; ``None`` uses :func:`hl3.correlate.make_grid`'s
    #: own default of ``subset_radius + search_radius + 2``.
    margin: int | None = None
    strain_mode: StrainMode = StrainMode.AUTO
    strain_window: int = 5
    #: Explicit strain entry point, bypassing the :mod:`hl3.strain` lookup.
    strain_backend: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.icgn, ICGNParams):
            raise TypeError("icgn must be an ICGNParams instance")
        if self.reference_index < 0:
            raise ValueError("reference_index must be >= 0")
        if self.reference_every_n < 1:
            raise ValueError("reference_every_n must be >= 1")
        if not -1.0 <= self.reference_zncc <= 1.0:
            raise ValueError("reference_zncc must lie in [-1, 1]")
        if self.strain_window < 3 or self.strain_window % 2 == 0:
            raise ValueError("strain_window must be an odd integer >= 3")
        if self.margin is not None and self.margin < 0:
            raise ValueError("margin must be >= 0")
        if self.strain_backend is not None and not callable(self.strain_backend):
            raise TypeError("strain_backend must be callable")
        if (
            self.reference_mode is not ReferenceMode.FIXED
            and self.reference_index != 0
        ):
            # Composing warps backwards through the sequence is a different
            # problem from composing them forwards, and the spec only defines
            # the forward one. Refuse rather than silently walk backwards.
            raise ValueError(
                "reference updates require reference_index == 0; frames before "
                "the reference cannot be reached by forward accumulation"
            )

    @property
    def subset_size(self) -> int:
        return self.icgn.subset_size

    @property
    def step(self) -> int:
        return self.icgn.step

    @property
    def l_vsg_px(self) -> int:
        """VSG size implied by ``(subset, step, strain_window)``."""
        return vsg_size_px(self.subset_size, self.step, self.strain_window)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class FrameOutcome:
    """One frame of a run, in both the segment and the accumulated frame.

    ``segment`` is exactly what the kernel returned for this frame against the
    reference in use at the time (its ``x``/``y`` are that reference's
    coordinates). ``p_total`` is the same motion expressed from the *original*
    reference, which is the only quantity a user should compare across frames.
    Under :attr:`ReferenceMode.FIXED` the two are identical, element for
    element.

    As in :class:`hl3.correlate.ICGNResult`, a row of ``p_total`` only means
    something where ``status`` is ``CONVERGED``; :meth:`Dic2DRun.field` masks
    the rest to NaN rather than leaving a stale number to be read as a result.
    """

    index: int
    frame_index: int
    reference_index: int
    segment: ICGNResult
    p_total: np.ndarray
    zncc: np.ndarray
    iterations: np.ndarray
    status: np.ndarray
    reference_updated: bool
    timestamp_s: float | None = None
    camera_id: str | None = None

    @property
    def valid(self) -> np.ndarray:
        return self.status == int(Status.CONVERGED)

    @property
    def u(self) -> np.ndarray:
        return self.p_total[:, 0]

    @property
    def v(self) -> np.ndarray:
        return self.p_total[:, 3]

    @property
    def n_points(self) -> int:
        return int(self.p_total.shape[0])

    @property
    def valid_fraction(self) -> float:
        if self.n_points == 0:
            return 0.0
        return float(np.count_nonzero(self.valid)) / self.n_points

    @property
    def zncc_median(self) -> float:
        """Median ZNCC over converged points; NaN when none converged."""
        selected = self.zncc[self.valid]
        if selected.size == 0:
            return math.nan
        return float(np.median(selected))

    def status_counts(self) -> dict[Status, int]:
        return {
            status: int(np.count_nonzero(self.status == int(status)))
            for status in Status
            if np.any(self.status == int(status))
        }


@dataclass(frozen=True, eq=False)
class StrainOutcome:
    """What became of the optional :mod:`hl3.strain` hand-off.

    ``reason`` is always populated -- on success it names the entry point that
    was called, on failure it says what was missing or what went wrong. A run
    is therefore self-describing without the caller having to guess whether
    strain was skipped on purpose.
    """

    available: bool
    reason: str
    backend: str | None = None
    frames: tuple[Mapping[str, np.ndarray], ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Field names common to every frame, sorted."""
        if not self.frames:
            return ()
        common: set[str] = set(self.frames[0])
        for frame in self.frames[1:]:
            common &= set(frame)
        return tuple(sorted(common))


@dataclass(frozen=True, eq=False)
class Dic2DRun:
    """Displacement (and optional strain) for a whole sequence."""

    points: np.ndarray
    grid_shape: tuple[int, int] | None
    frames: tuple[FrameOutcome, ...]
    config: Dic2DConfig
    strain: StrainOutcome
    provenance: dict[str, Any]

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def n_points(self) -> int:
        return int(self.points.shape[0])

    @property
    def reference_updates(self) -> tuple[int, ...]:
        return tuple(f.index for f in self.frames if f.reference_updated)

    def valid_mask(self) -> np.ndarray:
        """``(n_frames, ...)`` boolean array of converged points."""
        stacked = np.stack([f.valid for f in self.frames]) if self.frames else _empty(bool)
        return self._shape(stacked)

    def field(self, name: str, masked: bool = True) -> np.ndarray:
        """A ``(n_frames, ny, nx)`` field, or ``(n_frames, n_points)`` off-grid.

        Float fields are returned with non-converged points set to NaN unless
        ``masked`` is false; ``status`` and ``iterations`` are integer
        bookkeeping and are never masked, because NaN would destroy the very
        information they carry.
        """
        if name not in _FIELD_GETTERS:
            raise ValueError(
                f"unknown field {name!r}; expected one of "
                + ", ".join(sorted(_FIELD_GETTERS))
            )
        getter = _FIELD_GETTERS[name]
        if not self.frames:
            return self._shape(_empty(np.float64))
        stacked = np.stack([getter(f) for f in self.frames])
        if masked and name not in _INTEGER_FIELDS:
            stacked = stacked.astype(np.float64, copy=True)
            stacked[~np.stack([f.valid for f in self.frames])] = np.nan
        return self._shape(stacked)

    def strain_field(self, name: str) -> np.ndarray:
        """Stack one strain field over frames, gridded like :meth:`field`."""
        if not self.strain.available:
            raise StrainUnavailableError(self.strain.reason)
        if name not in self.strain.names:
            raise ValueError(
                f"unknown strain field {name!r}; backend returned "
                + (", ".join(self.strain.names) or "nothing")
            )
        stacked = np.stack(
            [np.asarray(frame[name], dtype=np.float64) for frame in self.strain.frames]
        )
        return self._shape(stacked)

    def _shape(self, stacked: np.ndarray) -> np.ndarray:
        """Reshape ``(n_frames, n_points)`` to ``(n_frames, ny, nx)`` on a grid."""
        if self.grid_shape is None or stacked.ndim != 2:
            return stacked
        if stacked.shape[1] != self.n_points:
            return stacked
        return stacked.reshape((stacked.shape[0],) + self.grid_shape)


def _empty(dtype: Any) -> np.ndarray:
    return np.zeros((0, 0), dtype=dtype)


_FIELD_GETTERS: dict[str, Callable[[FrameOutcome], np.ndarray]] = {
    "u": lambda f: f.p_total[:, 0],
    "u_x": lambda f: f.p_total[:, 1],
    "u_y": lambda f: f.p_total[:, 2],
    "v": lambda f: f.p_total[:, 3],
    "v_x": lambda f: f.p_total[:, 4],
    "v_y": lambda f: f.p_total[:, 5],
    "zncc": lambda f: f.zncc,
    "iterations": lambda f: f.iterations,
    "status": lambda f: f.status,
}

_INTEGER_FIELDS = frozenset({"status", "iterations"})


# --------------------------------------------------------------------------
# Warp accumulation across reference updates
# --------------------------------------------------------------------------


def compose_total(accumulated: np.ndarray, segment: np.ndarray) -> np.ndarray:
    """Compose a per-point segment warp onto the accumulated one (spec §2.9).

    With ``x_ref`` the point in the original reference, the accumulated warp
    puts it at ``x_ref + u_a`` and maps a subset offset by ``F_a``; the segment
    warp then acts from there, so

    ``u_total = u_a + u_s`` and ``F_total = F_s @ F_a``

    which is the chain rule the spec states for incremental references. Both
    arguments are ``(n, 6)`` in ``(u, u_x, u_y, v, v_x, v_y)`` order.
    """
    accumulated = np.asarray(accumulated, dtype=np.float64)
    segment = np.asarray(segment, dtype=np.float64)
    if accumulated.shape != segment.shape or accumulated.shape[-1:] != (6,):
        raise ValueError(
            "accumulated and segment must both be (n, 6), got "
            f"{accumulated.shape} and {segment.shape}"
        )

    if not accumulated.any():
        # Under a fixed reference this is every frame, and the identity has to
        # be exact: what the pipeline reports must be the kernel's own numbers,
        # not those numbers plus a round-off from multiplying by I.
        return segment.copy()

    f_a = _deformation_gradient(accumulated)
    f_s = _deformation_gradient(segment)
    f_t = f_s @ f_a

    total = np.empty_like(accumulated)
    total[:, 0] = accumulated[:, 0] + segment[:, 0]
    total[:, 3] = accumulated[:, 3] + segment[:, 3]
    total[:, 1] = f_t[:, 0, 0] - 1.0
    total[:, 2] = f_t[:, 0, 1]
    total[:, 4] = f_t[:, 1, 0]
    total[:, 5] = f_t[:, 1, 1] - 1.0
    return total


def _deformation_gradient(p: np.ndarray) -> np.ndarray:
    """``(n, 2, 2)`` array of ``F = I + grad u`` for ``(n, 6)`` warp params."""
    f = np.empty(p.shape[:-1] + (2, 2), dtype=np.float64)
    f[..., 0, 0] = 1.0 + p[..., 1]
    f[..., 0, 1] = p[..., 2]
    f[..., 1, 0] = p[..., 4]
    f[..., 1, 1] = 1.0 + p[..., 5]
    return f


# --------------------------------------------------------------------------
# Point grid
# --------------------------------------------------------------------------


def lattice_shape(points: np.ndarray) -> tuple[int, int] | None:
    """``(ny, nx)`` when ``points`` is a full row-major lattice, else ``None``.

    Field reshaping is only legitimate when the POI set really is a complete
    rectangular lattice listed row by row, which is what
    :func:`hl3.correlate.make_grid` produces. Anything else -- a masked AOI, a
    hand-picked point list -- stays a flat list of points rather than being
    folded into a grid that would silently misplace values.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or points.shape[0] == 0:
        return None
    xs = np.unique(points[:, 0])
    ys = np.unique(points[:, 1])
    if xs.size * ys.size != points.shape[0]:
        return None
    grid_x, grid_y = np.meshgrid(xs, ys)
    expected = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    if not np.array_equal(expected, points):
        return None
    return int(ys.size), int(xs.size)


# --------------------------------------------------------------------------
# Image sequence intake
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class _Input:
    image: np.ndarray
    index: int
    frame_index: int
    timestamp_s: float | None
    camera_id: str | None


def _collect_inputs(images: Any) -> list[_Input]:
    """Normalise a stack, a list of arrays or a capture source into frames.

    A capture source is recognised structurally (anything whose items carry an
    ``image`` attribute, as :class:`hl3.capture.Frame` does) so that the
    pipeline does not depend on the capture layer, and so any future hardware
    adapter works here without changes.
    """
    if isinstance(images, np.ndarray):
        if images.ndim == 3:
            items: list[Any] = [images[i] for i in range(images.shape[0])]
        else:
            items = [images]
    elif isinstance(images, Iterable):
        items = list(images)
    else:
        raise TypeError(
            "images must be a 3-D array, a sequence of 2-D arrays, or an "
            f"iterable of capture frames, got {type(images).__name__}"
        )

    collected: list[_Input] = []
    for position, item in enumerate(items):
        raw = getattr(item, "image", item)
        array = np.asarray(raw, dtype=np.float64)
        if array.ndim != 2:
            raise ValueError(
                f"frame {position} must be a 2-D greyscale image, got "
                f"{array.ndim}-D"
            )
        collected.append(
            _Input(
                image=array,
                index=position,
                frame_index=int(getattr(item, "frame_index", position)),
                timestamp_s=_optional_float(getattr(item, "timestamp_s", None)),
                camera_id=_optional_str(getattr(item, "camera_id", None)),
            )
        )

    if not collected:
        raise ValueError("images must contain at least one frame")
    shape = collected[0].image.shape
    for item in collected[1:]:
        if item.image.shape != shape:
            raise ValueError(
                "every frame must share the reference shape "
                f"{shape}, frame {item.index} has {item.image.shape}"
            )
    return collected


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def run_sequence(
    images: Any,
    config: Dic2DConfig | None = None,
    *,
    points: np.ndarray | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Dic2DRun:
    """Correlate a whole sequence against frame ``config.reference_index``.

    Parameters
    ----------
    images:
        A ``(n_frames, h, w)`` array, a sequence of 2-D arrays, or any iterable
        of capture frames (objects with an ``image`` attribute, optionally
        ``frame_index`` / ``timestamp_s`` / ``camera_id``).
    config:
        :class:`Dic2DConfig`; defaults are the spec's §7 table.
    points:
        ``(n, 2)`` array of ``(x, y)`` POI centres in the reference frame. A
        regular grid from :func:`hl3.correlate.make_grid` is built when omitted.
    progress:
        Called as ``progress(done, total)`` after each frame.

    Every frame is reported, including the reference frame itself: it is
    correlated like any other rather than shortcut to zero, so that a POI whose
    subset is out of bounds or textureless is diagnosed on frame 0 instead of
    on the first frame that happens to move.
    """
    config = config or Dic2DConfig()
    inputs = _collect_inputs(images)
    n_frames = len(inputs)
    if config.reference_index >= n_frames:
        raise ValueError(
            f"reference_index {config.reference_index} is outside the "
            f"{n_frames}-frame sequence"
        )

    params = config.icgn
    origin = inputs[config.reference_index]
    if points is None:
        grid = make_grid(origin.image.shape, params, margin=config.margin)
    else:
        grid = np.asarray(points, dtype=np.float64)
        if grid.ndim != 2 or grid.shape[1] != 2:
            raise ValueError(
                f"points must be an (n, 2) array of (x, y), got shape {grid.shape}"
            )
        if not np.all(np.isfinite(grid)):
            raise ValueError("points must be finite")
        grid = grid.copy()
    n_points = int(grid.shape[0])

    reference = origin
    points_ref = grid.copy()
    accumulated = np.zeros((n_points, 6), dtype=np.float64)
    tracked = np.ones(n_points, dtype=bool)
    previous_p: np.ndarray | None = None
    previous_valid: np.ndarray | None = None

    outcomes: list[FrameOutcome] = []
    for item in inputs:
        guess = _seed(config, n_points, previous_p, previous_valid)
        segment = _solve_tracked(
            reference.image, item.image, points_ref, tracked, params, guess
        )
        total = compose_total(accumulated, segment.p)
        status = segment.status.copy()
        status[~tracked] = int(Status.NO_INITIAL_GUESS)

        outcome = FrameOutcome(
            index=item.index,
            frame_index=item.frame_index,
            reference_index=reference.index,
            segment=segment,
            p_total=total,
            zncc=segment.zncc.copy(),
            iterations=segment.iterations.copy(),
            status=status,
            reference_updated=False,
            timestamp_s=item.timestamp_s,
            camera_id=item.camera_id,
        )

        if _should_update_reference(config, outcome, reference.index, item.index):
            # Only points solved against the outgoing reference can be
            # re-anchored: for the rest we no longer know where the material
            # point sits in the new reference, and inventing a position would
            # hand back a confident answer to a question never asked.
            tracked = tracked & outcome.valid
            accumulated = total.copy()
            points_ref = np.column_stack(
                (grid[:, 0] + accumulated[:, 0], grid[:, 1] + accumulated[:, 3])
            )
            reference = item
            previous_p = None
            previous_valid = None
            outcome = replace(outcome, reference_updated=True)
        else:
            previous_p = segment.p
            previous_valid = outcome.valid

        outcomes.append(outcome)
        if progress is not None:
            progress(len(outcomes), n_frames)

    grid_shape = lattice_shape(grid)
    strain = _run_strain(config, grid, outcomes)
    provenance = _provenance(config, inputs, grid, grid_shape, outcomes, strain)
    return Dic2DRun(
        points=grid,
        grid_shape=grid_shape,
        frames=tuple(outcomes),
        config=config,
        strain=strain,
        provenance=provenance,
    )


def correlate_pair(
    reference: np.ndarray,
    target: np.ndarray,
    config: Dic2DConfig | None = None,
    *,
    points: np.ndarray | None = None,
) -> Dic2DRun:
    """Two-image convenience wrapper; frame 0 is the reference, frame 1 the target."""
    return run_sequence([reference, target], config, points=points)


def _seed(
    config: Dic2DConfig,
    n_points: int,
    previous_p: np.ndarray | None,
    previous_valid: np.ndarray | None,
) -> np.ndarray | None:
    """Initial guess for the next frame, in the current segment's coordinates.

    ``None`` means "let the kernel decide", which is how the FFT-CC integer
    search in :func:`hl3.correlate.icgn_first_order` stays reachable.
    """
    if config.seed_mode is SeedMode.SOLVER:
        return None
    if config.seed_mode is SeedMode.ZERO:
        return np.zeros((n_points, 6), dtype=np.float64)
    if previous_p is None or previous_valid is None:
        return None
    # A point that did not converge last frame carries a meaningless warp; seed
    # it from zero instead of propagating the failure into the next frame.
    seeds = previous_p.copy()
    seeds[~previous_valid] = 0.0
    return seeds


def _solve_tracked(
    reference: np.ndarray,
    target: np.ndarray,
    points_ref: np.ndarray,
    tracked: np.ndarray,
    params: ICGNParams,
    guess: np.ndarray | None,
) -> ICGNResult:
    """One kernel call for the tracked points, scattered back to full length.

    Points that lost their track are never handed to the solver -- their
    reference position is stale -- and come back as ``NO_INITIAL_GUESS``.
    """
    n_points = int(points_ref.shape[0])
    selected = np.flatnonzero(tracked)

    sub_guess = None if guess is None else guess[selected]
    solved = icgn_first_order(
        reference, target, points_ref[selected], params, sub_guess
    )
    if selected.size == n_points:
        return solved

    p = np.zeros((n_points, 6), dtype=np.float64)
    zncc = np.full(n_points, -1.0, dtype=np.float64)
    iterations = np.zeros(n_points, dtype=np.int32)
    status = np.full(n_points, int(Status.NO_INITIAL_GUESS), dtype=np.int32)
    covariance = None
    if solved.covariance is not None:
        covariance = np.full((n_points, 6, 6), np.nan, dtype=np.float64)
        covariance[selected] = solved.covariance
    p[selected] = solved.p
    zncc[selected] = solved.zncc
    iterations[selected] = solved.iterations
    status[selected] = solved.status
    return ICGNResult(
        x=points_ref[:, 0].copy(),
        y=points_ref[:, 1].copy(),
        p=p,
        zncc=zncc,
        iterations=iterations,
        status=status,
        covariance=covariance,
    )


def _should_update_reference(
    config: Dic2DConfig,
    outcome: FrameOutcome,
    reference_index: int,
    index: int,
) -> bool:
    """Decide, after solving frame ``index``, whether it becomes the reference.

    The decision is taken *after* the frame is solved because the accumulated
    warp at the switch is exactly that frame's solution; and a frame on which
    nothing converged is never promoted, since it would take every track with
    it.
    """
    if config.reference_mode is ReferenceMode.FIXED:
        return False
    if outcome.valid_fraction <= 0.0:
        return False
    if config.reference_mode is ReferenceMode.EVERY_N:
        return index - reference_index >= config.reference_every_n
    median = outcome.zncc_median
    return math.isnan(median) or median < config.reference_zncc


def _provenance(
    config: Dic2DConfig,
    inputs: Sequence[_Input],
    grid: np.ndarray,
    grid_shape: tuple[int, int] | None,
    outcomes: Sequence[FrameOutcome],
    strain: StrainOutcome,
) -> dict[str, Any]:
    """The parameter/quality snapshot required by spec §1.11 for reporting."""
    params = config.icgn
    valid = [o.valid_fraction for o in outcomes]
    return {
        "solver": "hl3.correlate.icgn_first_order",
        "shape_function": "first_order_affine",
        "criterion": "znssd",
        "interpolation": "bicubic_bspline",
        "deterministic": True,
        "backend": "cpu-numpy",
        "image_shape": tuple(int(n) for n in inputs[0].image.shape),
        "n_frames": len(outcomes),
        "n_points": int(grid.shape[0]),
        "grid_shape": grid_shape,
        "subset_size": params.subset_size,
        "subset_radius": params.subset_radius,
        "step": params.step,
        "search_radius": params.search_radius,
        "zncc_min": params.zncc_min,
        "seed_mode": config.seed_mode.value,
        "reference_mode": config.reference_mode.value,
        "reference_index": config.reference_index,
        "reference_updates": tuple(
            o.index for o in outcomes if o.reference_updated
        ),
        "strain_window": config.strain_window,
        "l_vsg_px": config.l_vsg_px,
        "valid_fraction_min": min(valid) if valid else 0.0,
        "valid_fraction_mean": float(np.mean(valid)) if valid else 0.0,
        "strain": {
            "mode": config.strain_mode.value,
            "available": strain.available,
            "backend": strain.backend,
            "reason": strain.reason,
        },
    }


# --------------------------------------------------------------------------
# Optional strain hand-off
# --------------------------------------------------------------------------

#: Entry points looked up in :mod:`hl3.strain`, in order of preference. The
#: list is deliberately generous: this pipeline was written before the strain
#: module landed, and a missing or differently named entry point must downgrade
#: the run rather than break it.
STRAIN_ENTRY_POINTS: tuple[str, ...] = (
    "pipeline_strain",
    "strain_fields",
    "strain_field",
    "compute_strain",
    "strain_from_displacement",
    "local_plane_fit",
    "pointwise_least_squares",
    "pls_gradients",
)


def resolve_strain_backend(
    override: Callable[..., Any] | None = None,
) -> tuple[Callable[..., Any] | None, str, str]:
    """Find a strain entry point. Returns ``(callable, name, reason)``.

    ``callable`` is ``None`` when strain cannot be produced, and ``reason``
    then says why in a sentence a user can act on.
    """
    if override is not None:
        name = getattr(override, "__name__", repr(override))
        return override, name, f"using the caller-supplied backend {name!r}"

    try:
        module = importlib.import_module("hl3.strain")
    except Exception as error:  # noqa: BLE001
        # Not just ImportError: a module discovered at run time can also be
        # half-written or raise on import, and neither is a reason to lose a
        # correlation result that has already been computed.
        detail = f"{type(error).__name__}: {error}"
        return None, None, f"hl3.strain is not importable ({detail}); displacement only"

    for attribute in STRAIN_ENTRY_POINTS:
        candidate = getattr(module, attribute, None)
        if callable(candidate):
            return candidate, f"hl3.strain.{attribute}", f"hl3.strain.{attribute}"
    return (
        None,
        None,
        "hl3.strain exposes none of the expected entry points ("
        + ", ".join(STRAIN_ENTRY_POINTS)
        + "); displacement only",
    )


def _run_strain(
    config: Dic2DConfig,
    grid: np.ndarray,
    outcomes: Sequence[FrameOutcome],
) -> StrainOutcome:
    if config.strain_mode is StrainMode.OFF:
        return StrainOutcome(False, "strain_mode is OFF")

    backend, name, reason = resolve_strain_backend(config.strain_backend)
    if backend is None:
        if config.strain_mode is StrainMode.REQUIRED:
            raise StrainUnavailableError(reason)
        return StrainOutcome(False, reason)

    grid_shape = lattice_shape(grid)
    frames: list[Mapping[str, np.ndarray]] = []
    try:
        for outcome in outcomes:
            frames.append(_strain_one(backend, config, grid, grid_shape, outcome))
    except Exception as error:
        # A downstream module that is present but does not fit the contract is
        # the same kind of event as one that is absent: the correlation result
        # is already computed and must survive it. REQUIRED opts out of that.
        detail = f"{name} failed: {type(error).__name__}: {error}"
        if config.strain_mode is StrainMode.REQUIRED:
            raise StrainUnavailableError(detail) from error
        return StrainOutcome(False, detail, backend=name)

    return StrainOutcome(True, reason, backend=name, frames=tuple(frames))


def _strain_one(
    backend: Callable[..., Any],
    config: Dic2DConfig,
    grid: np.ndarray,
    grid_shape: tuple[int, int] | None,
    outcome: FrameOutcome,
) -> Mapping[str, np.ndarray]:
    """Call the backend with the first payload shape it accepts.

    Two payloads are tried. When the POIs form a lattice the ``(ny, nx)``
    gridded one goes first, because a pointwise-least-squares fit over a
    ``L_window x L_window`` neighbourhood is naturally written against a grid;
    the flat point-list payload follows, and is the only one available for a
    scattered POI set. Keyword arguments the backend does not declare are
    dropped, so a narrower signature than this pipeline's payload is not an
    error.
    """
    valid = outcome.valid
    payload: dict[str, Any] = {
        "x": grid[:, 0],
        "y": grid[:, 1],
        "u": outcome.p_total[:, 0],
        "v": outcome.p_total[:, 3],
        "u_x": outcome.p_total[:, 1],
        "u_y": outcome.p_total[:, 2],
        "v_x": outcome.p_total[:, 4],
        "v_y": outcome.p_total[:, 5],
        "valid": valid,
        "zncc": outcome.zncc,
        "window": config.strain_window,
        "step": config.step,
        "step_px": float(config.step),
        "subset_size": config.subset_size,
        "subset_px": config.subset_size,
        "grid_shape": grid_shape,
    }

    candidates = [payload]
    if grid_shape is not None:
        gridded = {
            key: (
                value.reshape(grid_shape)
                if isinstance(value, np.ndarray) and value.shape == (grid.shape[0],)
                else value
            )
            for key, value in payload.items()
        }
        candidates.insert(0, gridded)

    errors: list[str] = []
    for candidate in candidates:
        try:
            return _normalise_strain_output(backend(**_accepted(backend, candidate)))
        except (TypeError, ValueError) as error:
            errors.append(f"{type(error).__name__}: {error}")
    raise TypeError("; ".join(errors))


def _accepted(backend: Callable[..., Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop payload keys the backend does not declare.

    A backend whose signature cannot be inspected (a C extension, say) is given
    the full payload and allowed to complain itself.
    """
    try:
        signature = inspect.signature(backend)
    except (TypeError, ValueError):
        return dict(payload)

    parameters = signature.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
        return dict(payload)
    names = {
        p.name
        for p in parameters
        if p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in payload.items() if key in names}


def _normalise_strain_output(result: Any) -> Mapping[str, np.ndarray]:
    """Accept a mapping, a dataclass-like object or an object with arrays."""
    if isinstance(result, Mapping):
        items = result.items()
    elif hasattr(result, "_asdict"):
        items = result._asdict().items()
    elif hasattr(result, "__dict__") and vars(result):
        items = vars(result).items()
    else:
        raise TypeError(
            "strain backend must return a mapping of field name to array, got "
            f"{type(result).__name__}"
        )

    fields = {
        str(key): np.asarray(value, dtype=np.float64)
        for key, value in items
        if isinstance(value, np.ndarray)
    }
    if not fields:
        raise ValueError("strain backend returned no array-valued fields")
    return fields
