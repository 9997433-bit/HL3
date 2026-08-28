"""Stereo / multi-view triangulation from projection matrices.

Round 2 lightweight prototype for the HL3-3D stereo pipeline (spec
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
  covariance (spec S6.6, match term only).

Deliberately *not* implemented here, and tracked as later work:

* lens distortion of any kind. The prototype is a pure L0 pinhole model. The
  Brown--Conrady / rational / thin-prism layers (spec S4.1 L1--L5) and the
  distorted epipolar-curve sampling of spec S6.3 come with the calibration
  module proper.
* the non-parametric distortion field for stereo microscopy (spec S4.1 L6).
  That layer stays out of every branch until the written patent-clearance
  opinion required by spec S10.4 exists.
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
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "camera_center",
    "cheirality_mask",
    "epipolar_distance",
    "fundamental_from_projections",
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
]

_TINY = np.finfo(float).tiny


# --------------------------------------------------------------------------- #
# Cameras and projection
# --------------------------------------------------------------------------- #


def projection_matrix(K: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Assemble ``P = K [R | t]`` (3x4) from intrinsics and extrinsics."""
    K = np.asarray(K, dtype=float).reshape(3, 3)
    R = np.asarray(R, dtype=float).reshape(3, 3)
    t = np.asarray(t, dtype=float).reshape(3)
    return K @ np.hstack([R, t[:, None]])


def camera_center(P: np.ndarray) -> np.ndarray:
    """Camera centre as the right null-space of ``P`` (3-vector, world frame)."""
    P = np.asarray(P, dtype=float).reshape(3, 4)
    _, _, vt = np.linalg.svd(P)
    Ch = vt[-1]
    if abs(Ch[3]) < 1e-12:
        raise ValueError("degenerate projection matrix: camera centre at infinity")
    return Ch[:3] / Ch[3]


def project_with_depth(P: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project world points and also return the projective depth ``p3 . Xh``."""
    P = np.asarray(P, dtype=float).reshape(3, 4)
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    w = X @ P[2, :3] + P[2, 3]
    u = (X @ P[0, :3] + P[0, 3]) / w
    v = (X @ P[1, :3] + P[1, 3]) / w
    return np.column_stack([u, v]), w


def project(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Project world points ``(N, 3)`` to pixels ``(N, 2)``."""
    return project_with_depth(P, X)[0]


def _hom2(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).reshape(-1, 2)
    return np.hstack([x, np.ones((x.shape[0], 1))])


def _normalizer_2d(x: np.ndarray) -> np.ndarray:
    """Hartley isotropic normalising transform for one view's pixel coordinates.

    Triangulation is invariant under ``x -> T x`` combined with ``P -> T P``, so
    this only buys conditioning: with focal lengths of order 1e4 px the raw DLT
    design matrix mixes entries spanning several decades.
    """
    x = np.asarray(x, dtype=float).reshape(-1, 2)
    c = x.mean(axis=0)
    d = float(np.sqrt(((x - c) ** 2).sum(axis=1)).mean())
    s = np.sqrt(2.0) / d if d > 1e-12 else 1.0
    return np.array([[s, 0.0, -s * c[0]], [0.0, s, -s * c[1]], [0.0, 0.0, 1.0]])


# --------------------------------------------------------------------------- #
# Epipolar geometry
# --------------------------------------------------------------------------- #


def fundamental_from_projections(P1: np.ndarray, P2: np.ndarray) -> np.ndarray:
    """Fundamental matrix with ``x2.T @ F @ x1 == 0``, from the two ``P`` matrices.

    Uses ``F = [e2]_x P2 P1^+`` with ``e2 = P2 C1``. Spec S4.3 requires F to be
    derived from the calibration rather than fitted from correspondences, so that
    the epipolar quality metrics measure the *match*, not a co-estimated geometry.
    """
    P1 = np.asarray(P1, dtype=float).reshape(3, 4)
    P2 = np.asarray(P2, dtype=float).reshape(3, 4)
    C1 = camera_center(P1)
    e2 = P2 @ np.append(C1, 1.0)
    ex = np.array(
        [[0.0, -e2[2], e2[1]], [e2[2], 0.0, -e2[0]], [-e2[1], e2[0], 0.0]]
    )
    F = ex @ P2 @ np.linalg.pinv(P1)
    n = np.linalg.norm(F)
    return F / n if n > 0 else F


def epipolar_distance(
    F: np.ndarray, x1: np.ndarray, x2: np.ndarray, symmetric: bool = True
) -> np.ndarray:
    """Point-to-epipolar-line distance in pixels (spec S4.3).

    With ``symmetric=False`` this is the one-way distance of ``x2`` to the line
    ``F x1``; with ``symmetric=True`` it is the mean of both directions.
    """
    F = np.asarray(F, dtype=float).reshape(3, 3)
    x1h, x2h = _hom2(x1), _hom2(x2)
    l2 = x1h @ F.T
    num = np.abs(np.einsum("ij,ij->i", x2h, l2))
    d21 = num / np.maximum(np.hypot(l2[:, 0], l2[:, 1]), _TINY)
    if not symmetric:
        return d21
    l1 = x2h @ F
    d12 = num / np.maximum(np.hypot(l1[:, 0], l1[:, 1]), _TINY)
    return 0.5 * (d21 + d12)


def sampson_distance(F: np.ndarray, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """Sampson distance in pixels (spec S4.3, default POI-level quality field)."""
    F = np.asarray(F, dtype=float).reshape(3, 3)
    x1h, x2h = _hom2(x1), _hom2(x2)
    Fx1 = x1h @ F.T
    Ftx2 = x2h @ F
    eps = np.einsum("ij,ij->i", x2h, Fx1)
    den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
    return np.abs(eps) / np.sqrt(np.maximum(den, _TINY))


def sampson_correct(
    F: np.ndarray, x1: np.ndarray, x2: np.ndarray, iters: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """Move ``x1, x2`` onto corresponding epipolar lines with minimal L2 shift.

    One Sampson step is the first-order optimal correction; iterating it converges
    to the Hartley--Sturm optimum without the degree-six polynomial root finding,
    which is what spec S6.1 calls the "iterative Sampson correction" rung.
    After convergence the two rays intersect exactly, so a subsequent DLT is the
    exact L2-optimal triangulation of the corrected pair.
    """
    F = np.asarray(F, dtype=float).reshape(3, 3)
    a = np.array(x1, dtype=float).reshape(-1, 2)
    b = np.array(x2, dtype=float).reshape(-1, 2)
    for _ in range(int(iters)):
        ah, bh = _hom2(a), _hom2(b)
        Fx1 = ah @ F.T
        Ftx2 = bh @ F
        eps = np.einsum("ij,ij->i", bh, Fx1)
        den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
        k = eps / np.maximum(den, _TINY)
        a = a - k[:, None] * Ftx2[:, :2]
        b = b - k[:, None] * Fx1[:, :2]
    return a, b


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
    """
    Ps = [np.asarray(P, dtype=float).reshape(3, 4) for P in Ps]
    xs = [np.asarray(x, dtype=float).reshape(-1, 2) for x in xs]
    if len(Ps) != len(xs):
        raise ValueError("Ps and xs must have the same number of views")
    if len(Ps) < 2:
        raise ValueError("triangulation needs at least two views")
    n = xs[0].shape[0]
    if any(x.shape[0] != n for x in xs):
        raise ValueError("all views must supply the same number of points")

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
    bad = np.abs(w) < 1e-14
    if np.any(bad):
        w = np.where(bad, np.nan, w)
    return Xh[:, :3] / w[:, None]


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
    P = np.asarray(P, dtype=float).reshape(3, 4)
    M = P[:, :3]
    d = np.linalg.solve(M, _hom2(x).T).T
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
    """
    C1 = camera_center(P1)
    C2 = camera_center(P2)
    d1 = _ray_directions(P1, x1)
    d2 = _ray_directions(P2, x2)
    e = C1 - C2
    c = np.einsum("ij,ij->i", d1, d2)
    b1 = -(d1 @ e)
    b2 = d2 @ e
    det = 1.0 - c**2
    near_parallel = np.abs(det) < 1e-14
    det = np.where(near_parallel, np.nan, det)
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
    P = np.asarray(P, dtype=float).reshape(3, 4)
    w = X @ P[2, :3] + P[2, 3]
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
    weights: Sequence[float] | None,
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
    """
    Ps = [np.asarray(P, dtype=float).reshape(3, 4) for P in Ps]
    xs = [np.asarray(x, dtype=float).reshape(-1, 2) for x in xs]
    X = (
        triangulate_multiview_dlt(Ps, xs)
        if X0 is None
        else np.array(X0, dtype=float).reshape(-1, 3)
    )
    _, _, cost = _normal_equations(Ps, xs, X, weights)

    for _ in range(int(iters)):
        JtJ, Jtr, _ = _normal_equations(Ps, xs, X, weights)
        # Relative Levenberg damping keeps rank-deficient points (near-parallel
        # rays) from producing an unusable step instead of raising.
        damp = 1e-12 * np.trace(JtJ, axis1=1, axis2=2)
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
        delta = np.max(np.abs(np.where(improved[:, None], X_new - X, 0.0)))
        X = np.where(improved[:, None], X_new, X)
        cost = np.where(improved, cost_new, cost)
        if delta < tol:
            break
    return X


# --------------------------------------------------------------------------- #
# Quality metrics and uncertainty
# --------------------------------------------------------------------------- #


def reprojection_residuals(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], X: np.ndarray
) -> np.ndarray:
    """Per-view reprojection residuals in pixels, shape ``(n_views, N, 2)``."""
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    return np.stack(
        [project(P, X) - np.asarray(x, dtype=float).reshape(-1, 2)
         for P, x in zip(Ps, xs, strict=True)]
    )


def reprojection_rmse(
    Ps: Sequence[np.ndarray], xs: Sequence[np.ndarray], X: np.ndarray
) -> float:
    """Root-mean-square reprojection error in pixels over all views and points."""
    r = reprojection_residuals(Ps, xs, X)
    return float(np.sqrt(np.mean(r**2) * 2.0))


def cheirality_mask(Ps: Sequence[np.ndarray], X: np.ndarray) -> np.ndarray:
    """Boolean mask of points lying in front of every camera.

    The cheapest half of the quality gate of spec S5.1 stage D. It catches sign
    inversions and rays that cross behind a camera, but *not* the far-field
    degeneracy where near-parallel rays admit a low-residual solution near
    infinity -- for that, gate on :func:`triangulation_covariance` as well.
    """
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    ok = np.ones(X.shape[0], dtype=bool)
    for P in Ps:
        P = np.asarray(P, dtype=float).reshape(3, 4)
        ok &= (X @ P[2, :3] + P[2, 3]) > 0
    return ok


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
    """
    Ps = [np.asarray(P, dtype=float).reshape(3, 4) for P in Ps]
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    sig = np.broadcast_to(np.asarray(sigma_px, dtype=float), (len(Ps),))
    JtJ = np.zeros((X.shape[0], 3, 3))
    for P, s in zip(Ps, sig, strict=True):
        _, Ju, Jv = _projection_jacobian(P, X)
        w = 1.0 / float(s) ** 2
        JtJ += w * (Ju[:, :, None] * Ju[:, None, :] + Jv[:, :, None] * Jv[:, None, :])
    return np.linalg.inv(JtJ)
