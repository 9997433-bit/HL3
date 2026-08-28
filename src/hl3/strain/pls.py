# SPDX-License-Identifier: Apache-2.0
"""Pointwise least squares (PLS) displacement gradients on a POI grid.

Implements step 1 of spec R1-O1 section 2.11 (Pan et al., *Opt. Eng.* 46:033601,
2007): around every point of a regular POI grid, fit a low-order polynomial to
the neighbouring displacements in a least-squares sense and read the strain off
the fitted first-order coefficients::

    u(dx, dy) = a0 + a1 dx + a2 dy [+ a3 dx^2 + a4 dx dy + a5 dy^2]
    v(dx, dy) = b0 + b1 dx + b2 dy [+ ...]

    u_x = a1,  u_y = a2,  v_x = b1,  v_y = b2

Differentiating a fit rather than differencing the raw field is what makes DIC
strain usable at all: displacement noise of 0.01 px differenced over a 5 px step
would be 2000 microstrain of noise. The price is spatial resolution, and the
price tag is the VSG size in :mod:`hl3.strain.vsg`.

Implementation
--------------
The fit is done for every grid point at once. Because every point uses the same
window offsets and the same weights, each entry of the normal equations is a
windowed sum, and every such sum is a separable 2-D correlation of either the
validity mask (for the Gram matrix) or the masked displacement (for the
right-hand side) with a kernel ``w(dx) dx^a`` times ``w(dy) dy^b``. So the whole
field costs a handful of 1-D correlations plus one batched 3x3 (or 6x6) solve,
with no Python loop over points, and -- crucially -- the mask enters the normal
equations directly, so a window with holes in it is solved exactly rather than
approximately.

Fitting is done in *index* units (offsets counted in POI, not pixels) and the
gradients are divided by ``step_px`` at the end. That keeps the normal matrix
well conditioned for any step and makes the quadratic terms O(r^4) instead of
O((r*step)^4).

Failure conventions, matching :mod:`hl3.stereo.triangulate`:

* broken calling code raises :class:`ValueError` -- wrong shapes, even windows,
  non-positive steps, unknown option strings;
* missing measurements propagate as ``nan`` -- a point whose window holds fewer
  than ``neighbor_min`` valid neighbours gets ``nan`` gradients, never a value
  extrapolated from somewhere else and never a zero-filled one. Spec section
  2.11 is explicit about this ("不外推、不用零填充"), because a zero-filled
  strain hole looks exactly like an unloaded region;
* rank-deficient windows -- all neighbours collinear, e.g. a single grid row --
  are rejected by an eigenvalue test rather than solved into a plausible number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

__all__ = [
    "DEFAULT_FIT_ORDER",
    "DEFAULT_MIN_VALID_FRACTION",
    "DEFAULT_WEIGHTING",
    "DEFAULT_WINDOW_PTS",
    "GradientField",
    "neighbor_min_for",
    "pls_gradients",
]

DEFAULT_WINDOW_PTS = 5  # data points, spec section 1.6
DEFAULT_FIT_ORDER = "linear"
# Spec section 1.6 makes Gaussian weighting the product default; IR1-F3 froze
# ``uniform`` as the S1 default and made the flip a gated numerical change.
# Both are implemented; only the default is held back.
DEFAULT_WEIGHTING = "uniform"
DEFAULT_MIN_VALID_FRACTION = 0.5  # of window_pts^2, spec section 1.6

# Monomial exponents (a, b) of the basis terms dx^a dy^b, ordered so that
# index 1 is dx and index 2 is dy for both orders. The gradient reader below
# depends on that ordering.
_TERMS = {
    "linear": ((0, 0), (1, 0), (0, 1)),
    "quadratic": ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)),
}

_WEIGHTINGS = ("uniform", "gaussian")

# Relative floor on the smallest eigenvalue of the normal matrix, below which
# the window is treated as rank deficient. Double precision carries ~2.2e-16 of
# relative error; 1e-12 leaves four decades of headroom while still sitting far
# below any genuinely two-dimensional point cloud (a full 5x5 window scores
# ~0.2, a single collinear row scores ~1e-17).
_REL_EPS = 1e-12


@dataclass(frozen=True)
class GradientField:
    """Displacement gradients on the POI grid, all arrays shaped ``(ny, nx)``.

    ``u_fit`` and ``v_fit`` are the fitted displacements at the window centre,
    i.e. the smoothed displacement field that comes free with the fit. They are
    *not* the input displacements: the difference between the two is the local
    fit residual and is the natural input to a displacement pre-filter study.
    """

    u_x: np.ndarray
    u_y: np.ndarray
    v_x: np.ndarray
    v_y: np.ndarray
    u_fit: np.ndarray
    v_fit: np.ndarray
    n_neighbors: np.ndarray  # valid POI that entered each window, int
    window_pts: int
    fit_order: str
    step_px: float

    @property
    def valid(self) -> np.ndarray:
        """Points where the fit succeeded."""
        return np.isfinite(self.u_x)

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.u_x.shape[0]), int(self.u_x.shape[1]))


def neighbor_min_for(window_pts: int, frac: float = DEFAULT_MIN_VALID_FRACTION) -> int:
    """Minimum valid neighbours for a window, spec section 1.6's ``0.5 * L^2``.

    Rounded up, and never below the number of fitted coefficients, since fewer
    points than coefficients cannot determine a fit at all.
    """
    win = _as_window(window_pts)
    if not math.isfinite(frac) or frac <= 0.0:
        raise ValueError(f"frac must be finite and > 0, got {frac!r}")
    return max(1, math.ceil(frac * win * win))


def _as_window(window_pts: int) -> int:
    if isinstance(window_pts, bool) or window_pts != int(window_pts):
        raise ValueError(
            f"window_pts must be an integer number of POI, got {window_pts!r}"
        )
    win = int(window_pts)
    if win < 3:
        raise ValueError(
            f"window_pts must be >= 3 POI for a local fit, got {win}; a 1-point "
            "window means 'take the strain from the subset shape function' and "
            "is handled by the correlator, not here"
        )
    if win % 2 == 0:
        raise ValueError(
            f"window_pts must be odd so the fit is centred on a POI, got {win}"
        )
    return win


def _as_field(values: np.ndarray, name: str, shape: tuple[int, ...] | None) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"{name} must be a 2-D (ny, nx) grid of POI values, got shape {arr.shape}"
        )
    if shape is not None and arr.shape != shape:
        raise ValueError(
            f"{name} must have the same shape as u, got {arr.shape} and {shape}"
        )
    return arr


def _weights_1d(window_pts: int, weighting: str, sigma: float | None) -> np.ndarray:
    """Window weights along one axis, indexed by offset ``-r ... r``."""
    radius = window_pts // 2
    offsets = np.arange(-radius, radius + 1, dtype=float)
    if weighting == "uniform":
        return np.ones_like(offsets)
    if weighting == "gaussian":
        s = window_pts / 4.0 if sigma is None else float(sigma)
        if not math.isfinite(s) or s <= 0.0:
            raise ValueError(f"sigma must be finite and > 0, got {sigma!r}")
        return np.exp(-0.5 * (offsets / s) ** 2)
    raise ValueError(f"weighting must be one of {_WEIGHTINGS}, got {weighting!r}")


def _correlate1d(field: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """``out[p] = sum_d kernel[d + r] * field[p + d]`` with zero padding.

    Zero padding is correct here rather than merely convenient: the arrays being
    correlated are already masked, so a zero contribution is exactly what a POI
    outside the grid should contribute. Mirroring would invent data.
    """
    radius = (kernel.size - 1) // 2
    pad = [(0, 0)] * field.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(field, pad)
    windows = sliding_window_view(padded, kernel.size, axis=axis)
    return np.tensordot(windows, kernel, axes=([-1], [0]))


def _windowed_sum(
    field: np.ndarray, kernel_x: np.ndarray, kernel_y: np.ndarray
) -> np.ndarray:
    """Separable 2-D correlation: ``kernel_x`` along x (axis 1), ``kernel_y`` along y."""
    return _correlate1d(_correlate1d(field, kernel_x, axis=1), kernel_y, axis=0)


def pls_gradients(
    u: np.ndarray,
    v: np.ndarray,
    *,
    step_px: float = 1.0,
    window_pts: int = DEFAULT_WINDOW_PTS,
    fit_order: str = DEFAULT_FIT_ORDER,
    weighting: str = DEFAULT_WEIGHTING,
    sigma: float | None = None,
    valid: np.ndarray | None = None,
    neighbor_min: int | None = None,
    require_center: bool = True,
) -> GradientField:
    """Fit displacement gradients on a regular POI grid by weighted PLS.

    Parameters
    ----------
    u, v
        Displacement components on the POI grid, shape ``(ny, nx)``, with ``x``
        along axis 1 and ``y`` along axis 0 (the layout produced by reshaping
        :func:`hl3.correlate.make_grid` output). ``nan`` marks a point the
        correlator did not solve.
    step_px
        POI grid pitch in the same length unit as ``u`` and ``v``. Gradients are
        dimensionless, so the unit cancels -- but only if it is the same unit,
        which is the caller's responsibility: displacements in pixels need a
        step in pixels.
    window_pts
        Fit window in POI, odd and >= 3. This is the parameter that trades
        strain noise against spatial resolution; see :mod:`hl3.strain.vsg`.
    fit_order
        ``"linear"`` (plane fit, default) or ``"quadratic"``. On a full,
        symmetric window the two give *identical* gradients, because the extra
        basis terms are even in each axis and the gradient terms are odd. The
        quadratic order earns its cost exactly where the window is not
        symmetric: at grid edges, next to holes, and along a mask boundary.
    weighting
        ``"uniform"`` (default, the classical Pan PLS) or ``"gaussian"``
        (``sigma = window_pts / 4`` per spec section 1.6). Gaussian weights
        soften the window edge, which lowers the sidelobes of the implied filter
        at the cost of a smaller effective gauge -- the nominal ``L_VSG`` is
        unchanged, so two analyses that differ only in weighting are not
        strictly comparable by VSG alone. That is why the default is the
        unweighted fit and the flip is a gated change (IR1-F3 section 4).
    valid
        Optional boolean grid of usable POI, i.e. ``status == CONVERGED``.
        Combined with the finiteness of ``u`` and ``v``.
    neighbor_min
        Minimum valid POI inside a window; below it the point is ``nan``.
        Defaults to :func:`neighbor_min_for`, i.e. half the window area.
    require_center
        When true (default) a point whose own displacement is missing gets
        ``nan`` strain even if its neighbourhood is well populated. Setting it
        false lets the fit interpolate across single-point dropouts, which is
        legitimate for filling pinholes but is extrapolation at a mask edge, so
        it is off by default and must be reported when used.

    Returns
    -------
    GradientField
        Gradients, fitted displacements and the per-point neighbour count.
    """
    u = _as_field(u, "u", None)
    v = _as_field(v, "v", u.shape)
    win = _as_window(window_pts)
    if fit_order not in _TERMS:
        raise ValueError(
            f"fit_order must be one of {tuple(_TERMS)}, got {fit_order!r}"
        )
    terms = _TERMS[fit_order]
    step = float(step_px)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError(f"step_px must be finite and > 0, got {step_px!r}")

    if neighbor_min is None:
        neighbor_min = neighbor_min_for(win)
    else:
        if isinstance(neighbor_min, bool) or neighbor_min != int(neighbor_min):
            raise ValueError(
                f"neighbor_min must be an integer, got {neighbor_min!r}"
            )
        neighbor_min = int(neighbor_min)
        if neighbor_min < 1:
            raise ValueError(f"neighbor_min must be >= 1, got {neighbor_min}")
    # Fewer samples than coefficients is never solvable, whatever the caller asked.
    neighbor_min = max(neighbor_min, len(terms))

    mask = np.isfinite(u) & np.isfinite(v)
    if valid is not None:
        valid_arr = np.asarray(valid)
        if valid_arr.shape != u.shape:
            raise ValueError(
                f"valid must have the same shape as u, got {valid_arr.shape} "
                f"and {u.shape}"
            )
        if valid_arr.dtype != np.bool_:
            raise ValueError(
                f"valid must be a boolean mask, got dtype {valid_arr.dtype}"
            )
        mask = mask & valid_arr

    weights = _weights_1d(win, weighting, sigma)
    radius = win // 2
    offsets = np.arange(-radius, radius + 1, dtype=float)

    def kernel(exponent: int) -> np.ndarray:
        return weights * offsets**exponent

    mask_f = mask.astype(float)
    u_masked = np.where(mask, u, 0.0)
    v_masked = np.where(mask, v, 0.0)

    gram_cache: dict[tuple[int, int], np.ndarray] = {}

    def gram_sum(a: int, b: int) -> np.ndarray:
        key = (a, b)
        if key not in gram_cache:
            gram_cache[key] = _windowed_sum(mask_f, kernel(a), kernel(b))
        return gram_cache[key]

    n_terms = len(terms)
    ny, nx = u.shape
    gram = np.empty((ny, nx, n_terms, n_terms))
    for i, (ai, bi) in enumerate(terms):
        for j, (aj, bj) in enumerate(terms[: i + 1]):
            block = gram_sum(ai + aj, bi + bj)
            gram[..., i, j] = block
            gram[..., j, i] = block

    rhs = np.stack(
        [
            np.stack(
                [_windowed_sum(field, kernel(a), kernel(b)) for a, b in terms],
                axis=-1,
            )
            for field in (u_masked, v_masked)
        ],
        axis=-1,
    )  # (ny, nx, n_terms, 2)

    ones = np.ones_like(offsets)
    n_neighbors = np.rint(_windowed_sum(mask_f, ones, ones)).astype(np.int32)

    accepted = n_neighbors >= neighbor_min
    if require_center:
        accepted &= mask

    gram_flat = gram.reshape(ny * nx, n_terms, n_terms)
    rhs_flat = rhs.reshape(ny * nx, n_terms, 2)
    coeffs_flat = np.full((ny * nx, n_terms, 2), np.nan)
    idx = np.flatnonzero(accepted.ravel())
    if idx.size:
        # The Gram matrix is symmetric positive semi-definite by construction,
        # so the ratio of its extreme eigenvalues is the natural rank test, and
        # eigvalsh is batched. A batched solve raises for the whole field if any
        # single matrix is exactly singular, so the degenerate windows have to
        # be dropped before the solve rather than after it.
        eig = np.linalg.eigvalsh(gram_flat[idx])
        idx = idx[eig[:, 0] > _REL_EPS * eig[:, -1]]
    if idx.size:
        coeffs_flat[idx] = np.linalg.solve(gram_flat[idx], rhs_flat[idx])
    coeffs = coeffs_flat.reshape(ny, nx, n_terms, 2)

    return GradientField(
        u_x=coeffs[..., 1, 0] / step,
        u_y=coeffs[..., 2, 0] / step,
        v_x=coeffs[..., 1, 1] / step,
        v_y=coeffs[..., 2, 1] / step,
        u_fit=coeffs[..., 0, 0],
        v_fit=coeffs[..., 0, 1],
        n_neighbors=n_neighbors,
        window_pts=win,
        fit_order=fit_order,
        step_px=step,
    )
