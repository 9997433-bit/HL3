"""Synthetic stereo rig generation, linear camera resection and error metrics.

Round 2 lightweight prototype for the HL3-3D calibration chain (spec
``.agent_workspace/round1/R1-O2-hl3-3d-spec.md``, section 4). NumPy only.

What this module *is*
---------------------
A closed-loop synthetic testbed: build a stereo rig with exactly known
intrinsics and extrinsics, project known 3D geometry into both cameras, add
image noise, then either

* triangulate with the true cameras and report the 3D reconstruction error, or
* recover each camera from 3D--2D correspondences by linear DLT resection,
  decompose the result back into ``K, R, t``, and report both the pose error and
  the 3D error that the residual calibration error causes downstream.

That second path is the point of the exercise. The Stereo-DIC Challenge 1.0
conclusion quoted in spec section 4 is that the five commercial codes differ
mainly through *calibration*, not through the correlator, so the prototype is
built to make calibration error visible as micrometres of 3D error rather than
as a single opaque "calibration score".

What this module is *not*
-------------------------
* **Not Zhang's method.** Resection here consumes 3D points whose world
  coordinates are known exactly, i.e. a 3D calibration object. Zhang's planar
  method (per-board homographies, closed-form intrinsics from the image of the
  absolute conic, then Levenberg--Marquardt bundle adjustment over intrinsics,
  distortion, per-board poses and the stereo extrinsics) treats the board poses
  as unknowns and is the real deliverable. So is checkerboard/ChArUco corner
  detection from actual images, the target-non-ideality free parameters of spec
  section 4.2 step 4, and the bootstrap covariance ``Sigma_cal`` of spec section
  4.2 step 5. All of that is later work; see the module ``README`` note in the
  Round 2 report.
* **No lens distortion.** Pure L0 pinhole. See ``triangulate`` module docstring.
* **No non-parametric distortion field / stereo microscopy** (spec section 4.1
  L6). Blocked behind the written patent-clearance opinion of spec section 10.4
  and intentionally absent from this branch.

Conventions match :mod:`hl3.stereo.triangulate`: millimetres, pixels,
``x_cam = R @ X_world + t``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .triangulate import (
    cheirality_mask,
    epipolar_distance,
    fundamental_from_projections,
    project,
    projection_matrix,
    reprojection_rmse,
    sampson_correct,
    sampson_distance,
    triangulate_dlt,
    triangulate_midpoint,
    triangulate_nonlinear,
    triangulate_optimal,
    triangulation_covariance,
)

__all__ = [
    "Camera",
    "StereoRig",
    "add_pixel_noise",
    "decompose_projection",
    "intrinsics",
    "look_at_extrinsics",
    "make_stereo_rig",
    "pose_errors",
    "reconstruction_error",
    "relative_pose",
    "resection_dlt",
    "rq3",
    "run_synthetic_experiment",
    "synth_complex_surface",
    "synth_planar_target",
    "synth_target_poses",
    "umeyama",
    "visible_mask",
]


# --------------------------------------------------------------------------- #
# Camera model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Camera:
    """Pinhole camera: intrinsics ``K`` plus world-to-camera rotation/translation."""

    K: np.ndarray
    R: np.ndarray
    t: np.ndarray
    width: int = 0
    height: int = 0

    @property
    def P(self) -> np.ndarray:
        """The 3x4 projection matrix ``K [R | t]``."""
        return projection_matrix(self.K, self.R, self.t)

    @property
    def C(self) -> np.ndarray:
        """Camera centre in world coordinates."""
        return -self.R.T @ self.t

    def project(self, X: np.ndarray) -> np.ndarray:
        """Project world points ``(N, 3)`` to pixels ``(N, 2)``."""
        return project(self.P, X)


@dataclass(frozen=True)
class StereoRig:
    """A two-camera rig plus its nominal working distance, for bookkeeping."""

    left: Camera
    right: Camera
    standoff_mm: float = 0.0

    @property
    def baseline_mm(self) -> float:
        """Distance between the two camera centres."""
        return float(np.linalg.norm(self.right.C - self.left.C))

    @property
    def stereo_angle_deg(self) -> float:
        """Angle subtended at the world origin by the two camera centres."""
        a = -self.left.C / np.linalg.norm(self.left.C)
        b = -self.right.C / np.linalg.norm(self.right.C)
        return float(np.degrees(np.arccos(np.clip(a @ b, -1.0, 1.0))))


def intrinsics(
    focal_mm: float,
    pixel_pitch_mm: float,
    width: int,
    height: int,
    principal_point: tuple[float, float] | None = None,
) -> np.ndarray:
    """Square-pixel, zero-skew intrinsic matrix from physical lens/sensor data.

    Skew is locked to zero, matching the L0 default of spec section 4.1.
    """
    f = focal_mm / pixel_pitch_mm
    if principal_point is None:
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    else:
        cx, cy = principal_point
    return np.array([[f, 0.0, cx], [0.0, f, cy], [0.0, 0.0, 1.0]])


def look_at_extrinsics(
    center: np.ndarray, target: np.ndarray, up: np.ndarray = (0.0, -1.0, 0.0)
) -> tuple[np.ndarray, np.ndarray]:
    """Extrinsics for a camera at ``center`` whose optical axis points at ``target``.

    Returns ``(R, t)`` with ``x_cam = R @ X_world + t``; the camera looks along
    its own ``+z`` axis and image ``v`` increases along camera ``+y``.
    """
    center = np.asarray(center, dtype=float).reshape(3)
    target = np.asarray(target, dtype=float).reshape(3)
    up = np.asarray(up, dtype=float).reshape(3)

    zc = target - center
    zc /= np.linalg.norm(zc)
    xc = np.cross(up, zc)
    nx = np.linalg.norm(xc)
    if nx < 1e-12:
        raise ValueError("'up' is parallel to the optical axis")
    xc /= nx
    yc = np.cross(zc, xc)
    R = np.stack([xc, yc, zc])
    return R, -R @ center


def make_stereo_rig(
    baseline_mm: float = 254.0,
    standoff_mm: float = 648.0,
    focal_mm: float = 35.0,
    pixel_pitch_mm: float = 3.45e-3,
    width: int = 2448,
    height: int = 2048,
    target: np.ndarray = (0.0, 0.0, 0.0),
) -> StereoRig:
    """Converged stereo pair, both cameras aimed at ``target``.

    The default numbers follow the publicly reported Stereo-DIC Challenge 1.0
    Sample 1 "35 mm" configuration (35 mm lens, 648 mm standoff, 254 mm baseline,
    3.45 um pixels), which lands at about 15.7 px/mm at the object -- close to the
    16.35 px/mm scale quoted in the Challenge paper. Only the published geometry
    is reproduced; no Challenge imagery is used or redistributed here.
    """
    target = np.asarray(target, dtype=float).reshape(3)
    K = intrinsics(focal_mm, pixel_pitch_mm, width, height)
    half = baseline_mm / 2.0
    cams = []
    for sign in (-1.0, +1.0):
        C = target + np.array([sign * half, 0.0, -standoff_mm])
        R, t = look_at_extrinsics(C, target)
        cams.append(Camera(K=K.copy(), R=R, t=t, width=width, height=height))
    return StereoRig(left=cams[0], right=cams[1], standoff_mm=standoff_mm)


# --------------------------------------------------------------------------- #
# Synthetic geometry
# --------------------------------------------------------------------------- #


def synth_complex_surface(
    n_side: int = 61, half_extent_mm: float = 45.0
) -> np.ndarray:
    """A small stand-in for the Challenge Sample 1 "complex shape" test object.

    A tilted base plane carrying a 45-degree triangular ridge, a half-cylinder and
    a raised step, so the point set spans roughly 16 mm of depth. The ridge and
    the step deliberately create curvature and depth discontinuities: those are
    where every code in the Challenge lost points, so they belong in the very
    first synthetic fixture even at prototype scale.

    Returns ``(n_side**2, 3)`` world points; the surface faces the cameras
    (features protrude towards -z).
    """
    g = np.linspace(-half_extent_mm, half_extent_mm, int(n_side))
    xx, yy = np.meshgrid(g, g, indexing="xy")
    x = xx.ravel()
    y = yy.ravel()

    h = 0.02 * x  # slight global tilt
    ridge = 12.0 - np.abs(x + 22.0)
    h = h + np.where(ridge > 0.0, ridge, 0.0)
    r2 = 100.0 - (x - 22.0) ** 2
    h = h + np.where(r2 > 0.0, np.sqrt(np.maximum(r2, 0.0)), 0.0)
    h = h + np.where(y > 20.0, 4.0, 0.0)

    return np.column_stack([x, y, -h])


def synth_planar_target(
    n_cols: int = 9, n_rows: int = 7, spacing_mm: float = 10.0
) -> np.ndarray:
    """Planar grid of target points in the board frame, centred, ``z = 0``."""
    xs = (np.arange(n_cols) - (n_cols - 1) / 2.0) * spacing_mm
    ys = (np.arange(n_rows) - (n_rows - 1) / 2.0) * spacing_mm
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])


def _rotation_xyz(rx: float, ry: float, rz: float) -> np.ndarray:
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    return Rz @ Ry @ Rx


def synth_target_poses(
    n_poses: int = 14,
    depth_span_mm: float = 120.0,
    lateral_span_mm: float = 40.0,
    max_tilt_deg: float = 28.0,
    seed: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Board poses spread through the calibration volume, as ``(R, t)`` pairs.

    Poses are drawn from a fixed-seed generator over depth, lateral position and
    tilt. This is the crude ancestor of the six-dimensional coverage grid and
    next-best-view guidance of spec section 4.4: here it only guarantees that the
    poses are not degenerate, it does not yet score coverage or condition number.
    """
    rng = np.random.default_rng(seed)
    poses = []
    for i in range(int(n_poses)):
        frac = (i + 0.5) / n_poses
        tz = (frac - 0.5) * depth_span_mm
        tx, ty = rng.uniform(-lateral_span_mm, lateral_span_mm, size=2)
        tilt = np.radians(max_tilt_deg)
        rx, ry = rng.uniform(-tilt, tilt, size=2)
        rz = rng.uniform(-np.pi / 6.0, np.pi / 6.0)
        poses.append((_rotation_xyz(rx, ry, rz), np.array([tx, ty, tz])))
    return poses


def visible_mask(cam: Camera, X: np.ndarray, margin_px: float = 0.0) -> np.ndarray:
    """Boolean mask of points that fall inside ``cam``'s sensor and in front of it."""
    P = cam.P
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    w = X @ P[2, :3] + P[2, 3]
    x = cam.project(X)
    return (
        (w > 0)
        & (x[:, 0] >= margin_px)
        & (x[:, 0] <= cam.width - 1 - margin_px)
        & (x[:, 1] >= margin_px)
        & (x[:, 1] <= cam.height - 1 - margin_px)
    )


def add_pixel_noise(
    x: np.ndarray, sigma_px: float, rng: np.random.Generator
) -> np.ndarray:
    """Add isotropic Gaussian image-plane noise of ``sigma_px`` to ``(N, 2)`` pixels."""
    x = np.asarray(x, dtype=float)
    if sigma_px <= 0.0:
        return x.copy()
    return x + rng.normal(0.0, sigma_px, size=x.shape)


# --------------------------------------------------------------------------- #
# Linear resection and pose algebra
# --------------------------------------------------------------------------- #


def _normalize_2d(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = x.mean(axis=0)
    d = float(np.sqrt(((x - c) ** 2).sum(axis=1)).mean())
    s = np.sqrt(2.0) / d if d > 1e-12 else 1.0
    T = np.array([[s, 0.0, -s * c[0]], [0.0, s, -s * c[1]], [0.0, 0.0, 1.0]])
    return T, (x - c) * s


def _normalize_3d(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = X.mean(axis=0)
    d = float(np.sqrt(((X - c) ** 2).sum(axis=1)).mean())
    s = np.sqrt(3.0) / d if d > 1e-12 else 1.0
    U = np.eye(4)
    U[:3, :3] *= s
    U[:3, 3] = -s * c
    return U, (X - c) * s


def resection_dlt(X: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Recover a 3x4 projection matrix from >= 6 non-coplanar 3D--2D correspondences.

    Hartley-normalised direct linear transform: each correspondence contributes
    ``u (p3 . Xh) - (p1 . Xh) = 0`` and ``v (p3 . Xh) - (p2 . Xh) = 0``, and the
    solution is the right singular vector of the 2N x 12 design matrix with the
    smallest singular value.

    The 3D points must not be coplanar -- a single planar board is a degenerate
    configuration for this estimator. Use the union of several board poses, or
    Zhang's planar method (later work).
    """
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    x = np.asarray(x, dtype=float).reshape(-1, 2)
    n = X.shape[0]
    if n != x.shape[0]:
        raise ValueError("X and x must have the same number of rows")
    if n < 6:
        raise ValueError("DLT resection needs at least 6 correspondences")
    if np.linalg.matrix_rank(X - X.mean(axis=0), tol=1e-8) < 3:
        raise ValueError("DLT resection needs non-coplanar 3D points")

    T, xn = _normalize_2d(x)
    U, Xn = _normalize_3d(X)
    Xh = np.hstack([Xn, np.ones((n, 1))])
    zero = np.zeros((n, 4))

    A = np.empty((2 * n, 12))
    A[0::2] = np.hstack([-Xh, zero, xn[:, 0:1] * Xh])
    A[1::2] = np.hstack([zero, -Xh, xn[:, 1:2] * Xh])

    _, _, vt = np.linalg.svd(A)
    Pn = vt[-1].reshape(3, 4)
    P = np.linalg.inv(T) @ Pn @ U
    return P / np.linalg.norm(P[2, :3])


def rq3(M: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """RQ decomposition of a 3x3 matrix: ``M = R @ Q`` with ``R`` upper triangular."""
    M = np.asarray(M, dtype=float).reshape(3, 3)
    E = np.flipud(np.eye(3))
    Q0, R0 = np.linalg.qr((E @ M).T)
    R = E @ R0.T @ E
    Q = E @ Q0.T
    return R, Q


def decompose_projection(P: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split a 3x4 projection matrix into ``(K, R, t)`` with ``K[2, 2] == 1``.

    The sign of ``P`` is fixed so that ``det(M) > 0``, which after forcing a
    positive-diagonal ``K`` guarantees ``det(R) == +1`` and keeps scene points in
    front of the camera.
    """
    P = np.asarray(P, dtype=float).reshape(3, 4)
    if np.linalg.det(P[:, :3]) < 0:
        P = -P
    Kr, R = rq3(P[:, :3])
    d = np.sign(np.diag(Kr))
    d[d == 0] = 1.0
    D = np.diag(d)
    Kr = Kr @ D
    R = D @ R
    scale = Kr[2, 2]
    K = Kr / scale
    t = np.linalg.solve(K, P[:, 3]) / scale
    return K, R, t


def relative_pose(
    R1: np.ndarray, t1: np.ndarray, R2: np.ndarray, t2: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Pose of camera 2 in camera 1's frame: ``x2 = R_rel @ x1 + t_rel``."""
    R_rel = R2 @ R1.T
    return R_rel, t2 - R_rel @ t1


def umeyama(
    A: np.ndarray, B: np.ndarray, with_scale: bool = False
) -> tuple[np.ndarray, np.ndarray, float]:
    """Least-squares similarity aligning ``A`` onto ``B`` (Umeyama 1991).

    Minimises ``sum_i || s R a_i + t - b_i ||^2`` and returns ``(R, t, s)``.
    Reflections are excluded, so ``det(R) == +1``. With ``with_scale=False`` the
    scale is locked to 1, which is the correct choice whenever both point sets
    are already in physical units -- letting scale float is the standard way to
    hide a calibration error (spec sections 8.4 and 12.2).
    """
    A = np.asarray(A, dtype=float).reshape(-1, 3)
    B = np.asarray(B, dtype=float).reshape(-1, 3)
    n = A.shape[0]
    muA, muB = A.mean(axis=0), B.mean(axis=0)
    Ac, Bc = A - muA, B - muB
    C = (Bc.T @ Ac) / n
    U, S, Vt = np.linalg.svd(C)
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1.0
    R = U @ D @ Vt
    if with_scale:
        var_a = float((Ac**2).sum()) / n
        s = float(np.trace(np.diag(S) @ D) / var_a) if var_a > 0 else 1.0
    else:
        s = 1.0
    return R, muB - s * (R @ muA), s


# --------------------------------------------------------------------------- #
# Error metrics
# --------------------------------------------------------------------------- #


def pose_errors(
    R_est: np.ndarray, t_est: np.ndarray, R_true: np.ndarray, t_true: np.ndarray
) -> dict[str, float]:
    """Rotation angle error (degrees) and translation error (mm, absolute/relative)."""
    dR = np.asarray(R_est) @ np.asarray(R_true).T
    cos = (np.trace(dR) - 1.0) / 2.0
    dt = np.asarray(t_est, dtype=float) - np.asarray(t_true, dtype=float)
    norm_true = float(np.linalg.norm(t_true))
    return {
        "rotation_deg": float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))),
        "translation_mm": float(np.linalg.norm(dt)),
        "translation_rel": float(np.linalg.norm(dt) / norm_true) if norm_true else 0.0,
    }


def reconstruction_error(
    X_est: np.ndarray, X_true: np.ndarray, align: bool = False
) -> dict[str, float]:
    """3D error statistics in micrometres, plus per-axis RMS.

    With ``align=True`` the estimate is first brought onto the truth by a
    scale-locked rigid transform and the recovered rotation angle and translation
    are reported as well. Comparing the aligned and unaligned numbers separates
    genuine shape error from a rigid frame offset -- exactly the distinction the
    Challenge preliminary analysis found people were missing (spec section 7.3).
    """
    X_est = np.asarray(X_est, dtype=float).reshape(-1, 3)
    X_true = np.asarray(X_true, dtype=float).reshape(-1, 3)

    out: dict[str, float] = {}
    if align:
        R, t, _ = umeyama(X_est, X_true, with_scale=False)
        X_est = X_est @ R.T + t
        cos = (np.trace(R) - 1.0) / 2.0
        out["align_rotation_deg"] = float(
            np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
        )
        out["align_translation_um"] = float(np.linalg.norm(t) * 1e3)

    d = (X_est - X_true) * 1e3  # mm -> um
    r = np.linalg.norm(d, axis=1)
    out.update(
        {
            "rms_um": float(np.sqrt(np.mean(r**2))),
            "mean_um": float(np.mean(r)),
            "p95_um": float(np.percentile(r, 95.0)),
            "max_um": float(np.max(r)),
            "rms_x_um": float(np.sqrt(np.mean(d[:, 0] ** 2))),
            "rms_y_um": float(np.sqrt(np.mean(d[:, 1] ** 2))),
            "rms_z_um": float(np.sqrt(np.mean(d[:, 2] ** 2))),
            "bias_x_um": float(np.mean(d[:, 0])),
            "bias_y_um": float(np.mean(d[:, 1])),
            "bias_z_um": float(np.mean(d[:, 2])),
        }
    )
    return out


# --------------------------------------------------------------------------- #
# End-to-end synthetic experiment
# --------------------------------------------------------------------------- #


def _triangulate_all(
    rig: StereoRig, xL: np.ndarray, xR: np.ndarray
) -> dict[str, np.ndarray]:
    """Run all four triangulation rungs on the same correspondences."""
    PL, PR = rig.left.P, rig.right.P
    return {
        "midpoint": triangulate_midpoint(PL, PR, xL, xR),
        "dlt": triangulate_dlt(PL, PR, xL, xR),
        "sampson": triangulate_optimal(PL, PR, xL, xR),
        "nonlinear": triangulate_nonlinear([PL, PR], [xL, xR]),
    }


def _resect_rig(
    rig: StereoRig,
    X_cal: np.ndarray,
    sigma_px: float,
    rng: np.random.Generator,
) -> tuple[StereoRig, list[np.ndarray]]:
    """Resect both cameras of ``rig`` from noisy projections of ``X_cal``."""
    cams, x_obs = [], []
    for cam in (rig.left, rig.right):
        x = add_pixel_noise(cam.project(X_cal), sigma_px, rng)
        K_e, R_e, t_e = decompose_projection(resection_dlt(X_cal, x))
        cams.append(Camera(K_e, R_e, t_e, cam.width, cam.height))
        x_obs.append(x)
    return StereoRig(cams[0], cams[1], rig.standoff_mm), x_obs


def _calibration_volume(
    rig: StereoRig, n_poses: int, seed: int
) -> np.ndarray:
    """Union of ``n_poses`` planar-board point sets visible in both cameras."""
    board = synth_planar_target()
    poses = synth_target_poses(n_poses=n_poses, seed=seed)
    X_cal = np.concatenate([board @ R.T + t for R, t in poses])
    vis = visible_mask(rig.left, X_cal, margin_px=4.0) & visible_mask(
        rig.right, X_cal, margin_px=4.0
    )
    return X_cal[vis]


@dataclass(frozen=True)
class _Scene:
    """The fixed part of the study: a rig, its truth surface and exact pixels."""

    rig: StereoRig
    X_true: np.ndarray
    xL0: np.ndarray
    xR0: np.ndarray

    @property
    def Ps(self) -> list[np.ndarray]:
        return [self.rig.left.P, self.rig.right.P]

    def tiled_truth(self, n: int) -> np.ndarray:
        return np.tile(self.X_true, (int(n), 1))


def _study_noise_free(sc: _Scene) -> dict:
    return {
        name: {
            **reconstruction_error(X_est, sc.X_true),
            "reproj_rmse_px": reprojection_rmse(sc.Ps, [sc.xL0, sc.xR0], X_est),
        }
        for name, X_est in _triangulate_all(sc.rig, sc.xL0, sc.xR0).items()
    }


def _study_noise_sweep(
    sc: _Scene, sigmas_px: tuple[float, ...], n_trials: int, rng: np.random.Generator
) -> tuple[dict, dict[float, np.ndarray]]:
    """Monte-Carlo 3D error per triangulation rung; also returns the raw draws."""
    sweep: dict[str, dict] = {}
    mc_store: dict[float, np.ndarray] = {}
    for sigma in sigmas_px:
        per_method: dict[str, list[np.ndarray]] = {}
        reproj: dict[str, list[float]] = {}
        for _ in range(n_trials):
            xL = add_pixel_noise(sc.xL0, sigma, rng)
            xR = add_pixel_noise(sc.xR0, sigma, rng)
            for name, X_est in _triangulate_all(sc.rig, xL, xR).items():
                per_method.setdefault(name, []).append(X_est)
                reproj.setdefault(name, []).append(
                    reprojection_rmse(sc.Ps, [xL, xR], X_est)
                )
        entry: dict = {
            name: {
                **reconstruction_error(
                    np.concatenate(arrs), sc.tiled_truth(len(arrs))
                ),
                "reproj_rmse_px": float(np.mean(reproj[name])),
            }
            for name, arrs in per_method.items()
        }
        ref = np.concatenate(per_method["nonlinear"])
        entry["spread_vs_nonlinear_um"] = {
            name: float(
                np.max(np.linalg.norm(np.concatenate(arrs) - ref, axis=1)) * 1e3
            )
            for name, arrs in per_method.items()
            if name != "nonlinear"
        }
        sweep[f"{sigma:g}"] = entry
        mc_store[sigma] = np.stack(per_method["nonlinear"])
    return sweep, mc_store


def _study_covariance(sc: _Scene, mc_store: dict[float, np.ndarray]) -> dict:
    """Compare the first-order covariance against the Monte-Carlo spread."""
    out = {}
    for sigma, draws in mc_store.items():
        if sigma <= 0.0:
            continue
        Sig = triangulation_covariance(sc.Ps, sc.X_true, sigma_px=sigma)
        pred = np.sqrt(np.diagonal(Sig, axis1=1, axis2=2)) * 1e3
        emp = draws.std(axis=0, ddof=1) * 1e3
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = emp / pred
        out[f"{sigma:g}"] = {
            "pred_sigma_x_um": float(pred[:, 0].mean()),
            "pred_sigma_y_um": float(pred[:, 1].mean()),
            "pred_sigma_z_um": float(pred[:, 2].mean()),
            "emp_sigma_x_um": float(emp[:, 0].mean()),
            "emp_sigma_y_um": float(emp[:, 1].mean()),
            "emp_sigma_z_um": float(emp[:, 2].mean()),
            "ratio_mean": float(np.nanmean(ratio)),
            "ratio_max_dev": float(np.nanmax(np.abs(ratio - 1.0))),
        }
    return out


def _study_epipolar(sc: _Scene, sigma_px: float, rng: np.random.Generator) -> dict:
    PL, PR = sc.Ps
    F = fundamental_from_projections(PL, PR)
    x1h = np.hstack([sc.xL0, np.ones((sc.xL0.shape[0], 1))])
    x2h = np.hstack([sc.xR0, np.ones((sc.xR0.shape[0], 1))])
    xLn = add_pixel_noise(sc.xL0, sigma_px, rng)
    xRn = add_pixel_noise(sc.xR0, sigma_px, rng)
    xLc, xRc = sampson_correct(F, xLn, xRn, iters=10)
    return {
        "constraint_residual_exact": float(
            np.max(np.abs(np.einsum("ij,ij->i", x2h, x1h @ F.T)))
        ),
        "sampson_px_exact_max": float(np.max(sampson_distance(F, sc.xL0, sc.xR0))),
        "sym_epipolar_px_exact_max": float(
            np.max(epipolar_distance(F, sc.xL0, sc.xR0))
        ),
        "noise_sigma_px": sigma_px,
        "sampson_px_noisy_rms": float(
            np.sqrt(np.mean(sampson_distance(F, xLn, xRn) ** 2))
        ),
        "sampson_px_corrected_max": float(np.max(sampson_distance(F, xLc, xRc))),
        "correction_shift_px_rms": float(
            np.sqrt(np.mean(np.linalg.norm(xLc - xLn, axis=1) ** 2))
        ),
    }


def _study_multiview(
    sc: _Scene, sigma_px: float, n_trials: int, rng: np.random.Generator
) -> dict:
    """Does a third camera above the baseline buy accuracy at fixed image noise?"""
    left = sc.rig.left
    R3, t3 = look_at_extrinsics(
        [0.0, -220.0, -sc.rig.standoff_mm], np.zeros(3), up=(0.0, 0.0, -1.0)
    )
    cam3 = Camera(left.K.copy(), R3, t3, left.width, left.height)
    vis3 = visible_mask(cam3, sc.X_true, margin_px=8.0)
    Ps = [*sc.Ps, cam3.P]
    xs0 = [sc.xL0, sc.xR0, cam3.project(sc.X_true)]

    two, three = [], []
    for _ in range(n_trials):
        xs = [add_pixel_noise(x, sigma_px, rng) for x in xs0]
        two.append(triangulate_nonlinear(Ps[:2], xs[:2])[vis3])
        three.append(triangulate_nonlinear(Ps, xs)[vis3])
    Xt = np.tile(sc.X_true[vis3], (n_trials, 1))
    return {
        "sigma_px": sigma_px,
        "n_points_visible_in_3": int(vis3.sum()),
        "two_view": reconstruction_error(np.concatenate(two), Xt),
        "three_view": reconstruction_error(np.concatenate(three), Xt),
    }


def _camera_recovery_errors(
    est: Camera, truth: Camera, X_cal: np.ndarray, x_cal: np.ndarray
) -> dict:
    pe = pose_errors(est.R, est.t, truth.R, truth.t)
    resid = project(est.P, X_cal) - x_cal
    return {
        "focal_err_rel": float(abs(est.K[0, 0] - truth.K[0, 0]) / truth.K[0, 0]),
        "focal_x_px": float(est.K[0, 0]),
        "focal_y_px": float(est.K[1, 1]),
        "cx_err_px": float(est.K[0, 2] - truth.K[0, 2]),
        "cy_err_px": float(est.K[1, 2] - truth.K[1, 2]),
        "skew_px": float(est.K[0, 1]),
        "rotation_err_deg": pe["rotation_deg"],
        "translation_err_mm": pe["translation_mm"],
        "center_err_um": float(np.linalg.norm(est.C - truth.C) * 1e3),
        "target_reproj_rmse_px": float(np.sqrt(np.mean(np.sum(resid**2, axis=1)))),
    }


def _study_calibration(
    sc: _Scene, X_cal: np.ndarray, calib_sigma_px: float, rng: np.random.Generator
) -> tuple[dict, StereoRig]:
    """Resect both cameras from the target, exactly and under detection noise."""
    rig = sc.rig
    out: dict = {"n_target_points": int(X_cal.shape[0])}
    rig_noisy = rig
    for label, sigma in (("exact", 0.0), ("noisy", calib_sigma_px)):
        rig_est, x_obs = _resect_rig(rig, X_cal, sigma, rng)
        entry: dict = {"detection_sigma_px": sigma}
        for side, est, truth, x in (
            ("left", rig_est.left, rig.left, x_obs[0]),
            ("right", rig_est.right, rig.right, x_obs[1]),
        ):
            entry[side] = _camera_recovery_errors(est, truth, X_cal, x)

        R_rel_e, t_rel_e = relative_pose(
            rig_est.left.R, rig_est.left.t, rig_est.right.R, rig_est.right.t
        )
        R_rel_t, t_rel_t = relative_pose(
            rig.left.R, rig.left.t, rig.right.R, rig.right.t
        )
        pe_rel = pose_errors(R_rel_e, t_rel_e, R_rel_t, t_rel_t)
        base_e = rig_est.baseline_mm
        entry["extrinsics"] = {
            "rel_rotation_err_deg": pe_rel["rotation_deg"],
            "rel_translation_err_um": pe_rel["translation_mm"] * 1e3,
            "baseline_est_mm": base_e,
            "baseline_err_um": (base_e - rig.baseline_mm) * 1e3,
        }

        # Exact pixels, so any 3D error left here is purely calibration error.
        X_est = triangulate_nonlinear(
            [rig_est.left.P, rig_est.right.P], [sc.xL0, sc.xR0]
        )
        entry["surface"] = {
            "raw": reconstruction_error(X_est, sc.X_true),
            "aligned": reconstruction_error(X_est, sc.X_true, align=True),
        }
        out[label] = entry
        if label == "noisy":
            rig_noisy = rig_est
    return out, rig_noisy


def _study_pose_sweep(
    sc: _Scene,
    pose_counts: tuple[int, ...],
    pose_repeats: int,
    calib_sigma_px: float,
    seed: int,
    rng: np.random.Generator,
) -> dict:
    """Calibration-induced 3D error as a function of target-pose count."""
    out = {}
    for npose in pose_counts:
        Xc = _calibration_volume(sc.rig, int(npose), (seed + npose) % 2**32)
        rms, rms_aligned = [], []
        for _ in range(pose_repeats):
            rig_e, _ = _resect_rig(sc.rig, Xc, calib_sigma_px, rng)
            Xe = triangulate_nonlinear(
                [rig_e.left.P, rig_e.right.P], [sc.xL0, sc.xR0]
            )
            rms.append(reconstruction_error(Xe, sc.X_true)["rms_um"])
            rms_aligned.append(
                reconstruction_error(Xe, sc.X_true, align=True)["rms_um"]
            )
        out[str(int(npose))] = {
            "n_target_points": int(Xc.shape[0]),
            "calib_rms_um_mean": float(np.mean(rms)),
            "calib_rms_um_max": float(np.max(rms)),
            "calib_rms_um_aligned_mean": float(np.mean(rms_aligned)),
        }
    return out


def _study_error_budget(
    sc: _Scene,
    rig_noisy: StereoRig,
    match_sigma_px: float,
    calib_sigma_px: float,
    n_trials: int,
    rng: np.random.Generator,
) -> dict:
    """Split the 3D error into its matching and calibration contributions."""
    Ps_true = sc.Ps
    Ps_est = [rig_noisy.left.P, rig_noisy.right.P]
    match_only, combined = [], []
    for _ in range(n_trials):
        xL = add_pixel_noise(sc.xL0, match_sigma_px, rng)
        xR = add_pixel_noise(sc.xR0, match_sigma_px, rng)
        match_only.append(triangulate_nonlinear(Ps_true, [xL, xR]))
        combined.append(triangulate_nonlinear(Ps_est, [xL, xR]))
    calib_only = triangulate_nonlinear(Ps_est, [sc.xL0, sc.xR0])
    Xt = sc.tiled_truth(n_trials)
    return {
        "match_sigma_px": match_sigma_px,
        "calib_sigma_px": calib_sigma_px,
        "matching_only": reconstruction_error(np.concatenate(match_only), Xt),
        "calibration_only": reconstruction_error(calib_only, sc.X_true),
        "combined": reconstruction_error(np.concatenate(combined), Xt),
    }


def _study_degeneracy(
    sc: _Scene,
    sigma_px: float,
    gate_sigma_mm: float,
    n_trials: int,
    rng: np.random.Generator,
) -> dict:
    """Behaviour at absurd image noise, with and without the quality gate.

    The gate is cheirality plus a ceiling on the predicted position uncertainty.
    The covariance term is what catches the far-field failure mode: near-parallel
    corrupted rays admit a low-residual minimum out near infinity, which no
    reprojection-residual threshold can reject because its residual is small.
    """
    PL, PR = sc.Ps
    out: dict = {
        "sigma_px": sigma_px,
        "gate_sigma_mm": gate_sigma_mm,
        "n_trials": int(n_trials),
    }
    pooled: dict[str, list[np.ndarray]] = {}
    for _ in range(n_trials):
        xL = add_pixel_noise(sc.xL0, sigma_px, rng)
        xR = add_pixel_noise(sc.xR0, sigma_px, rng)
        for name, X_est in _triangulate_all(sc.rig, xL, xR).items():
            pooled.setdefault(name, []).append(X_est)

    Xt = sc.tiled_truth(n_trials)
    for name, arrs in pooled.items():
        X_est = np.concatenate(arrs)
        finite = np.all(np.isfinite(X_est), axis=1)
        keep = finite.copy()
        keep[keep] = cheirality_mask([PL, PR], X_est[keep])
        idx = np.flatnonzero(keep)
        if idx.size:
            Sig = triangulation_covariance([PL, PR], X_est[idx], sigma_px=sigma_px)
            keep[idx] = np.sqrt(np.trace(Sig, axis1=1, axis2=2)) < gate_sigma_mm
        out[name] = {
            "kept_fraction": float(keep.mean()),
            "n_pooled": int(keep.size),
            "n_rejected": int(keep.size - keep.sum()),
            "nonfinite_fraction": float(1.0 - finite.mean()),
            "ungated": reconstruction_error(X_est[finite], Xt[finite]),
            "gated": (
                reconstruction_error(X_est[keep], Xt[keep]) if keep.any() else None
            ),
        }
    return out


def run_synthetic_experiment(
    sigmas_px: tuple[float, ...] = (0.0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.5),
    degenerate_sigma_px: float = 2.0,
    gate_sigma_mm: float = 1.0,
    n_trials: int = 60,
    n_side: int = 41,
    n_target_poses: int = 14,
    calib_sigma_px: float = 0.02,
    pose_counts: tuple[int, ...] = (3, 5, 8, 14, 25),
    pose_repeats: int = 10,
    seed: int = 20260828,
) -> dict:
    """Run the whole closed-loop study and return every metric as plain numbers.

    Parts:

    ``rig``
        geometry summary of the synthetic stereo pair.
    ``noise_free``
        project/triangulate round trip with exact cameras and exact pixels; this
        measures the numerical floor of the four triangulation rungs.
    ``noise_sweep``
        Monte-Carlo 3D error versus image-plane noise, per rung, plus the spread
        between rungs.
    ``covariance``
        predicted per-point standard deviations from
        :func:`~hl3.stereo.triangulate.triangulation_covariance` against the
        Monte-Carlo empirical spread.
    ``epipolar``
        Sampson-distance statistics before and after Sampson correction, and the
        residual of the analytic epipolar constraint on exact correspondences.
    ``multiview``
        two-camera versus three-camera triangulation at fixed image noise.
    ``calibration``
        DLT resection of both cameras from a synthetic multi-pose target, the
        recovered intrinsics/extrinsics errors, and the 3D error obtained when
        the *recovered* cameras are used to triangulate the test surface.
    ``pose_sweep``
        calibration-induced 3D error versus the number of target poses.
    ``error_budget``
        3D error attributable to matching noise alone, to calibration alone, and
        to both together.
    ``degeneracy``
        behaviour at grossly excessive image noise, with and without the
        cheirality + covariance quality gate.
    """
    rng = np.random.default_rng(seed)
    rig = make_stereo_rig()

    X_true = synth_complex_surface(n_side=n_side)
    keep = visible_mask(rig.left, X_true, margin_px=8.0) & visible_mask(
        rig.right, X_true, margin_px=8.0
    )
    X_true = X_true[keep]
    sc = _Scene(rig, X_true, rig.left.project(X_true), rig.right.project(X_true))
    n_trials = int(n_trials)

    X_cal = _calibration_volume(rig, n_target_poses, seed % 2**32)
    calibration, rig_noisy = _study_calibration(sc, X_cal, calib_sigma_px, rng)
    calibration["n_poses"] = int(n_target_poses)
    sweep, mc_store = _study_noise_sweep(sc, sigmas_px, n_trials, rng)

    return {
        "rig": {
            "baseline_mm": rig.baseline_mm,
            "standoff_mm": rig.standoff_mm,
            "stereo_angle_deg": rig.stereo_angle_deg,
            "focal_px": float(rig.left.K[0, 0]),
            "image_size": [rig.left.width, rig.left.height],
            "scale_px_per_mm": float(rig.left.K[0, 0] / rig.standoff_mm),
            "n_points": int(X_true.shape[0]),
            "depth_span_mm": float(np.ptp(X_true[:, 2])),
        },
        "noise_free": _study_noise_free(sc),
        "noise_sweep": sweep,
        "covariance": _study_covariance(sc, mc_store),
        "epipolar": _study_epipolar(sc, calib_sigma_px, rng),
        "multiview": _study_multiview(sc, calib_sigma_px, n_trials, rng),
        "calibration": calibration,
        "pose_sweep": _study_pose_sweep(
            sc, pose_counts, int(pose_repeats), calib_sigma_px, seed, rng
        ),
        "error_budget": _study_error_budget(
            sc, rig_noisy, calib_sigma_px, calib_sigma_px, n_trials, rng
        ),
        "degeneracy": _study_degeneracy(
            sc, degenerate_sigma_px, gate_sigma_mm, n_trials, rng
        ),
    }


def _fmt(v: float) -> str:
    return f"{v:.4g}"


def main() -> None:  # pragma: no cover - console reporting only
    """Print the synthetic study as plain text tables."""
    r = run_synthetic_experiment()

    print("== rig ==")
    for k, v in r["rig"].items():
        print(f"  {k:20s} {v}")

    print("\n== noise-free triangulation (numerical floor) ==")
    print(f"  {'method':10s} {'rms_um':>12s} {'max_um':>12s} {'reproj_px':>12s}")
    for name, m in r["noise_free"].items():
        print(
            f"  {name:10s} {_fmt(m['rms_um']):>12s} {_fmt(m['max_um']):>12s} "
            f"{_fmt(m['reproj_rmse_px']):>12s}"
        )

    print("\n== 3D RMS error [um] vs image noise [px] ==")
    methods = list(r["noise_free"].keys())
    header = "".join(f"{m:>12s}" for m in methods)
    print("  sigma_px  " + header + f"{'rms_z(nl)':>12s}")
    for s, row in r["noise_sweep"].items():
        cells = "".join(f"{_fmt(row[m]['rms_um']):>12s}" for m in methods)
        print(f"  {s:>8s}  " + cells + f"{_fmt(row['nonlinear']['rms_z_um']):>12s}")

    print("\n== max spread between triangulation rungs [um] ==")
    others = [m for m in methods if m != "nonlinear"]
    print(f"  {'sigma_px':>8s} " + "".join(f"{m:>12s}" for m in others))
    for s, row in r["noise_sweep"].items():
        sp = row["spread_vs_nonlinear_um"]
        print(f"  {s:>8s} " + "".join(f"{_fmt(sp[m]):>12s}" for m in sp))

    print("\n== covariance prediction vs Monte Carlo ==")
    print(
        f"  {'sigma':>8s} {'pred_z_um':>12s} {'emp_z_um':>12s} "
        f"{'ratio':>8s} {'max_dev':>8s}"
    )
    for s, c in r["covariance"].items():
        print(
            f"  {s:>8s} {_fmt(c['pred_sigma_z_um']):>12s} "
            f"{_fmt(c['emp_sigma_z_um']):>12s} {_fmt(c['ratio_mean']):>8s} "
            f"{_fmt(c['ratio_max_dev']):>8s}"
        )

    print("\n== epipolar geometry ==")
    for k, v in r["epipolar"].items():
        print(f"  {k:32s} {_fmt(v)}")

    print("\n== two-view vs three-view ==")
    mv = r["multiview"]
    print(
        f"  sigma={mv['sigma_px']} px, "
        f"{mv['n_points_visible_in_3']} points in all 3 views"
    )
    for k in ("two_view", "three_view"):
        m = mv[k]
        print(
            f"  {k:12s} rms={_fmt(m['rms_um'])}um  rms_z={_fmt(m['rms_z_um'])}um  "
            f"p95={_fmt(m['p95_um'])}um"
        )

    print("\n== calibration by DLT resection ==")
    for label in ("exact", "noisy"):
        e = r["calibration"][label]
        print(f"  [{label}] detection sigma = {e['detection_sigma_px']} px, "
              f"{r['calibration']['n_target_points']} target points")
        for side in ("left", "right"):
            c = e[side]
            print(
                f"    {side:5s} f_rel={_fmt(c['focal_err_rel'])} "
                f"cx={_fmt(c['cx_err_px'])}px rot={_fmt(c['rotation_err_deg'])}deg "
                f"C={_fmt(c['center_err_um'])}um "
                f"reproj={_fmt(c['target_reproj_rmse_px'])}px"
            )
        x = e["extrinsics"]
        print(
            f"    extrinsics rel_rot={_fmt(x['rel_rotation_err_deg'])}deg "
            f"rel_t={_fmt(x['rel_translation_err_um'])}um "
            f"baseline_err={_fmt(x['baseline_err_um'])}um"
        )
        print(
            f"    surface raw rms={_fmt(e['surface']['raw']['rms_um'])}um  "
            f"aligned rms={_fmt(e['surface']['aligned']['rms_um'])}um  "
            f"(align rot={_fmt(e['surface']['aligned']['align_rotation_deg'])}deg)"
        )

    print("\n== calibration-induced 3D error vs number of target poses ==")
    print(
        f"  {'poses':>6s} {'pts':>6s} {'rms_um':>10s} "
        f"{'rms_max_um':>12s} {'aligned_um':>12s}"
    )
    for n, p in r["pose_sweep"].items():
        print(
            f"  {n:>6s} {p['n_target_points']:>6d} "
            f"{_fmt(p['calib_rms_um_mean']):>10s} {_fmt(p['calib_rms_um_max']):>12s} "
            f"{_fmt(p['calib_rms_um_aligned_mean']):>12s}"
        )

    print("\n== error budget ==")
    b = r["error_budget"]
    print(
        f"  matching sigma={b['match_sigma_px']} px, "
        f"calibration sigma={b['calib_sigma_px']} px"
    )
    for k in ("matching_only", "calibration_only", "combined"):
        m = b[k]
        print(
            f"  {k:18s} rms={_fmt(m['rms_um'])}um  rms_z={_fmt(m['rms_z_um'])}um  "
            f"p95={_fmt(m['p95_um'])}um  max={_fmt(m['max_um'])}um"
        )

    d = r["degeneracy"]
    print(f"\n== degeneracy at sigma={d['sigma_px']} px "
          f"(gate: cheirality + sigma_pos < {d['gate_sigma_mm']} mm) ==")
    print(
        f"  {'method':10s} {'rejected':>10s} {'ungated_rms_um':>16s} "
        f"{'ungated_max_um':>16s} {'gated_rms_um':>14s} {'gated_max_um':>14s}"
    )
    for name in methods:
        m = d[name]
        g = m["gated"]
        rejected = f"{m['n_rejected']}/{m['n_pooled']}"
        print(
            f"  {name:10s} {rejected:>10s} "
            f"{_fmt(m['ungated']['rms_um']):>16s} {_fmt(m['ungated']['max_um']):>16s} "
            f"{(_fmt(g['rms_um']) if g else 'n/a'):>14s} "
            f"{(_fmt(g['max_um']) if g else 'n/a'):>14s}"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
