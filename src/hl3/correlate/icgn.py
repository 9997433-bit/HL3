"""CPU reference implementation of first-order IC-GN digital image correlation.

This module is the normative (slow, readable) reference for the HL3-2D local
correlator described in ``.agent_workspace/round1/R1-O1-hl3-2d-spec.md`` §2.
Any future accelerated backend must reproduce its numbers.

Design choices, all taken from the Round 1 spec:

* Criterion: ZNSSD is minimised (least-squares form, feeds Gauss-Newton
  directly); ZNCC is reported, using ``C_ZNSSD = 2 (1 - C_ZNCC)``.
  Zero-mean + normalisation makes the solver exactly invariant to an affine
  greyscale change ``g = a f + b`` with ``a > 0``.
* Shape function: first order (affine), ``p = (u, u_x, u_y, v, v_x, v_y)``.
* Inverse-compositional Gauss-Newton: the warp increment is applied to the
  *reference* subset, so the steepest-descent images, the Hessian and its
  factorisation are computed once per point instead of once per iteration.
* Interpolation of the target: bicubic B-spline (prefiltered coefficients).
* Reference gradients: 4th-order central differences, *not* the analytic
  derivative of the interpolant -- mixing the two breaks the IC-GN
  consistency argument.

Only NumPy is required. No GPU, no external DIC code.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "Status",
    "ICGNParams",
    "ICGNResult",
    "BSplineInterpolator",
    "reference_gradients",
    "make_grid",
    "integer_search_fftcc",
    "warp_matrix",
    "warp_params",
    "compose_inverse",
    "icgn_first_order",
]


class Status(enum.IntEnum):
    """Per-point outcome. Mirrors ``hl3::corr2d::Status`` in the 2D spec."""

    UNCOMPUTED = 0
    CONVERGED = 1
    LOW_ZNCC = 2
    NOT_CONVERGED = 3
    OUT_OF_BOUNDS = 4
    SINGULAR_HESSIAN = 5
    DIVERGED = 6


@dataclass(frozen=True)
class ICGNParams:
    """Correlation parameters. Defaults follow the spec's §7 table."""

    subset_radius: int = 10  # 21 x 21 subset
    step: int = 5
    conv_tol: float = 1e-4  # px, scaled ||dp||
    max_iter: int = 30
    zncc_min: float = 0.80
    max_disp: float = 1.0e4  # px
    hessian_reg: float = 1e-9  # diagonal loading, relative to tr(H)/n
    search_radius: int = 0  # FFT-CC integer search half-width; 0 disables
    compute_covariance: bool = False
    image_noise_sigma: float = 0.0  # grey levels, for the covariance estimate

    def __post_init__(self) -> None:
        if self.subset_radius < 2:
            raise ValueError("subset_radius must be >= 2")
        if self.step < 1:
            raise ValueError("step must be >= 1")
        if self.max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        if self.search_radius < 0:
            raise ValueError("search_radius must be >= 0")

    @property
    def subset_size(self) -> int:
        return 2 * self.subset_radius + 1


@dataclass
class ICGNResult:
    """Solution for a set of points. All arrays are indexed by point."""

    x: np.ndarray  # (n,) reference-configuration x
    y: np.ndarray  # (n,) reference-configuration y
    p: np.ndarray  # (n, 6) = (u, u_x, u_y, v, v_x, v_y)
    zncc: np.ndarray  # (n,)
    iterations: np.ndarray  # (n,) int
    status: np.ndarray  # (n,) Status as int
    covariance: np.ndarray | None = field(default=None)  # (n, 6, 6) or None

    @property
    def u(self) -> np.ndarray:
        return self.p[:, 0]

    @property
    def v(self) -> np.ndarray:
        return self.p[:, 3]

    @property
    def valid(self) -> np.ndarray:
        """Points that converged and cleared the ZNCC threshold."""
        return self.status == int(Status.CONVERGED)

    def masked(self, field_name: str) -> np.ndarray:
        """A copy of ``field_name`` with non-converged points set to NaN."""
        values = np.asarray(getattr(self, field_name), dtype=np.float64).copy()
        values[~self.valid] = np.nan
        return values


# --------------------------------------------------------------------------
# Bicubic B-spline interpolation
# --------------------------------------------------------------------------

_BSPLINE_POLE = math.sqrt(3.0) - 2.0


def _prefilter_axis(data: np.ndarray, axis: int) -> np.ndarray:
    """Unser's causal/anti-causal recursion for cubic B-spline coefficients.

    Boundary handling is whole-sample mirroring, matching the ``reflect101``
    padding used when the coefficient grid is sampled.
    """
    out = np.moveaxis(np.array(data, dtype=np.float64, copy=True), axis, 0)
    n = out.shape[0]
    if n == 1:
        return np.moveaxis(out, 0, axis)

    z = _BSPLINE_POLE
    out *= 6.0

    # Causal initialisation: truncate the infinite mirrored sum once the pole
    # powers fall below double precision.
    horizon = min(n, int(math.ceil(math.log(1e-16) / math.log(abs(z)))))
    zk = z
    acc = out[0].copy()
    for k in range(1, horizon):
        acc += zk * out[k]
        zk *= z
    out[0] = acc
    for k in range(1, n):
        out[k] += z * out[k - 1]

    # Anti-causal initialisation and recursion.
    out[n - 1] = (z / (z * z - 1.0)) * (z * out[n - 2] + out[n - 1])
    for k in range(n - 2, -1, -1):
        out[k] = z * (out[k + 1] - out[k])

    return np.moveaxis(out, 0, axis)


def _mirror_index(index: np.ndarray, n: int) -> np.ndarray:
    """Whole-sample symmetric (reflect101) index folding."""
    if n == 1:
        return np.zeros_like(index)
    period = 2 * n - 2
    folded = np.abs(index) % period
    return np.where(folded >= n, period - folded, folded)


class BSplineInterpolator:
    """Bicubic B-spline sampler for a single ``float64`` image.

    The prefiltered coefficient grid is computed once at construction, so a
    sample costs 16 multiply-adds. Because the cubic B-spline is an
    interpolating basis after prefiltering, sampling at integer coordinates
    returns the original pixel values to round-off.
    """

    def __init__(self, image: np.ndarray) -> None:
        image = np.asarray(image, dtype=np.float64)
        if image.ndim != 2:
            raise ValueError("image must be 2-D")
        self.height, self.width = image.shape
        coefficients = _prefilter_axis(image, axis=0)
        self.coefficients = _prefilter_axis(coefficients, axis=1)

    def __call__(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return self.sample(x, y)

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        ix = np.floor(x).astype(np.int64)
        iy = np.floor(y).astype(np.int64)
        tx = x - ix
        ty = y - iy

        wx = _cubic_weights(tx)  # (4, ...)
        wy = _cubic_weights(ty)

        taps = np.arange(-1, 3).reshape((4,) + (1,) * x.ndim)
        cols = _mirror_index(ix[None, ...] + taps, self.width)
        rows = _mirror_index(iy[None, ...] + taps, self.height)

        # Separable evaluation: collapse rows first, then columns.
        partial = np.zeros((4,) + x.shape, dtype=np.float64)
        for j in range(4):
            column = np.zeros(x.shape, dtype=np.float64)
            for i in range(4):
                column += wy[i] * self.coefficients[rows[i], cols[j]]
            partial[j] = column
        return np.einsum("j...,j...->...", wx, partial)


def _cubic_weights(t: np.ndarray) -> np.ndarray:
    """Cubic B-spline basis values at offsets ``-1, 0, 1, 2`` for ``t in [0, 1)``."""
    t2 = t * t
    t3 = t2 * t
    one_minus = 1.0 - t
    return np.stack(
        (
            one_minus * one_minus * one_minus / 6.0,
            (3.0 * t3 - 6.0 * t2 + 4.0) / 6.0,
            (-3.0 * t3 + 3.0 * t2 + 3.0 * t + 1.0) / 6.0,
            t3 / 6.0,
        )
    )


# --------------------------------------------------------------------------
# Reference gradients
# --------------------------------------------------------------------------


def reference_gradients(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4th-order central-difference gradients ``(f_x, f_y)``.

    The two-pixel border falls back to 2nd-order central differences and then
    to one-sided differences at the very edge.
    """
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError("image must be 2-D")

    def diff_axis(axis: int) -> np.ndarray:
        arr = np.moveaxis(image, axis, 0)
        n = arr.shape[0]
        out = np.zeros_like(arr)
        if n < 2:
            return np.moveaxis(out, 0, axis)
        if n >= 5:
            out[2:-2] = (arr[:-4] - 8.0 * arr[1:-3] + 8.0 * arr[3:-1] - arr[4:]) / 12.0
            out[1] = 0.5 * (arr[2] - arr[0])
            out[n - 2] = 0.5 * (arr[n - 1] - arr[n - 3])
        elif n >= 3:
            out[1:-1] = 0.5 * (arr[2:] - arr[:-2])
        out[0] = arr[1] - arr[0]
        out[n - 1] = arr[n - 1] - arr[n - 2]
        return np.moveaxis(out, 0, axis)

    return diff_axis(1), diff_axis(0)


# --------------------------------------------------------------------------
# Point grid
# --------------------------------------------------------------------------


def make_grid(
    shape: tuple[int, int],
    params: ICGNParams,
    margin: int | None = None,
) -> np.ndarray:
    """Regular POI grid, ``(n, 2)`` array of ``(x, y)`` reference coordinates.

    ``margin`` defaults to the subset radius plus the integer search radius
    plus two pixels of interpolation support, i.e. the smallest border for
    which every subset sample stays inside the image.
    """
    height, width = shape
    if margin is None:
        margin = params.subset_radius + params.search_radius + 2
    if 2 * margin >= min(height, width):
        raise ValueError("image too small for the requested subset/margin")
    xs = np.arange(margin, width - margin, params.step, dtype=np.float64)
    ys = np.arange(margin, height - margin, params.step, dtype=np.float64)
    grid_x, grid_y = np.meshgrid(xs, ys)
    return np.column_stack((grid_x.ravel(), grid_y.ravel()))


# --------------------------------------------------------------------------
# Integer initial guess (FFT-accelerated ZNCC search)
# --------------------------------------------------------------------------


def integer_search_fftcc(
    reference: np.ndarray,
    target: np.ndarray,
    point: tuple[float, float],
    radius: int,
    search_radius: int,
) -> tuple[float, float, float]:
    """Integer-pixel ``(u, v, zncc)`` for one point by FFT cross-correlation.

    The reference subset is zero-meaned and correlated against a search window
    of the target; the local target mean and norm needed to turn the raw
    correlation into a true ZNCC come from summed-area tables, so the whole
    map costs ``O(M^2 log M)`` rather than ``O(M^2 N)``.
    """
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    x0 = int(round(point[0]))
    y0 = int(round(point[1]))
    n = 2 * radius + 1
    m = n + 2 * search_radius

    ref_top, ref_left = y0 - radius, x0 - radius
    win_top, win_left = ref_top - search_radius, ref_left - search_radius
    if (
        ref_top < 0
        or ref_left < 0
        or ref_top + n > reference.shape[0]
        or ref_left + n > reference.shape[1]
        or win_top < 0
        or win_left < 0
        or win_top + m > target.shape[0]
        or win_left + m > target.shape[1]
    ):
        return 0.0, 0.0, -1.0

    subset = reference[ref_top : ref_top + n, ref_left : ref_left + n]
    window = target[win_top : win_top + m, win_left : win_left + m]

    zero_mean = subset - subset.mean()
    ref_norm = math.sqrt(float(np.sum(zero_mean * zero_mean)))
    if ref_norm <= 0.0:
        return 0.0, 0.0, -1.0

    spectrum = np.conj(np.fft.rfft2(zero_mean, s=(m, m))) * np.fft.rfft2(window)
    correlation = np.fft.irfft2(spectrum, s=(m, m))[
        : 2 * search_radius + 1, : 2 * search_radius + 1
    ]

    count = float(n * n)
    sums = _window_sums(window, n)
    sums_sq = _window_sums(window * window, n)
    variance = sums_sq - sums * sums / count
    np.maximum(variance, 0.0, out=variance)
    window_norm = np.sqrt(variance)

    with np.errstate(divide="ignore", invalid="ignore"):
        zncc_map = correlation / (ref_norm * window_norm)
    zncc_map[~np.isfinite(zncc_map)] = -1.0

    peak = int(np.argmax(zncc_map))
    dy, dx = np.unravel_index(peak, zncc_map.shape)
    return (
        float(dx - search_radius),
        float(dy - search_radius),
        float(zncc_map[dy, dx]),
    )


def _window_sums(image: np.ndarray, n: int) -> np.ndarray:
    """Sums over every ``n x n`` window, via a summed-area table."""
    integral = np.zeros((image.shape[0] + 1, image.shape[1] + 1), dtype=np.float64)
    np.cumsum(np.cumsum(image, axis=0), axis=1, out=integral[1:, 1:])
    return (
        integral[n:, n:] - integral[:-n, n:] - integral[n:, :-n] + integral[:-n, :-n]
    )


# --------------------------------------------------------------------------
# First-order shape function algebra
# --------------------------------------------------------------------------


def warp_matrix(p: np.ndarray) -> np.ndarray:
    """Homogeneous 3x3 warp for ``p = (u, u_x, u_y, v, v_x, v_y)``."""
    u, ux, uy, v, vx, vy = (float(value) for value in p)
    return np.array(
        [
            [1.0 + ux, uy, u],
            [vx, 1.0 + vy, v],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def warp_params(matrix: np.ndarray) -> np.ndarray:
    """Inverse of :func:`warp_matrix`."""
    return np.array(
        [
            matrix[0, 2],
            matrix[0, 0] - 1.0,
            matrix[0, 1],
            matrix[1, 2],
            matrix[1, 0],
            matrix[1, 1] - 1.0,
        ],
        dtype=np.float64,
    )


def compose_inverse(p: np.ndarray, dp: np.ndarray) -> np.ndarray:
    """The inverse-compositional update ``W(p) <- W(p) . W(dp)^-1``."""
    increment = warp_matrix(dp)
    determinant = increment[0, 0] * increment[1, 1] - increment[0, 1] * increment[1, 0]
    if abs(determinant) < 1e-12:
        raise np.linalg.LinAlgError("degenerate warp increment")
    return warp_params(warp_matrix(p) @ np.linalg.inv(increment))


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------


def icgn_first_order(
    reference: np.ndarray,
    target: np.ndarray,
    points: np.ndarray | None = None,
    params: ICGNParams | None = None,
    initial_guess: np.ndarray | None = None,
) -> ICGNResult:
    """Solve first-order IC-GN / ZNSSD for every point.

    Parameters
    ----------
    reference, target:
        2-D greyscale images of identical shape.
    points:
        ``(n, 2)`` array of ``(x, y)`` reference-configuration centres. When
        omitted a regular grid from :func:`make_grid` is used.
    params:
        Correlation parameters; defaults to :class:`ICGNParams`.
    initial_guess:
        ``(n, 6)`` warp parameters, or ``(n, 2)`` displacements, used to seed
        the iteration. When omitted, the seed is the FFT-CC integer search if
        ``params.search_radius > 0`` and zero otherwise.
    """
    params = params or ICGNParams()
    reference = np.asarray(reference, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if reference.shape != target.shape:
        raise ValueError("reference and target must have the same shape")
    if reference.ndim != 2:
        raise ValueError("images must be 2-D")

    if points is None:
        points = make_grid(reference.shape, params)
    points = np.atleast_2d(np.asarray(points, dtype=np.float64))
    if points.shape[1] != 2:
        raise ValueError("points must be an (n, 2) array of (x, y)")
    n_points = points.shape[0]

    radius = params.subset_radius
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    dx, dy = np.meshgrid(offsets, offsets)
    dx = dx.ravel()
    dy = dy.ravel()

    ref_interp = BSplineInterpolator(reference)
    tgt_interp = BSplineInterpolator(target)
    grad_x, grad_y = reference_gradients(reference)
    gx_interp = BSplineInterpolator(grad_x)
    gy_interp = BSplineInterpolator(grad_y)

    seeds = _resolve_initial_guess(
        reference, target, points, params, initial_guess, n_points
    )

    p_out = np.zeros((n_points, 6), dtype=np.float64)
    zncc_out = np.full(n_points, -1.0, dtype=np.float64)
    iters_out = np.zeros(n_points, dtype=np.int32)
    status_out = np.full(n_points, int(Status.UNCOMPUTED), dtype=np.int32)
    cov_out = (
        np.full((n_points, 6, 6), np.nan, dtype=np.float64)
        if params.compute_covariance
        else None
    )

    height, width = reference.shape
    scale = np.array([1.0, radius, radius, 1.0, radius, radius], dtype=np.float64)

    for index in range(n_points):
        x0, y0 = points[index]
        sample_x = x0 + dx
        sample_y = y0 + dy
        if (
            sample_x.min() < 0.0
            or sample_y.min() < 0.0
            or sample_x.max() > width - 1.0
            or sample_y.max() > height - 1.0
        ):
            status_out[index] = int(Status.OUT_OF_BOUNDS)
            continue

        f = ref_interp.sample(sample_x, sample_y)
        f_mean = f.mean()
        f_centred = f - f_mean
        f_norm = math.sqrt(float(np.dot(f_centred, f_centred)))
        if f_norm < 1e-9:
            status_out[index] = int(Status.SINGULAR_HESSIAN)
            continue

        fx = gx_interp.sample(sample_x, sample_y)
        fy = gy_interp.sample(sample_x, sample_y)
        # Steepest-descent images: grad f . dW/dp, evaluated at p = 0.
        jacobian = np.column_stack((fx, fx * dx, fx * dy, fy, fy * dx, fy * dy))

        hessian_raw = jacobian.T @ jacobian
        trace_scale = float(np.trace(hessian_raw)) / 6.0
        hessian_raw = hessian_raw + params.hessian_reg * trace_scale * np.eye(6)
        hessian = (2.0 / (f_norm * f_norm)) * hessian_raw
        try:
            cho = np.linalg.cholesky(hessian)
        except np.linalg.LinAlgError:
            status_out[index] = int(Status.SINGULAR_HESSIAN)
            continue

        p = seeds[index].copy()
        status = int(Status.NOT_CONVERGED)
        zncc = -1.0
        used_iterations = 0

        for iteration in range(1, params.max_iter + 1):
            used_iterations = iteration
            warped_x = x0 + dx + p[0] + p[1] * dx + p[2] * dy
            warped_y = y0 + dy + p[3] + p[4] * dx + p[5] * dy
            if (
                warped_x.min() < 0.0
                or warped_y.min() < 0.0
                or warped_x.max() > width - 1.0
                or warped_y.max() > height - 1.0
            ):
                status = int(Status.OUT_OF_BOUNDS)
                break

            g = tgt_interp.sample(warped_x, warped_y)
            g_centred = g - g.mean()
            g_norm = math.sqrt(float(np.dot(g_centred, g_centred)))
            if g_norm < 1e-9:
                status = int(Status.SINGULAR_HESSIAN)
                break

            ratio = f_norm / g_norm
            residual = f_centred - ratio * g_centred
            rhs = (2.0 / (f_norm * f_norm)) * (jacobian.T @ residual)
            delta_p = -_cho_solve(cho, rhs)

            zncc = float(np.dot(f_centred, g_centred) / (f_norm * g_norm))

            try:
                p = compose_inverse(p, delta_p)
            except np.linalg.LinAlgError:
                status = int(Status.SINGULAR_HESSIAN)
                break

            if not np.all(np.isfinite(p)) or math.hypot(p[0], p[3]) > params.max_disp:
                status = int(Status.DIVERGED)
                break

            if float(np.linalg.norm(delta_p * scale)) < params.conv_tol:
                status = int(Status.CONVERGED)
                break

        if status == int(Status.CONVERGED):
            # Recompute ZNCC at the final warp so the reported quality matches
            # the returned parameters rather than the previous iterate.
            warped_x = x0 + dx + p[0] + p[1] * dx + p[2] * dy
            warped_y = y0 + dy + p[3] + p[4] * dx + p[5] * dy
            if (
                warped_x.min() < 0.0
                or warped_y.min() < 0.0
                or warped_x.max() > width - 1.0
                or warped_y.max() > height - 1.0
            ):
                status = int(Status.OUT_OF_BOUNDS)
            else:
                g = tgt_interp.sample(warped_x, warped_y)
                g_centred = g - g.mean()
                g_norm = math.sqrt(float(np.dot(g_centred, g_centred)))
                zncc = (
                    float(np.dot(f_centred, g_centred) / (f_norm * g_norm))
                    if g_norm > 1e-9
                    else -1.0
                )
                if zncc < params.zncc_min:
                    status = int(Status.LOW_ZNCC)

        p_out[index] = p
        zncc_out[index] = zncc
        iters_out[index] = used_iterations
        status_out[index] = status

        if cov_out is not None and status in (
            int(Status.CONVERGED),
            int(Status.LOW_ZNCC),
        ):
            # Cov(p) ~ 2 sigma_n^2 (J^T J)^-1 for i.i.d. Gaussian sensor noise
            # in both images (spec §2.6).
            sigma = params.image_noise_sigma
            try:
                cov_out[index] = 2.0 * sigma * sigma * np.linalg.inv(hessian_raw)
            except np.linalg.LinAlgError:
                pass

    return ICGNResult(
        x=points[:, 0].copy(),
        y=points[:, 1].copy(),
        p=p_out,
        zncc=zncc_out,
        iterations=iters_out,
        status=status_out,
        covariance=cov_out,
    )


def _cho_solve(cho: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    """Solve ``L L^T x = rhs`` given the lower Cholesky factor ``L``."""
    forward = np.linalg.solve(cho, rhs)
    return np.linalg.solve(cho.T, forward)


def _resolve_initial_guess(
    reference: np.ndarray,
    target: np.ndarray,
    points: np.ndarray,
    params: ICGNParams,
    initial_guess: np.ndarray | None,
    n_points: int,
) -> np.ndarray:
    seeds = np.zeros((n_points, 6), dtype=np.float64)
    if initial_guess is not None:
        guess = np.atleast_2d(np.asarray(initial_guess, dtype=np.float64))
        if guess.shape[0] == 1 and n_points > 1:
            guess = np.repeat(guess, n_points, axis=0)
        if guess.shape == (n_points, 6):
            seeds[:] = guess
        elif guess.shape == (n_points, 2):
            seeds[:, 0] = guess[:, 0]
            seeds[:, 3] = guess[:, 1]
        else:
            raise ValueError("initial_guess must have shape (n, 2) or (n, 6)")
        return seeds

    if params.search_radius > 0:
        for index in range(n_points):
            u0, v0, _ = integer_search_fftcc(
                reference,
                target,
                (points[index, 0], points[index, 1]),
                params.subset_radius,
                params.search_radius,
            )
            seeds[index, 0] = u0
            seeds[index, 3] = v0
    return seeds
