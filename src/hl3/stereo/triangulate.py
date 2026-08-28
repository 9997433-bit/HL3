"""Stereo / multi-view triangulation from projection matrices.

Lightweight reference implementation of the HL3-3D stereo pipeline (spec
``.agent_workspace/round1/R1-O2-hl3-3d-spec.md``, sections 6.1--6.6). NumPy only,
double precision, fully vectorised over points.

Scope of this prototype
-----------------------
Implemented:

* pinhole projection matrices ``P = K [R | t]`` and forward projection;
* the fundamental matrix derived analytically from two projection matrices
  (spec S4.3: never estimated with the eight-point algorithm);
* epipolar quality metrics (one-way, symmetric, Sampson);
* the four triangulation rungs of spec S6.1 -- midpoint, linear DLT, iterated
  Sampson correction (the practical stand-in for Hartley--Sturm), and non-linear
  reprojection minimisation;
* first-order propagation of image-plane noise into a per-point 3x3 position
  covariance (spec S6.6, match term only), and the cheirality + covariance
  quality gate built on top of it.

Deliberately *not* implemented here, and tracked as later work:

* lens distortion of any kind. The prototype is a pure L0 pinhole model. The
  Brown--Conrady / rational / thin-prism layers (spec S4.1 L1--L5) and the
  distorted epipolar-curve sampling of spec S6.3 come with the calibration
  module proper.
* the non-parametric distortion field for stereo microscopy (spec S4.1 L6).
  That layer stays out of every branch until the written patent-clearance
  opinion required by spec S10.4 exists. This paragraph is a scope exclusion,
  not a description of anything present in this file.
* the calibration covariance term ``Sigma_cal`` in spec S6.6. Only the match
  term is propagated here; calibration bootstrap covariance needs the real
  calibration solver.

Conventions
-----------
* World and camera coordinates are 3-vectors in millimetres, image coordinates
  are pixels, both stored row-wise as ``(N, 3)`` / ``(N, 2)`` float arrays.
* A camera maps world to camera coordinates as ``x_cam = R @ X_world + t``, so
  the camera centre is ``C = -R.T @ t`` and ``P = K @ [R | t]``.
* Multi-view helpers take ``Ps`` as a sequence of ``(3, 4)`` matrices and ``xs``
  as a matching sequence of ``(N, 2)`` pixel arrays, one entry per view.

Failure conventions
-------------------
The module distinguishes three kinds of bad input, and the distinction is
deliberate rather than incidental:

* **Broken calling code raises.** Wrong shapes, mismatched view counts,
  non-finite camera parameters, non-positive noise levels and geometrically
  degenerate camera configurations all raise :class:`ValueError`. These cannot
  be produced by measurement, only by a bug upstream, so failing loudly is the
  cheap option.
* **Missing measurements propagate.** A non-finite pixel coordinate means the
  correlator dropped that point, which is normal in any real field. Such points
  yield ``nan`` world coordinates and are excluded from the shared least-squares
  machinery instead of poisoning their neighbours or aborting the whole batch.
* **Degenerate geometry is reported, not hidden.** A point whose rays are too
  close to parallel to be located gets an infinite position covariance rather
  than a plausible-looking finite number, so that
  :func:`triangulation_quality_mask` can reject it.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "camera_center",
    "cheirality_mask",
    "epipolar_distance",
    "fundamental_from_projections",
    "position_sigma",
    "project",
    "project_with_depth",
    "projection_matrix",
    "reprojection_residuals",
    "reprojection_rmse",
    "sampson_correct",
    "sampson_distance",
    "triangulate_dlt",
    "triangulate_midpoint",
    "triangulate_multiview_dlt",
    "triangulate_nonlinear",
    "triangulate_optimal",
    "triangulation_covariance",
    "triangulation_quality_mask",
]

_TINY = np.finfo(float).tiny

# Relative floor below which a baseline, a determinant or a matrix eigenvalue
# counts as numerically zero. Double precision carries ~2.2e-16 of relative
# error, so 1e-12 leaves four decades of headroom above the noise while still
# sitting far below any physically meaningful configuration: a coincident
# camera pair scores ~5e-17 on the baseline test and a real 254 mm baseline
# scores ~4e-3, fourteen decades apart.
_REL_EPS = 1e-12


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


def _as_projection(P: np.ndarray, name: str = "P") -> np.ndarray:
    """Validate and return a ``(3, 4)`` float projection matrix.

    Camera parameters are configuration, never measurement, so a non-finite
    entry here is always an upstream bug and is rejected rather than propagated.
    """
    A = np.asarray(P, dtype=float)
    if A.size != 12:
        raise ValueError(
            f"{name} must be a 3x4 projection matrix, got shape {A.shape}"
        )
    A = A.reshape(3, 4)
    if not np.all(np.isfinite(A)):
        raise ValueError(f"{name} contains non-finite entries")
    return A


def _as_projections(Ps: Sequence[np.ndarray], name: str = "Ps") -> list[np.ndarray]:
    """Validate a sequence of projection matrices; at least one is required."""
    if isinstance(Ps, np.ndarray) and Ps.ndim == 2:
        raise ValueError(
            f"{name} must be a sequence of 3x4 matrices, not a single matrix"
        )
    out = [_as_projection(P, f"{name}[{i}]") for i, P in enumerate(Ps)]
    if not out:
        raise ValueError(f"{name} must contain at least one view")
    return out


def _as_pixels(x: np.ndarray, name: str = "x") -> np.ndarray:
    """Validate and return an ``(N, 2)`` float pixel array.

    Non-finite entries are *not* rejected: they are how a correlator reports a
    point it could not match, and they must survive to the output as ``nan``.
    """
    a = np.asarray(x, dtype=float)
    if a.ndim == 2 and a.shape[1] == 2:
        return a
    # Only a flat array is reshaped. Silently reinterpreting an (N, 3) array as
    # pixels whenever 3N happens to be even is how a swapped argument survives
    # to become a plausible-looking answer.
    if a.ndim != 1 or a.size % 2 != 0:
        raise ValueError(f"{name} must be an (N, 2) pixel array, got shape {a.shape}")
    return a.reshape(-1, 2)


def _as_points(X: np.ndarray, name: str = "X") -> np.ndarray:
    """Validate and return an ``(N, 3)`` float world-point array."""
    a = np.asarray(X, dtype=float)
    if a.ndim == 2 and a.shape[1] == 3:
        return a
    if a.ndim != 1 or a.size % 3 != 0:
        raise ValueError(f"{name} must be an (N, 3) point array, got shape {a.shape}")
    return a.reshape(-1, 3)


def _as_views(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], min_views: int = 2
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Validate matching sequences of projection matrices and pixel arrays."""
    Ps = _as_projections(Ps)
    xs = [_as_pixels(x, f"xs[{i}]") for i, x in enumerate(xs)]
    if len(Ps) != len(xs):
        raise ValueError(
            f"Ps and xs must have the same number of views, got {len(Ps)} and {len(xs)}"
        )
    if len(Ps) < min_views:
        raise ValueError(
            f"triangulation needs at least {min_views} views, got {len(Ps)}"
        )
    n = xs[0].shape[0]
    if any(x.shape[0] != n for x in xs):
        raise ValueError(
            "all views must supply the same number of points, got "
            f"{[x.shape[0] for x in xs]}"
        )
    return Ps, xs


def _observed_mask(xs: Sequence[np.ndarray]) -> np.ndarray:
    """Points whose pixel coordinates are finite in every view.

    Every estimator that pools points into one shared linear algebra call must
    filter on this first. A single dropped point otherwise turns the whole
    batch's SVD into ``LinAlgError: SVD did not converge``, i.e. one bad POI
    destroys the entire field.
    """
    ok = np.ones(xs[0].shape[0], dtype=bool)
    for x in xs:
        ok &= np.all(np.isfinite(x), axis=1)
    return ok


# --------------------------------------------------------------------------- #
# Cameras and projection
# --------------------------------------------------------------------------- #


def projection_matrix(K: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Assemble ``P = K [R | t]`` (3x4) from intrinsics and extrinsics."""
    K = np.asarray(K, dtype=float)
    R = np.asarray(R, dtype=float)
    t = np.asarray(t, dtype=float)
    if K.size != 9:
        raise ValueError(f"K must be 3x3, got shape {K.shape}")
    if R.size != 9:
        raise ValueError(f"R must be 3x3, got shape {R.shape}")
    if t.size != 3:
        raise ValueError(f"t must be a 3-vector, got shape {t.shape}")
    K, R, t = K.reshape(3, 3), R.reshape(3, 3), t.reshape(3)
    if not (np.all(np.isfinite(K)) and np.all(np.isfinite(R))
            and np.all(np.isfinite(t))):
        raise ValueError("K, R and t must all be finite")
    return K @ np.hstack([R, t[:, None]])


def camera_center(P: np.ndarray) -> np.ndarray:
    """Camera centre as the right null-space of ``P`` (3-vector, world frame)."""
    P = _as_projection(P)
    _, _, vt = np.linalg.svd(P)
    Ch = vt[-1]
    if abs(Ch[3]) < _REL_EPS:
        raise ValueError("degenerate projection matrix: camera centre at infinity")
    return Ch[:3] / Ch[3]


def project_with_depth(P: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project world points and also return the projective depth ``p3 . Xh``.

    Points on the camera's principal plane have zero depth and no image; they
    come back as ``nan`` rather than as a finite value produced by dividing by a
    denormal.
    """
    P = _as_projection(P)
    X = _as_points(X)
    w = X @ P[2, :3] + P[2, 3]
    safe = np.where(w == 0.0, np.nan, w)
    u = (X @ P[0, :3] + P[0, 3]) / safe
    v = (X @ P[1, :3] + P[1, 3]) / safe
    return np.column_stack([u, v]), w


def project(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Project world points ``(N, 3)`` to pixels ``(N, 2)``."""
    return project_with_depth(P, X)[0]


def _hom2(x: np.ndarray) -> np.ndarray:
    return np.hstack([x, np.ones((x.shape[0], 1))])


def _normalizer_2d(x: np.ndarray) -> np.ndarray:
    """Hartley isotropic normalising transform for one view's pixel coordinates.

    Triangulation is invariant under ``x -> T x`` combined with ``P -> T P``, so
    this only buys conditioning: with focal lengths of order 1e4 px the raw DLT
    design matrix mixes entries spanning several decades.

    ``x`` must already be restricted to observed points; a single ``nan`` in the
    centroid would otherwise scale every point in the view to ``nan``.
    """
    if x.shape[0] == 0:
        return np.eye(3)
    c = x.mean(axis=0)
    d = float(np.sqrt(((x - c) ** 2).sum(axis=1)).mean())
    s = np.sqrt(2.0) / d if d > _REL_EPS else 1.0
    return np.array([[s, 0.0, -s * c[0]], [0.0, s, -s * c[1]], [0.0, 0.0, 1.0]])


# --------------------------------------------------------------------------- #
# Epipolar geometry
# --------------------------------------------------------------------------- #


def fundamental_from_projections(P1: np.ndarray, P2: np.ndarray) -> np.ndarray:
    """Fundamental matrix with ``x2.T @ F @ x1 == 0``, from the two ``P`` matrices.

    Uses ``F = [e2]_x P2 P1^+`` with ``e2 = P2 C1``. Spec S4.3 requires F to be
    derived from the calibration rather than fitted from correspondences, so that
    the epipolar quality metrics measure the *match*, not a co-estimated geometry.

    Raises if the two camera centres coincide. That configuration has no
    epipolar geometry at all, but the unnormalised ``F`` it produces is merely
    tiny rather than exactly zero, so without this check the final normalisation
    would rescale pure rounding error into a unit-norm matrix that looks like a
    valid answer.
    """
    P1 = _as_projection(P1, "P1")
    P2 = _as_projection(P2, "P2")
    C1 = camera_center(P1)
    C1h = np.append(C1, 1.0)
    e2 = P2 @ C1h
    scale = np.linalg.norm(P2) * np.linalg.norm(C1h)
    if np.linalg.norm(e2) <= _REL_EPS * scale:
        raise ValueError(
            "degenerate stereo pair: the two camera centres coincide, so no "
            "epipolar geometry exists"
        )
    ex = np.array(
        [[0.0, -e2[2], e2[1]], [e2[2], 0.0, -e2[0]], [-e2[1], e2[0], 0.0]]
    )
    F = ex @ P2 @ np.linalg.pinv(P1)
    n = np.linalg.norm(F)
    if n <= _REL_EPS:
        raise ValueError("degenerate stereo pair: fundamental matrix vanished")
    return F / n


def _as_fundamental(F: np.ndarray) -> np.ndarray:
    A = np.asarray(F, dtype=float)
    if A.size != 9:
        raise ValueError(f"F must be a 3x3 matrix, got shape {A.shape}")
    A = A.reshape(3, 3)
    if not np.all(np.isfinite(A)):
        raise ValueError("F contains non-finite entries")
    if np.linalg.norm(A) <= _REL_EPS:
        raise ValueError("F is the zero matrix; it carries no epipolar geometry")
    return A


def _match_pair(x1: np.ndarray, x2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b = _as_pixels(x1, "x1"), _as_pixels(x2, "x2")
    if a.shape[0] != b.shape[0]:
        raise ValueError(
            f"x1 and x2 must have the same number of points, got "
            f"{a.shape[0]} and {b.shape[0]}"
        )
    return a, b


def _safe_divide(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """``num / den`` with a zero denominator reported as ``nan``, never as zero.

    Flooring the denominator at a denormal instead would turn "this metric is
    undefined" into "this metric is exactly zero", i.e. into a perfect score on
    a quality field whose whole job is to flag bad matches.
    """
    good = den > 0.0
    return np.where(good, num / np.where(good, den, 1.0), np.nan)


def epipolar_distance(
    F: np.ndarray, x1: np.ndarray, x2: np.ndarray, symmetric: bool = True
) -> np.ndarray:
    """Point-to-epipolar-line distance in pixels (spec S4.3).

    With ``symmetric=False`` this is the one-way distance of ``x2`` to the line
    ``F x1``; with ``symmetric=True`` it is the mean of both directions.
    """
    F = _as_fundamental(F)
    x1, x2 = _match_pair(x1, x2)
    x1h, x2h = _hom2(x1), _hom2(x2)
    l2 = x1h @ F.T
    num = np.abs(np.einsum("ij,ij->i", x2h, l2))
    d21 = _safe_divide(num, np.hypot(l2[:, 0], l2[:, 1]))
    if not symmetric:
        return d21
    l1 = x2h @ F
    d12 = _safe_divide(num, np.hypot(l1[:, 0], l1[:, 1]))
    return 0.5 * (d21 + d12)


def sampson_distance(F: np.ndarray, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """Sampson distance in pixels (spec S4.3, default POI-level quality field)."""
    F = _as_fundamental(F)
    x1, x2 = _match_pair(x1, x2)
    x1h, x2h = _hom2(x1), _hom2(x2)
    Fx1 = x1h @ F.T
    Ftx2 = x2h @ F
    eps = np.einsum("ij,ij->i", x2h, Fx1)
    den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
    return _safe_divide(np.abs(eps), np.sqrt(den))


def sampson_correct(
    F: np.ndarray,
    x1: np.ndarray,
    x2: np.ndarray,
    iters: int = 10,
    tol: float = 1e-12,
) -> tuple[np.ndarray, np.ndarray]:
    """Move ``x1, x2`` onto corresponding epipolar lines with minimal L2 shift.

    One Sampson step is the first-order optimal correction; iterating it converges
    to the Hartley--Sturm optimum without the degree-six polynomial root finding,
    which is what spec S6.1 calls the "iterative Sampson correction" rung.
    After convergence the two rays intersect exactly, so a subsequent DLT is the
    exact L2-optimal triangulation of the corrected pair.

    Iteration stops early once the largest per-point shift falls below ``tol``
    pixels. Convergence is quadratic in practice, so the default ``iters=10``
    is a safety ceiling rather than the expected cost.
    """
    F = _as_fundamental(F)
    a, b = _match_pair(x1, x2)
    a, b = a.copy(), b.copy()
    iters = int(iters)
    if iters < 0:
        raise ValueError(f"iters must be non-negative, got {iters}")
    if not tol >= 0.0:
        raise ValueError(f"tol must be non-negative, got {tol}")

    for _ in range(iters):
        ah, bh = _hom2(a), _hom2(b)
        Fx1 = ah @ F.T
        Ftx2 = bh @ F
        eps = np.einsum("ij,ij->i", bh, Fx1)
        den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
        k = np.divide(eps, den, out=np.zeros_like(eps), where=den > 0.0)
        da = k[:, None] * Ftx2[:, :2]
        db = k[:, None] * Fx1[:, :2]
        a = a - da
        b = b - db
        step = max(_finite_max(np.abs(da)), _finite_max(np.abs(db)))
        if step <= tol:
            break
    return a, b


def _finite_max(a: np.ndarray) -> float:
    """Largest finite entry, or 0.0 when there is none. Never warns."""
    finite = a[np.isfinite(a)]
    return float(finite.max()) if finite.size else 0.0


# --------------------------------------------------------------------------- #
# Triangulation
# --------------------------------------------------------------------------- #


def triangulate_multiview_dlt(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], normalize: bool = True
) -> np.ndarray:
    """Linear DLT triangulation from two or more views.

    Each view contributes the two rows ``u * p3 - p1`` and ``v * p3 - p2``; the
    homogeneous world point is the right singular vector of the stacked design
    matrix belonging to the smallest singular value.

    Points that are not finite in every view, and points whose homogeneous
    solution lies on the plane at infinity, come back as ``nan``.
    """
    Ps, xs = _as_views(Ps, xs)
    n = xs[0].shape[0]
    out = np.full((n, 3), np.nan)
    if n == 0:
        return out

    ok = _observed_mask(xs)
    if not ok.any():
        return out
    xs = [x[ok] for x in xs]

    rows = []
    for P, x in zip(Ps, xs, strict=True):
        if normalize:
            T = _normalizer_2d(x)
            Pn = T @ P
            xn = (_hom2(x) @ T.T)[:, :2]
        else:
            Pn, xn = P, x
        rows.append(xn[:, 0:1] * Pn[2][None, :] - Pn[0][None, :])
        rows.append(xn[:, 1:2] * Pn[2][None, :] - Pn[1][None, :])

    A = np.stack(rows, axis=1)
    A = A / np.maximum(np.linalg.norm(A, axis=2, keepdims=True), _TINY)
    _, _, vt = np.linalg.svd(A)
    Xh = vt[:, -1, :]
    w = Xh[:, 3]
    w = np.where(np.abs(w) < _REL_EPS, np.nan, w)
    out[ok] = Xh[:, :3] / w[:, None]
    return out


def triangulate_dlt(
    P1: np.ndarray,
    P2: np.ndarray,
    x1: np.ndarray,
    x2: np.ndarray,
    normalize: bool = True,
) -> np.ndarray:
    """Two-view linear DLT triangulation."""
    return triangulate_multiview_dlt([P1, P2], [x1, x2], normalize=normalize)


def _ray_directions(P: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Unit world-frame viewing rays, oriented towards increasing depth."""
    P = _as_projection(P)
    x = _as_pixels(x)
    M = P[:, :3]
    try:
        d = np.linalg.solve(M, _hom2(x).T).T
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "degenerate projection matrix: the leading 3x3 block is singular, "
            "so viewing rays are undefined"
        ) from exc
    d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), _TINY)
    flip = (d @ P[2, :3]) < 0
    d[flip] *= -1.0
    return d


def triangulate_midpoint(
    P1: np.ndarray, P2: np.ndarray, x1: np.ndarray, x2: np.ndarray
) -> np.ndarray:
    """Midpoint of the common perpendicular of the two viewing rays.

    Fast and distortion-free but not optimal in any image-plane sense; kept as
    the cheap initialiser of spec S6.1 and as an independent cross-check of DLT.
    Near-parallel ray pairs come back as ``nan``.
    """
    P1 = _as_projection(P1, "P1")
    P2 = _as_projection(P2, "P2")
    x1, x2 = _match_pair(x1, x2)
    C1 = camera_center(P1)
    C2 = camera_center(P2)
    d1 = _ray_directions(P1, x1)
    d2 = _ray_directions(P2, x2)
    e = C1 - C2
    c = np.einsum("ij,ij->i", d1, d2)
    b1 = -(d1 @ e)
    b2 = d2 @ e
    det = 1.0 - c**2
    det = np.where(np.abs(det) < _REL_EPS, np.nan, det)
    s = (b1 + c * b2) / det
    u = (c * b1 + b2) / det
    return 0.5 * ((C1 + s[:, None] * d1) + (C2 + u[:, None] * d2))


def triangulate_optimal(
    P1: np.ndarray,
    P2: np.ndarray,
    x1: np.ndarray,
    x2: np.ndarray,
    iters: int = 10,
) -> np.ndarray:
    """L2-optimal two-view triangulation via iterated Sampson correction + DLT."""
    F = fundamental_from_projections(P1, P2)
    a, b = sampson_correct(F, x1, x2, iters=iters)
    return triangulate_dlt(P1, P2, a, b)


def _projection_jacobian(
    P: np.ndarray, X: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(uv, dU/dX, dV/dX)`` for one view; jacobians are ``(N, 3)``."""
    w = X @ P[2, :3] + P[2, 3]
    w = np.where(w == 0.0, np.nan, w)
    u = (X @ P[0, :3] + P[0, 3]) / w
    v = (X @ P[1, :3] + P[1, 3]) / w
    inv_w = (1.0 / w)[:, None]
    Ju = (P[0, :3][None, :] - u[:, None] * P[2, :3][None, :]) * inv_w
    Jv = (P[1, :3][None, :] - v[:, None] * P[2, :3][None, :]) * inv_w
    return np.column_stack([u, v]), Ju, Jv


def _normal_equations(
    Ps: Sequence[np.ndarray],
    xs: Sequence[np.ndarray],
    X: np.ndarray,
    weights: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = X.shape[0]
    JtJ = np.zeros((n, 3, 3))
    Jtr = np.zeros((n, 3))
    cost = np.zeros(n)
    for i, (P, x) in enumerate(zip(Ps, xs, strict=True)):
        w = 1.0 if weights is None else float(weights[i])
        uv, Ju, Jv = _projection_jacobian(P, X)
        r = uv - x
        JtJ += w * (
            Ju[:, :, None] * Ju[:, None, :] + Jv[:, :, None] * Jv[:, None, :]
        )
        Jtr += w * (Ju * r[:, 0:1] + Jv * r[:, 1:2])
        cost += w * (r[:, 0] ** 2 + r[:, 1] ** 2)
    return JtJ, Jtr, cost


def _as_weights(weights: Sequence[float] | None, n_views: int) -> np.ndarray | None:
    if weights is None:
        return None
    w = np.asarray(weights, dtype=float).reshape(-1)
    if w.size != n_views:
        raise ValueError(
            f"weights must supply one value per view, got {w.size} for {n_views} views"
        )
    if not np.all(np.isfinite(w)) or np.any(w < 0.0):
        raise ValueError("weights must be finite and non-negative")
    if not np.any(w > 0.0):
        raise ValueError("at least one view weight must be positive")
    return w


def triangulate_nonlinear(
    Ps: Sequence[np.ndarray],
    xs: Sequence[np.ndarray],
    X0: np.ndarray | None = None,
    iters: int = 20,
    tol: float = 1e-12,
    weights: Sequence[float] | None = None,
) -> np.ndarray:
    """Minimise the sum of squared reprojection residuals over all views.

    Gauss--Newton with per-point step halving, initialised from the DLT solution.
    This is the default high-accuracy rung of spec S6.1 and the only one that
    generalises cleanly to three or more cameras with per-view weights (used by
    the multi-system overlap regions of spec S9).

    ``weights[i]`` is an isotropic weight for view ``i``, nominally
    ``1 / sigma_i**2`` in inverse squared pixels.

    Points that are unobserved in any view, or whose supplied initial guess is
    non-finite, are dropped before the solve and returned as ``nan``.
    """
    Ps, xs = _as_views(Ps, xs)
    weights = _as_weights(weights, len(Ps))
    iters = int(iters)
    if iters < 0:
        raise ValueError(f"iters must be non-negative, got {iters}")
    if not tol >= 0.0:
        raise ValueError(f"tol must be non-negative, got {tol}")

    n = xs[0].shape[0]
    if X0 is None:
        X_full = triangulate_multiview_dlt(Ps, xs)
    else:
        X_full = _as_points(X0, "X0").copy()
        if X_full.shape[0] != n:
            raise ValueError(
                f"X0 must supply one point per observation, got "
                f"{X_full.shape[0]} for {n} points"
            )

    # Gauss--Newton pools all points into batched 3x3 solves, and NumPy raises
    # for the whole batch if any single matrix is exactly singular. Restricting
    # to observed points with a finite starting estimate keeps one dead POI from
    # taking the field down with it.
    ok = _observed_mask(xs) & np.all(np.isfinite(X_full), axis=1)
    out = np.full((n, 3), np.nan)
    if not ok.any():
        return out
    xs = [x[ok] for x in xs]
    X = X_full[ok]

    _, _, cost = _normal_equations(Ps, xs, X, weights)

    for _ in range(iters):
        JtJ, Jtr, _ = _normal_equations(Ps, xs, X, weights)
        # Relative Levenberg damping keeps rank-deficient points (near-parallel
        # rays) from producing an unusable step instead of raising.
        trace = np.trace(JtJ, axis1=1, axis2=2)
        damp = np.where(trace > 0.0, _REL_EPS * trace, _REL_EPS)
        JtJ = JtJ + damp[:, None, None] * np.eye(3)[None, :, :]
        try:
            step = -np.linalg.solve(JtJ, Jtr[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            break

        scale = np.ones(X.shape[0])
        X_new = X + step
        _, _, cost_new = _normal_equations(Ps, xs, X_new, weights)
        for _ in range(5):
            worse = cost_new > cost
            if not np.any(worse):
                break
            scale = np.where(worse, scale * 0.5, scale)
            X_new = X + scale[:, None] * step
            _, _, cost_new = _normal_equations(Ps, xs, X_new, weights)

        improved = cost_new <= cost
        delta = _finite_max(np.abs(np.where(improved[:, None], X_new - X, 0.0)))
        X = np.where(improved[:, None], X_new, X)
        cost = np.where(improved, cost_new, cost)
        if delta <= tol:
            break

    out[ok] = X
    return out


# --------------------------------------------------------------------------- #
# Quality metrics and uncertainty
# --------------------------------------------------------------------------- #


def reprojection_residuals(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], X: np.ndarray
) -> np.ndarray:
    """Per-view reprojection residuals in pixels, shape ``(n_views, N, 2)``."""
    Ps, xs = _as_views(Ps, xs, min_views=1)
    X = _as_points(X)
    if X.shape[0] != xs[0].shape[0]:
        raise ValueError(
            f"X must supply one point per observation, got "
            f"{X.shape[0]} for {xs[0].shape[0]} points"
        )
    return np.stack([project(P, X) - x for P, x in zip(Ps, xs, strict=True)])


def reprojection_rmse(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], X: np.ndarray
) -> float:
    """Root-mean-square reprojection error in pixels over all views and points.

    Unobserved points are excluded rather than turning the whole figure into
    ``nan``; an all-``nan`` input yields ``nan``.
    """
    r = reprojection_residuals(Ps, xs, X)
    finite = r[np.isfinite(r)]
    if finite.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(finite**2) * 2.0))


def cheirality_mask(Ps: Sequence[np.ndarray], X: np.ndarray) -> np.ndarray:
    """Boolean mask of points lying in front of every camera.

    The cheapest half of the quality gate of spec S5.1 stage D. It catches sign
    inversions and rays that cross behind a camera, but *not* the far-field
    degeneracy where near-parallel rays admit a low-residual solution near
    infinity -- for that, gate on :func:`triangulation_covariance` as well, or
    use :func:`triangulation_quality_mask`, which combines the two.

    An empty ``Ps`` raises rather than passing every point: this is a safety
    gate, and a gate with no cameras to check against must fail closed.
    """
    Ps = _as_projections(Ps)
    X = _as_points(X)
    ok = np.ones(X.shape[0], dtype=bool)
    for P in Ps:
        with np.errstate(invalid="ignore"):
            ok &= (X @ P[2, :3] + P[2, 3]) > 0
    return ok


def _as_sigma_px(sigma_px: float | Sequence[float], n_views: int) -> np.ndarray:
    s = np.asarray(sigma_px, dtype=float).reshape(-1)
    if s.size == 1:
        s = np.repeat(s, n_views)
    if s.size != n_views:
        raise ValueError(
            f"sigma_px must be a scalar or one value per view, got {s.size} "
            f"for {n_views} views"
        )
    if not np.all(np.isfinite(s)) or np.any(s <= 0.0):
        raise ValueError("sigma_px must be finite and strictly positive")
    return s


def triangulation_covariance(
    Ps: Sequence[np.ndarray],
    X: np.ndarray,
    sigma_px: float | Sequence[float] = 1.0,
) -> np.ndarray:
    """First-order 3x3 position covariance per point, shape ``(N, 3, 3)``.

    Implements the match term of spec S6.6: with ``J`` the stacked jacobian of all
    view projections with respect to ``X`` and isotropic image noise of standard
    deviation ``sigma_i`` in view ``i``, the propagated covariance is
    ``(sum_i J_i.T J_i / sigma_i**2)^-1``.

    The calibration term ``Sigma_cal`` is *not* included; these numbers are the
    covariance conditional on exactly known camera parameters and therefore a
    lower bound on the deliverable per-point uncertainty.

    Rank-deficient points -- a single view, or two views whose rays are parallel
    to working precision -- have no finite covariance and are returned as
    ``inf`` instead of aborting the batch. Non-finite input points come back as
    ``nan``. Both fail every threshold in
    :func:`triangulation_quality_mask`, which is the intended behaviour: the
    covariance is the only quantity that catches the far-field degeneracy, so it
    must never report a plausible finite number for a point it cannot locate.
    """
    Ps = _as_projections(Ps)
    X = _as_points(X)
    sig = _as_sigma_px(sigma_px, len(Ps))

    n = X.shape[0]
    out = np.full((n, 3, 3), np.nan)
    finite = np.all(np.isfinite(X), axis=1)
    if not finite.any():
        return out

    Xf = X[finite]
    JtJ = np.zeros((Xf.shape[0], 3, 3))
    for P, s in zip(Ps, sig, strict=True):
        _, Ju, Jv = _projection_jacobian(P, Xf)
        w = 1.0 / float(s) ** 2
        JtJ += w * (Ju[:, :, None] * Ju[:, None, :] + Jv[:, :, None] * Jv[:, None, :])

    # JtJ is symmetric positive semi-definite by construction, so its smallest
    # eigenvalue relative to its largest is the natural rank test, and eigvalsh
    # is batched. A point on a principal plane makes JtJ non-finite, which
    # eigvalsh rejects for the whole batch, so screen those out first.
    good = np.all(np.isfinite(JtJ), axis=(1, 2))
    block = np.full((Xf.shape[0], 3, 3), np.inf)
    if good.any():
        lam = np.linalg.eigvalsh(JtJ[good])
        invertible = lam[:, 0] > _REL_EPS * np.maximum(lam[:, 2], _TINY)
        idx = np.flatnonzero(good)[invertible]
        if idx.size:
            block[idx] = np.linalg.inv(JtJ[idx])
    out[finite] = block
    return out


def position_sigma(Sigma: np.ndarray) -> np.ndarray:
    """Scalar position uncertainty ``sqrt(trace(Sigma))`` in mm, shape ``(N,)``.

    The trace is the total variance summed over the three axes, so its square
    root is the RMS radial position error. It is the single number the quality
    gate of spec S5.1 stage D thresholds on.
    """
    S = np.asarray(Sigma, dtype=float)
    if S.ndim != 3 or S.shape[1:] != (3, 3):
        raise ValueError(f"Sigma must have shape (N, 3, 3), got {S.shape}")
    return np.sqrt(np.trace(S, axis1=1, axis2=2))


def triangulation_quality_mask(
    Ps: Sequence[np.ndarray],
    X: np.ndarray,
    sigma_px: float | Sequence[float] = 1.0,
    max_position_sigma_mm: float = float("inf"),
) -> np.ndarray:
    """Points that are finite, in front of every camera, and locatable.

    The full stage-D gate of spec S5.1, in the order that matters:

    1. the point is finite -- the correlator produced a match and the
       triangulator converged;
    2. cheirality -- it lies in front of every camera;
    3. its predicted position uncertainty is below
       ``max_position_sigma_mm``.

    Step 3 is the one that cannot be replaced by a reprojection-residual
    threshold. Two near-parallel corrupted rays admit a genuine low-residual
    minimum out near infinity, so residual and Sampson distance both look
    excellent there; only the covariance blows up. Leaving
    ``max_position_sigma_mm`` at its default of infinity keeps steps 1 and 2
    only, which is a strictly weaker gate.
    """
    Ps = _as_projections(Ps)
    X = _as_points(X)
    if not max_position_sigma_mm > 0.0:
        raise ValueError(
            f"max_position_sigma_mm must be positive, got {max_position_sigma_mm}"
        )

    keep = np.all(np.isfinite(X), axis=1)
    if keep.any():
        keep[keep] = cheirality_mask(Ps, X[keep])
    if np.isfinite(max_position_sigma_mm) and keep.any():
        idx = np.flatnonzero(keep)
        sig = position_sigma(triangulation_covariance(Ps, X[idx], sigma_px=sigma_px))
        with np.errstate(invalid="ignore"):
            keep[idx] = sig < max_position_sigma_mm
    return keep
