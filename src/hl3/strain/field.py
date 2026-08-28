# SPDX-License-Identifier: Apache-2.0
"""End-to-end strain field: parameters in, tensors and VSG metadata out.

Ties :mod:`hl3.strain.pls`, :mod:`hl3.strain.tensors` and :mod:`hl3.strain.vsg`
into the two dataclasses that IR1-F3 froze as the public calling surface --
:class:`StrainParams` and :class:`StrainField`, re-exported from
``hl3.pipeline`` -- plus the function that produces one from the other,
:func:`compute_strain`.

Three requirements are made structural here rather than advisory:

* the tensor family is *named* in the result, not implied, because a strain
  field without its tensor name is not interpretable (spec section 2.11), and
  the name is checked against ``hl3.io.hdf5_schema.STRAIN_TENSORS`` so that a
  field can always be written to the container;
* the VSG size travels with the field and cannot be skipped: ``subset_px`` is a
  required argument of :func:`compute_strain` because ``@vsg_px`` is a mandatory
  attribute of ``strain/<strain_id>`` (``docs/schema-hdf5.md`` section 9.3,
  IR1-F4 section 10 item 2);
* strain arrays are NaN-carrying, and the three components share one NaN
  pattern, so ``valid == isfinite(exx)`` is exact rather than approximately
  true.

Recomputing strain from stored displacements is deliberately cheap -- no
correlation is repeated -- which is what turns the VSG study of spec section 1.3
step 5 from an overnight job into a parameter sweep.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field

import numpy as np

from hl3.io.hdf5_schema import STRAIN_METHODS, STRAIN_TENSORS

from . import vsg as _vsg
from .pls import (
    DEFAULT_FIT_ORDER,
    DEFAULT_MIN_VALID_FRACTION,
    DEFAULT_WEIGHTING,
    DEFAULT_WINDOW_PTS,
    GradientField,
    neighbor_min_for,
    pls_gradients,
)
from .tensors import (
    deformation_gradient,
    dilatation,
    principal_strains,
    rotation_angle,
    strain_tensor,
    tresca_strain,
    von_mises_strain,
)

__all__ = [
    "StrainField",
    "StrainParams",
    "compute_strain",
    "grid_from_points",
]

# Fit order -> the @method vocabulary of schema section 9.3. A uniformly
# weighted local polynomial fit *is* a Savitzky-Golay filter; with Gaussian
# weights it is the weighted generalisation of one, and the weighting is
# recorded separately so the two remain distinguishable.
_METHOD_BY_ORDER = {"linear": "local_plane_fit", "quadratic": "savitzky_golay"}

# Gate G-S1-STR-1 requires these names to be exactly the schema's, and a stored
# field whose @method is not in the vocabulary cannot be read back at all, so
# the check runs at import rather than at write time.
_UNKNOWN_METHODS = set(_METHOD_BY_ORDER.values()) - set(STRAIN_METHODS)
if _UNKNOWN_METHODS:
    raise RuntimeError(
        f"strain methods {sorted(_UNKNOWN_METHODS)} are not in "
        f"hl3.io.hdf5_schema.STRAIN_METHODS"
    )


@dataclass(frozen=True)
class StrainParams:
    """Everything that turns a displacement grid into a strain field.

    The first four fields are the frozen signature of IR1-F3 section 4; the rest
    are keyword slots appended under its rule 11.2, each defaulting to the frozen
    behaviour. Step and subset size are deliberately *not* here: they belong to
    the correlator (``Pipeline2DParams.icgn``) and are passed to
    :func:`compute_strain` directly, so that one analysis cannot carry two
    disagreeing copies of them.

    Parameters
    ----------
    window_pts
        Strain fit window in POI, odd and >= 3. The parameter that trades strain
        noise against spatial resolution; see :mod:`hl3.strain.vsg`.
    tensor
        A member of ``hl3.io.hdf5_schema.STRAIN_TENSORS``. Defaults to
        ``green_lagrange`` per spec section 1.6; ``logarithmic`` is accepted as
        the schema's alias for ``hencky`` (the two enumerate the same tensor --
        IR1-F4 gap G-4) and is echoed back unchanged so the stored ``@tensor``
        attribute stays faithful to what the caller asked for.
    weighting
        ``"uniform"`` (default) or ``"gaussian"``. Spec section 1.6 makes
        Gaussian the product default; IR1-F3 registered ``uniform`` as the S1
        default and froze the flip as a numerical-behaviour change that must
        pass a gate. Both are implemented here, and the default stays
        ``uniform``.
    min_valid_fraction
        ``neighbor_min = ceil(f * window_pts**2)``: below that many valid POI in
        a window the point is NaN.
    fit_order
        ``"linear"`` (plane fit, method ``local_plane_fit``) or ``"quadratic"``
        (method ``savitzky_golay``). See :func:`hl3.strain.pls.pls_gradients`
        for why the difference only shows at window boundaries.
    sigma
        Gaussian weight width in POI; defaults to ``window_pts / 4``.
    require_center
        When true (default) a POI whose own displacement is invalid gets NaN
        strain even if its neighbourhood is well populated.
    """

    window_pts: int = DEFAULT_WINDOW_PTS
    tensor: str = "green_lagrange"
    weighting: str = DEFAULT_WEIGHTING
    min_valid_fraction: float = DEFAULT_MIN_VALID_FRACTION
    fit_order: str = DEFAULT_FIT_ORDER
    sigma: float | None = None
    require_center: bool = True

    def __post_init__(self) -> None:
        # Validate by delegating to the routines the values are for, so each
        # vocabulary and each formula still lives in exactly one place.
        _vsg.effective_window_pts(self.window_pts)
        neighbor_min_for(self.window_pts, self.min_valid_fraction)
        if self.window_pts < 3:
            raise ValueError(
                f"window_pts must be >= 3 POI for a local fit, got {self.window_pts}"
            )
        if self.tensor not in STRAIN_TENSORS:
            raise ValueError(
                f"tensor must be one of {sorted(STRAIN_TENSORS)}, got {self.tensor!r}"
            )
        if self.fit_order not in _METHOD_BY_ORDER:
            raise ValueError(
                f"fit_order must be one of {tuple(_METHOD_BY_ORDER)}, "
                f"got {self.fit_order!r}"
            )
        if self.weighting not in ("uniform", "gaussian"):
            raise ValueError(
                f"weighting must be one of ('uniform', 'gaussian'), "
                f"got {self.weighting!r}"
            )
        if self.sigma is not None and (
            not math.isfinite(self.sigma) or self.sigma <= 0.0
        ):
            raise ValueError(f"sigma must be finite and > 0, got {self.sigma!r}")

    @property
    def method(self) -> str:
        """The ``@method`` this parameter set produces, from ``STRAIN_METHODS``."""
        return _METHOD_BY_ORDER[self.fit_order]

    @property
    def neighbor_min(self) -> int:
        """Minimum valid POI in a window, ``ceil(min_valid_fraction * L^2)``."""
        return neighbor_min_for(self.window_pts, self.min_valid_fraction)

    def vsg_px(self, step_px: float, subset_px: int) -> float:
        """VSG size for this window with the correlator's step and subset."""
        return _vsg.vsg_size_px(self.window_pts, step_px, subset_px)

    def with_window(self, window_pts: int) -> StrainParams:
        """Copy with a different strain window -- one step of a VSG study."""
        return replace(self, window_pts=int(window_pts))


@dataclass(frozen=True)
class StrainField:
    """Strain on a POI grid, with the metadata needed to interpret it.

    The first eight fields are the frozen layout of IR1-F3 section 6. Arrays are
    flat and indexed by POI in the correlator's point order (row major,
    ``index = iy * nx + ix``), which is what makes ``ICGNResult`` fields and
    strain fields index-compatible; :meth:`as_grid` gives the ``(ny, nx)`` view
    for plotting. Unlike displacements, strain arrays *carry* their NaNs: an
    invalid point is NaN in all three components.

    Derived quantities are properties rather than stored arrays, so there is one
    source of truth and no derived field can go stale against the tensor it came
    from.
    """

    exx: np.ndarray  # (P,) tensor named by `tensor`
    eyy: np.ndarray  # (P,)
    exy: np.ndarray  # (P,) tensor shear; gamma_xy = 2 * exy
    tensor: str
    method: str
    window_pts: int
    vsg_px: float
    grid_shape: tuple[int, int]
    # Appended beyond the frozen eight: provenance and the PLS detail that the
    # pipeline layer does not need but a VSG or noise study does.
    weighting: str = "uniform"
    vsg_mm: float | None = None
    gradients: GradientField | None = dataclass_field(default=None, repr=False)

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.exx)

    @property
    def n_points(self) -> int:
        return int(self.exx.size)

    @property
    def E(self) -> np.ndarray:
        """The strain tensor itself, shape ``(P, 2, 2)``."""
        return np.stack(
            [
                np.stack([self.exx, self.exy], axis=-1),
                np.stack([self.exy, self.eyy], axis=-1),
            ],
            axis=-2,
        )

    @property
    def F(self) -> np.ndarray:
        """Deformation gradient, shape ``(P, 2, 2)``; needs the PLS detail."""
        g = self._require_gradients("F")
        return deformation_gradient(
            g.u_x.ravel(), g.u_y.ravel(), g.v_x.ravel(), g.v_y.ravel()
        )

    @property
    def gamma_xy(self) -> np.ndarray:
        """Engineering shear ``2 * exy``, the other half of the factor-2 trap."""
        return 2.0 * self.exy

    @property
    def e1(self) -> np.ndarray:
        return principal_strains(self.E).e1

    @property
    def e2(self) -> np.ndarray:
        return principal_strains(self.E).e2

    @property
    def theta_p(self) -> np.ndarray:
        """Principal direction in radians; convert at the writer, per IR1-F4."""
        return principal_strains(self.E).theta_p

    @property
    def gamma_max(self) -> np.ndarray:
        """In-plane maximum shear ``e1 - e2``."""
        return principal_strains(self.E).gamma_max

    @property
    def von_mises(self) -> np.ndarray:
        """See :func:`hl3.strain.von_mises_strain` for the formula and its two
        assumptions (plane stress, incompressible)."""
        return von_mises_strain(self.E)

    @property
    def tresca(self) -> np.ndarray:
        return tresca_strain(self.E)

    @property
    def dilatation(self) -> np.ndarray:
        """Relative area change ``det(F) - 1``; needs the PLS detail."""
        return dilatation(self.F)

    @property
    def rotation(self) -> np.ndarray:
        """In-plane rigid rotation in radians; needs the PLS detail."""
        return rotation_angle(self.F)

    @property
    def n_neighbors(self) -> np.ndarray:
        """Valid POI that entered each fit window, ``(P,)``."""
        return self._require_gradients("n_neighbors").n_neighbors.ravel()

    def _require_gradients(self, name: str) -> GradientField:
        if self.gradients is None:
            raise ValueError(
                f"{name} needs the PLS detail, which this StrainField was "
                "constructed without"
            )
        return self.gradients

    def as_grid(self, name: str) -> np.ndarray:
        """A ``(ny, nx)`` view of one field, for plotting and line probes."""
        values = getattr(self, name)
        array = np.asarray(values)
        if array.shape[:1] != (self.n_points,):
            raise ValueError(
                f"{name} is not a per-POI array of length {self.n_points}"
            )
        return array.reshape(self.grid_shape + array.shape[1:])

    def as_schema_dict(self) -> dict[str, np.ndarray]:
        """Datasets of ``strain/<strain_id>``, keyed by their schema names."""
        return {
            "exx": self.exx,
            "eyy": self.eyy,
            "exy": self.exy,
            "e1": self.e1,
            "e2": self.e2,
            "theta_p": self.theta_p,
            "gamma_max": self.gamma_max,
            "von_mises": self.von_mises,
        }

    def schema_attrs(self) -> dict[str, object]:
        """The four mandatory attributes of ``strain/<strain_id>``, plus
        ``vsg_mm`` when the analysis is calibrated (and never otherwise, per
        IR1-F4 section 10 item 3)."""
        attrs: dict[str, object] = {
            "tensor": self.tensor,
            "method": self.method,
            "window_pts": int(self.window_pts),
            "vsg_px": float(self.vsg_px),
        }
        if self.vsg_mm is not None:
            attrs["vsg_mm"] = float(self.vsg_mm)
        return attrs


def compute_strain(
    u: np.ndarray,
    v: np.ndarray,
    params: StrainParams | None = None,
    *,
    step_px: float,
    subset_px: int,
    valid: np.ndarray | None = None,
    image_scale_px_per_mm: float | None = None,
) -> StrainField:
    """Compute a strain field from a displacement grid by PLS (spec section 2.11).

    Parameters
    ----------
    u, v
        Displacement components on the POI grid, shape ``(ny, nx)``, ``x`` along
        axis 1. NaN marks a POI the correlator did not solve.
    params
        :class:`StrainParams`; the spec defaults when omitted.
    step_px
        POI grid pitch in pixels. Required, and required to be the same length
        unit as ``u`` and ``v``: a displacement grid in pixels with a step in
        millimetres silently produces strain wrong by the image scale.
    subset_px
        Full correlation subset side length in pixels, for the VSG size.
        Required because ``@vsg_px`` is mandatory and a guessed spatial
        resolution is worse than none.
    valid
        Boolean grid of POI usable as fit neighbours. The frozen criterion
        (IR1-F3 section 4) is ``status == Status.CONVERGED``: a ``LOW_ZNCC``
        point is kept in the displacement field but must not pull on a strain
        fit, so the caller passes that mask here rather than re-thresholding
        ZNCC in this layer.
    image_scale_px_per_mm
        Supplied only for a calibrated analysis; controls whether ``vsg_mm``
        exists at all.
    """
    if params is None:
        params = StrainParams()

    gradients = pls_gradients(
        u,
        v,
        step_px=step_px,
        window_pts=params.window_pts,
        fit_order=params.fit_order,
        weighting=params.weighting,
        sigma=params.sigma,
        valid=valid,
        neighbor_min=params.neighbor_min,
        require_center=params.require_center,
    )
    F = deformation_gradient(
        gradients.u_x, gradients.u_y, gradients.v_x, gradients.v_y
    )
    E = strain_tensor(F, params.tensor)
    vsg_px = params.vsg_px(step_px, subset_px)
    vsg_mm = (
        None
        if image_scale_px_per_mm is None
        else _vsg.vsg_size_mm(vsg_px, image_scale_px_per_mm)
    )
    return StrainField(
        exx=E[..., 0, 0].ravel(),
        eyy=E[..., 1, 1].ravel(),
        exy=(0.5 * (E[..., 0, 1] + E[..., 1, 0])).ravel(),
        tensor=params.tensor,
        method=params.method,
        window_pts=params.window_pts,
        vsg_px=vsg_px,
        grid_shape=gradients.shape,
        weighting=params.weighting,
        vsg_mm=vsg_mm,
        gradients=gradients,
    )


def grid_from_points(
    x: np.ndarray,
    y: np.ndarray,
    values: Sequence[np.ndarray],
    tol: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Scatter per-POI arrays onto the ``(ny, nx)`` grid the PLS fitter expects.

    The correlator returns flat per-point arrays (see
    :class:`hl3.correlate.ICGNResult`), which is the right layout for solving
    and the wrong one for differentiating. This is the adapter, and it is a
    function rather than a reshape at the call site because the reshape is only
    valid if the points really do form a complete regular grid -- a masked AOI
    does not, and silently reshaping one would shear the field.

    Points are snapped to the sorted unique ``x`` and ``y`` values within
    ``tol``; positions with no point are filled with NaN. Returns the grid axes
    and one grid per input array.

    Raises when the coordinates do not form a regular lattice, when two points
    share a cell, or when a value array does not match the coordinate length.
    """
    xs_raw = np.asarray(x, dtype=float).reshape(-1)
    ys_raw = np.asarray(y, dtype=float).reshape(-1)
    if xs_raw.size != ys_raw.size:
        raise ValueError(
            f"x and y must have the same length, got {xs_raw.size} and {ys_raw.size}"
        )
    if xs_raw.size == 0:
        raise ValueError("x and y must contain at least one point")
    if not (np.all(np.isfinite(xs_raw)) and np.all(np.isfinite(ys_raw))):
        raise ValueError("POI coordinates must all be finite")
    if not math.isfinite(tol) or tol <= 0.0:
        raise ValueError(f"tol must be finite and > 0, got {tol!r}")

    axes = []
    indices = []
    for coord, name in ((xs_raw, "x"), (ys_raw, "y")):
        axis = np.unique(np.round(coord / tol) * tol)
        if axis.size > 1:
            spacing = np.diff(axis)
            if np.ptp(spacing) > tol * max(1.0, float(np.max(np.abs(axis)))):
                raise ValueError(
                    f"{name} coordinates are not on a regular grid: spacings "
                    f"range over {float(np.ptp(spacing))}"
                )
        idx = np.clip(np.searchsorted(axis, coord), 0, axis.size - 1)
        # searchsorted lands one past the match when rounding pushed the point
        # below its own axis entry; check both candidates before giving up.
        lower = np.clip(idx - 1, 0, axis.size - 1)
        take_lower = np.abs(axis[lower] - coord) < np.abs(axis[idx] - coord)
        idx = np.where(take_lower, lower, idx)
        axes.append(axis)
        indices.append(idx)

    xs, ys = axes
    flat = indices[1] * xs.size + indices[0]
    if np.unique(flat).size != flat.size:
        raise ValueError(
            "two POI fall in the same grid cell; coordinates must be unique"
        )

    grids = []
    for k, array in enumerate(values):
        arr = np.asarray(array, dtype=float).reshape(-1)
        if arr.size != xs_raw.size:
            raise ValueError(
                f"values[{k}] must supply one value per POI, got {arr.size} "
                f"for {xs_raw.size} points"
            )
        grid = np.full(ys.size * xs.size, np.nan)
        grid[flat] = arr
        grids.append(grid.reshape(ys.size, xs.size))
    return xs, ys, grids
