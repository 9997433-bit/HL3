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

Degenerate inputs are answered with a status code, never with a plausible
looking number: a subset whose contrast is round-off rather than texture, a
subset whose gradients only span one direction, a point whose integer search
window leaves the image, and an empty AOI are all defined cases (spec §2.6
failure table). Non-finite pixels are rejected at the API boundary instead --
the B-spline prefilter is an IIR recursion, so a single NaN would silently
poison a whole row and column of coefficients.

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

# A subset whose RMS contrast is below this fraction of the whole image's
# contrast is floating-point residue -- the B-spline prefilter is an IIR
# recursion, so texture outside a flat patch leaks a decaying tail into it --
# rather than something to correlate. Double-precision resampling leaves
# ~1e-14 relative; real speckle sits at ~1e-1 relative, so there are five
# decades of headroom on either side.
_CONTRAST_REL_EPS = 1e-9


class Status(enum.IntEnum):
    """Per-point outcome. Mirrors ``hl3::corr2d::Status`` in the 2D spec.

    The *values* here are normative: R1-O1 §4.3 declares the C++ enum in a
    different order (``NO_INITIAL_GUESS`` before ``DIVERGED``), so that
    declaration needs explicit initialisers to agree with these numbers. The
    numbering below is the one already published in R2-O1 §2.7 and is kept
    stable; see the Round 3 report for the reconciliation note.
    """

    UNCOMPUTED = 0
    CONVERGED = 1
    LOW_ZNCC = 2
    NOT_CONVERGED = 3
    OUT_OF_BOUNDS = 4
    SINGULAR_HESSIAN = 5
    DIVERGED = 6
    NO_INITIAL_GUESS = 7
    MASKED = 8


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
    # Absolute RMS-contrast floor in grey levels. The default 0 leaves only
    # the relative test, which keeps the solver exactly as gain-invariant as
    # ZNSSD itself; raise it to reject subsets that are technically textured
    # but too faint to be worth correlating.
    min_contrast: float = 0.0
    max_hessian_cond: float = 1e10  # spec §2.6: cond(H) above this is singular

    def __post_init__(self) -> None:
        if self.subset_radius < 2:
            raise ValueError("subset_radius must be >= 2")
        if self.step < 1:
            raise ValueError("step must be >= 1")
        if self.max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        if self.search_radius < 0:
            raise ValueError("search_radius must be >= 0")
        if not math.isfinite(self.conv_tol) or self.conv_tol <= 0.0:
            raise ValueError("conv_tol must be finite and > 0")
        if not -1.0 <= self.zncc_min <= 1.0:
            raise ValueError("zncc_min must lie in [-1, 1]")
        if not math.isfinite(self.max_disp) or self.max_disp <= 0.0:
            raise ValueError("max_disp must be finite and > 0")
        if not math.isfinite(self.hessian_reg) or self.hessian_reg < 0.0:
            raise ValueError("hessian_reg must be finite and >= 0")
        if not math.isfinite(self.image_noise_sigma) or self.image_noise_sigma < 0.0:
            raise ValueError("image_noise_sigma must be finite and >= 0")
        if not math.isfinite(self.min_contrast) or self.min_contrast < 0.0:
            raise ValueError("min_contrast must be finite and >= 0")
        if self.max_hessian_cond <= 1.0:
            raise ValueError("max_hessian_cond must be > 1")

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

    @property
    def n_points(self) -> int:
        return int(self.p.shape[0])

    def masked(self, field_name: str) -> np.ndarray:
        """A copy of ``field_name`` with non-converged points set to NaN."""
        if field_name not in _MASKABLE_FIELDS:
            raise ValueError(
                f"cannot mask {field_name!r}; expected one of "
                + ", ".join(sorted(_MASKABLE_FIELDS))
            )
        values = np.asarray(getattr(self, field_name), dtype=np.float64).copy()
        values[~self.valid] = np.nan
        return values

    def status_counts(self) -> dict[Status, int]:
        """Histogram of outcomes, for the per-point diagnostics of spec §1.5."""
        return {
            status: int(np.count_nonzero(self.status == int(status)))
            for status in Status
            if np.any(self.status == int(status))
        }


_MASKABLE_FIELDS = frozenset({"x", "y", "p", "u", "v", "zncc", "iterations"})


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def _as_image(image: np.ndarray, name: str) -> np.ndarray:
    """Validate and convert a greyscale image to a finite ``float64`` array."""
    array = np.asarray(image, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"{name} must be 2-D, got {array.ndim}-D")
    if array.size == 0:
        raise ValueError(f"{name} must be non-empty, got shape {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(
            f"{name} contains non-finite pixels; the B-spline prefilter is an "
            "IIR recursion and would spread them across whole rows/columns"
        )
    return array


def _contrast_scale(image: np.ndarray) -> float:
    """Grey-level contrast of a whole image, as the yardstick for flatness.

    The standard deviation is used rather than the mean level because it is
    the part of the image that survives the affine grey change ``g = a f + b``
    the way a subset's contrast does: both scale by ``a`` and neither moves
    with ``b``, so the ratio the flatness test forms is invariant.
    """
    return float(np.std(image))


def _is_flat(norm: float, count: int, scale: float, min_contrast: float) -> bool:
    """True when a zero-mean subset norm is resampling residue, not texture.

    ``scale`` is the parent image's contrast from :func:`_contrast_scale`. It
    deliberately is *not* the subset's own level: a crushed-black or saturated
    patch has almost no level of its own, so measured against itself the
    prefilter's leaked tail would look like full-scale texture.
    """
    if scale <= 0.0:
        # An image with no contrast anywhere has no textured subset; what the
        # interpolator returns for one is round-off in the basis weights.
        return True
    rms_contrast = norm / math.sqrt(count)
    return rms_contrast <= max(min_contrast, _CONTRAST_REL_EPS * scale)


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
        image = _as_image(image, "image")
        self.height, self.width = image.shape
        coefficients = _prefilter_axis(image, axis=0)
        self.coefficients = _prefilter_axis(coefficients, axis=1)

    def __call__(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return self.sample(x, y)

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        x, y = np.broadcast_arrays(
            np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        )
        if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
            raise ValueError("sample coordinates must be finite")
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
    to one-sided differences at the very edge. An axis of length 1 carries no
    difference at all and yields exact zeros along that axis.
    """
    image = _as_image(image, "image")

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
    if len(tuple(shape)) != 2:
        raise ValueError("shape must be (height, width)")
    height, width = (int(value) for value in shape)
    if height < 1 or width < 1:
        raise ValueError(f"shape must be positive, got ({height}, {width})")
    if margin is None:
        margin = params.subset_radius + params.search_radius + 2
    margin = int(margin)
    if margin < 0:
        raise ValueError("margin must be >= 0")
    if 2 * margin >= min(height, width):
        raise ValueError(
            f"image too small for the requested subset/margin: {height}x{width} "
            f"image needs more than {2 * margin} px for margin {margin}"
        )
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
    min_contrast: float = 0.0,
    contrast_scale: float | None = None,
) -> tuple[float, float, float]:
    """Integer-pixel ``(u, v, zncc)`` for one point by FFT cross-correlation.

    The reference subset is zero-meaned and correlated against a search window
    of the target; the local target mean and norm needed to turn the raw
    correlation into a true ZNCC come from summed-area tables, so the whole
    map costs ``O(M^2 log M)`` rather than ``O(M^2 N)``.

    Returns ``(0.0, 0.0, -1.0)`` when no candidate is usable -- the window
    leaves the image, or either patch is flat -- so a ``zncc`` of ``-1``
    always means "no integer guess", never "guess of zero".

    ``contrast_scale`` is the grey-level yardstick for that flatness test; it
    is recomputed from the images when omitted, so callers in a per-point
    loop should pass the value in.
    """
    reference = _as_image(reference, "reference")
    target = _as_image(target, "target")
    radius = int(radius)
    search_radius = int(search_radius)
    if radius < 1:
        raise ValueError("radius must be >= 1")
    if search_radius < 0:
        raise ValueError("search_radius must be >= 0")
    if not (math.isfinite(point[0]) and math.isfinite(point[1])):
        raise ValueError("point must be finite")
    if contrast_scale is None:
        contrast_scale = max(_contrast_scale(reference), _contrast_scale(target))
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
    if _is_flat(ref_norm, subset.size, contrast_scale, min_contrast):
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

    # Same flatness test as the solver, applied per candidate: a window of
    # constant grey has a norm made of round-off, and dividing by it would
    # manufacture a correlation peak out of nothing.
    flat = window_norm / math.sqrt(count) <= max(
        min_contrast, _CONTRAST_REL_EPS * contrast_scale
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        zncc_map = correlation / (ref_norm * window_norm)
    zncc_map[flat | ~np.isfinite(zncc_map)] = -1.0

    peak = int(np.argmax(zncc_map))
    dy, dx = np.unravel_index(peak, zncc_map.shape)
    best = float(zncc_map[dy, dx])
    if best <= -1.0:
        return 0.0, 0.0, -1.0
    return float(dx - search_radius), float(dy - search_radius), best


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


def _as_warp_params(p: np.ndarray, name: str = "p") -> np.ndarray:
    array = np.asarray(p, dtype=np.float64).reshape(-1)
    if array.size != 6:
        raise ValueError(f"{name} must have 6 elements, got {array.size}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite")
    return array


def warp_matrix(p: np.ndarray) -> np.ndarray:
    """Homogeneous 3x3 warp for ``p = (u, u_x, u_y, v, v_x, v_y)``."""
    u, ux, uy, v, vx, vy = _as_warp_params(p)
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
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise ValueError(f"matrix must be 3x3, got {matrix.shape}")
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
    """The inverse-compositional update ``W(p) <- W(p) . W(dp)^-1``.

    The 2x2 affine block is inverted in closed form rather than through
    :func:`numpy.linalg.inv`, and the singularity test is relative to the
    block's magnitude, so a large-but-invertible increment is not rejected
    while a tiny-but-singular one still is.
    """
    du, dux, duy, dv, dvx, dvy = _as_warp_params(dp, "dp")
    u, ux, uy, v, vx, vy = _as_warp_params(p, "p")

    a00, a01 = 1.0 + dux, duy
    a10, a11 = dvx, 1.0 + dvy
    determinant = a00 * a11 - a01 * a10
    magnitude = max(abs(a00), abs(a01), abs(a10), abs(a11), 1.0)
    if abs(determinant) <= 1e-12 * magnitude * magnitude:
        raise np.linalg.LinAlgError("degenerate warp increment")

    # inv(A_dp) and inv(A_dp) @ (-t_dp)
    i00, i01 = a11 / determinant, -a01 / determinant
    i10, i11 = -a10 / determinant, a00 / determinant
    tx = -(i00 * du + i01 * dv)
    ty = -(i10 * du + i11 * dv)

    b00, b01 = 1.0 + ux, uy
    b10, b11 = vx, 1.0 + vy
    return np.array(
        [
            b00 * tx + b01 * ty + u,
            b00 * i00 + b01 * i10 - 1.0,
            b00 * i01 + b01 * i11,
            b10 * tx + b11 * ty + v,
            b10 * i00 + b11 * i10,
            b10 * i01 + b11 * i11 - 1.0,
        ],
        dtype=np.float64,
    )


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

    An empty ``points`` array is a valid AOI and returns empty result arrays
    of the right shapes and dtypes rather than raising.
    """
    params = params or ICGNParams()
    reference = _as_image(reference, "reference")
    target = _as_image(target, "target")
    if reference.shape != target.shape:
        raise ValueError(
            f"reference and target must have the same shape, got "
            f"{reference.shape} and {target.shape}"
        )

    if points is None:
        points = make_grid(reference.shape, params)
    points = _as_points(points)
    n_points = points.shape[0]
    if n_points == 0:
        return _empty_result(params)

    radius = params.subset_radius
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    dx, dy = np.meshgrid(offsets, offsets)
    dx = dx.ravel()
    dy = dy.ravel()

    ref_scale = _contrast_scale(reference)
    tgt_scale = _contrast_scale(target)

    ref_interp = BSplineInterpolator(reference)
    tgt_interp = BSplineInterpolator(target)
    grad_x, grad_y = reference_gradients(reference)
    gx_interp = BSplineInterpolator(grad_x)
    gy_interp = BSplineInterpolator(grad_y)

    seeds, seed_ok = _resolve_initial_guess(
        reference,
        target,
        points,
        params,
        initial_guess,
        n_points,
        max(ref_scale, tgt_scale),
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

        if not seed_ok[index]:
            status_out[index] = int(Status.NO_INITIAL_GUESS)
            continue

        f = ref_interp.sample(sample_x, sample_y)
        f_mean = f.mean()
        f_centred = f - f_mean
        f_norm = math.sqrt(float(np.dot(f_centred, f_centred)))
        if _is_flat(f_norm, f.size, ref_scale, params.min_contrast):
            status_out[index] = int(Status.SINGULAR_HESSIAN)
            continue

        fx = gx_interp.sample(sample_x, sample_y)
        fy = gy_interp.sample(sample_x, sample_y)
        # Steepest-descent images: grad f . dW/dp, evaluated at p = 0.
        jacobian = np.column_stack((fx, fx * dx, fx * dy, fy, fy * dx, fy * dy))

        hessian_raw = jacobian.T @ jacobian
        # Conditioning is judged on the scaled Hessian (spec §2.6): the raw
        # gradient columns differ by a factor of r between the displacement
        # and the displacement-gradient terms, so cond(H_raw) measures the
        # parameterisation as much as the subset. A subset textured in one
        # direction only (stripes, a ramp) is genuinely rank-deficient and
        # must be rejected rather than rescued by the diagonal loading.
        if not _well_conditioned(hessian_raw, radius, params.max_hessian_cond):
            status_out[index] = int(Status.SINGULAR_HESSIAN)
            continue

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
            if _is_flat(g_norm, g.size, tgt_scale, params.min_contrast):
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
                if _is_flat(g_norm, g.size, tgt_scale, params.min_contrast):
                    status = int(Status.SINGULAR_HESSIAN)
                    zncc = -1.0
                else:
                    zncc = float(np.dot(f_centred, g_centred) / (f_norm * g_norm))
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


def _as_points(points: np.ndarray) -> np.ndarray:
    """Validate a POI list, accepting an empty AOI in any of its spellings."""
    array = np.asarray(points, dtype=np.float64)
    if array.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    array = np.atleast_2d(array)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(
            f"points must be an (n, 2) array of (x, y), got shape {array.shape}"
        )
    if not np.all(np.isfinite(array)):
        raise ValueError("points must be finite")
    return array


def _empty_result(params: ICGNParams) -> ICGNResult:
    """Result for an empty AOI: right shapes, right dtypes, no points."""
    return ICGNResult(
        x=np.zeros(0, dtype=np.float64),
        y=np.zeros(0, dtype=np.float64),
        p=np.zeros((0, 6), dtype=np.float64),
        zncc=np.zeros(0, dtype=np.float64),
        iterations=np.zeros(0, dtype=np.int32),
        status=np.zeros(0, dtype=np.int32),
        covariance=(
            np.zeros((0, 6, 6), dtype=np.float64)
            if params.compute_covariance
            else None
        ),
    )


def _well_conditioned(hessian_raw: np.ndarray, radius: int, max_cond: float) -> bool:
    """``cond(S H S) <= max_cond`` with ``S = diag(1, r, r, 1, r, r)``.

    The scaling puts every parameter in "pixels of motion at the subset edge",
    which is the same normalisation the convergence test uses, so the
    condition number describes the subset rather than the units.
    """
    scale = np.array([1.0, radius, radius, 1.0, radius, radius], dtype=np.float64)
    scaled = hessian_raw * scale[:, None] * scale[None, :]
    eigenvalues = np.linalg.eigvalsh(scaled)
    largest = float(eigenvalues[-1])
    smallest = float(eigenvalues[0])
    if not math.isfinite(largest) or largest <= 0.0:
        return False
    return smallest > 0.0 and largest / smallest <= max_cond


def _resolve_initial_guess(
    reference: np.ndarray,
    target: np.ndarray,
    points: np.ndarray,
    params: ICGNParams,
    initial_guess: np.ndarray | None,
    n_points: int,
    contrast_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Seeds plus a per-point flag saying whether a seed could be produced.

    A requested FFT-CC search that cannot run -- window off the image, flat
    patch -- yields ``False``: seeding such a point at zero would hand back a
    confident answer to a question that was never asked (``NO_INITIAL_GUESS``
    in the spec §2.6 failure table).
    """
    seeds = np.zeros((n_points, 6), dtype=np.float64)
    seed_ok = np.ones(n_points, dtype=bool)
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
            raise ValueError(
                f"initial_guess must have shape ({n_points}, 2) or "
                f"({n_points}, 6), got {guess.shape}"
            )
        if not np.all(np.isfinite(seeds)):
            raise ValueError("initial_guess must be finite")
        return seeds, seed_ok

    if params.search_radius > 0:
        for index in range(n_points):
            u0, v0, zncc = integer_search_fftcc(
                reference,
                target,
                (points[index, 0], points[index, 1]),
                params.subset_radius,
                params.search_radius,
                params.min_contrast,
                contrast_scale,
            )
            if zncc <= -1.0:
                seed_ok[index] = False
                continue
            seeds[index, 0] = u0
            seeds[index, 3] = v0
    return seeds, seed_ok
