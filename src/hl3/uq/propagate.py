# SPDX-License-Identifier: Apache-2.0
"""Displacement covariance -> strain standard deviation (IR2-F3 segments B/C/D).

Spec R1-O1 section 6.2 makes per-point, per-frame 1-sigma a *default* output
rather than a manual GPG exercise, and section 2.6 supplies the input side of
it: the ICGN Hessian already yields ``Cov(p) = 2 sigma_n^2 H^-1``, so the
displacement uncertainty costs nothing extra. What was missing is the step from
there to strain, and that is where the number is made or ruined -- strain is a
*derivative*, so its noise is set almost entirely by the strain window, and a
strain uncertainty quoted without the window that produced it is meaningless
(see :mod:`hl3.strain.vsg`).

The chain is split into four segments, of which this module implements three:

===  ==================================================  =========================
  A  image noise -> ``Cov(p)`` per POI                    ``hl3.correlate``
  B  ``Cov(p)`` -> ``Var(u), Var(v), Cov(u, v)``          :func:`displacement_variances`
  C  displacement variance -> gradient covariance         :func:`propagate_strain_std`
  D  gradient covariance -> strain component sigma        :func:`propagate_strain_std`
===  ==================================================  =========================

Segment C is *exact*, not an approximation, because the PLS fit of
:func:`hl3.strain.pls_gradients` is linear in the neighbouring displacements:
for a fixed window, weighting and validity mask the fitted coefficients are
``A^-1 X^T W u``, so each gradient is a fixed weighted sum and its variance is
the corresponding quadratic form. Only segment D linearises, and only because
the tensor family is non-linear; for ``engineering`` even that step is exact.

The headline consequence, for a full uniform window of ``L`` POI at pitch
``step`` and a homoscedastic ``sigma_u`` (IR2-F3 section 5)::

    sigma(exx) = (sigma_u / step) * sqrt(12 / (L^2 (L^2 - 1)))

-- strain noise falls roughly as ``L^-2``, which is the quantitative half of the
VSG trade-off that :mod:`hl3.strain.vsg` states qualitatively. That closed form
is asserted to 1e-12 in ``tests/test_uq.py``; this module computes the general
case (clipped windows, holes, per-point variance, weighting, quadratic fits),
for which no closed form exists.

Registered assumptions (IR2-F3 section 6), because a sigma without its
assumptions is decoration:

* **A1, independence between POI.** Neighbouring subsets share pixels whenever
  ``step < subset``, so their displacement errors are positively correlated and
  a strain sigma computed as if they were independent is systematically *low*.
  The assumption travels with the result as
  ``StrainStdField.neighbor_correlation``; a correlation correction is a future
  keyword, not a silent default change.
* **A2, the only cross term is within a POI**, the ``Cov(u, v)`` of the kernel's
  own 2x2 block. ``uv_cov=None`` means "treated as zero", which is what a bare
  pair of standard deviations claims.
* **A3, the kernel's noise model**: i.i.d. Gaussian sensor noise in each image,
  conditioned on the converged solution. Interpolation bias and pattern-induced
  bias are *systematic* errors and are not in this sigma.
* **A4, first-order delta method** in segment D. Exact for ``engineering``; a
  large-strain second-order correction to ``green_lagrange`` is a future slot.

This module transports uncertainty; it does not invent it. Hand it a measured
noise floor or the correlator's covariance, and record which.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from hl3.io.hdf5_schema import UQ_METHODS
from hl3.strain import StrainField, StrainParams, pls_gradients

# Imported rather than restated: the propagated variance is only correct if the
# linear operator built here is the *same* operator the fitter applies, so the
# term list, the weight profile and the rank threshold must have exactly one
# definition in the tree (IR2-F3 section 4 item 2 -- the equivalence discipline).
# ``tests/test_uq.py`` asserts the two agree point by point, which is what keeps
# this coupling honest.
from hl3.strain.pls import _REL_EPS, _TERMS, _weights_1d

__all__ = [
    "DisplacementVariances",
    "StrainStdField",
    "displacement_variances",
    "propagate_strain_std",
]

#: ``uncertainty/@method`` written by this chain, from ``UQ_METHODS``.
UQ_METHOD = "propagated"
if UQ_METHOD not in UQ_METHODS:
    raise RuntimeError(
        f"{UQ_METHOD!r} is not in hl3.io.hdf5_schema.UQ_METHODS; a stored "
        "uncertainty group with an unknown @method cannot be read back"
    )

#: Registered value of ``StrainStdField.neighbor_correlation`` for assumption A1.
NEIGHBOR_CORRELATION_INDEPENDENT = "independent"

#: Tensor families with a frozen analytic Jacobian (IR2-F3 section 5). The rest
#: of ``STRAIN_TENSORS`` is rejected rather than silently approximated.
PROPAGATED_TENSORS = ("engineering", "green_lagrange")

#: Order of the gradient vector segment C produces.
_GRADIENT_LABELS = ("u_x", "u_y", "v_x", "v_y")


# --------------------------------------------------------------------------
# Segment B: Cov(p) -> displacement variances
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DisplacementVariances:
    """Per-POI displacement variance triple, flat and in the correlator's order.

    ``uv_cov`` is the covariance between the ``u`` and ``v`` errors *at the same
    POI*. It is not a decoration: the ICGN Hessian is not diagonal, so for an
    anisotropic speckle or a subset near an edge the two components are
    genuinely correlated, and dropping the cross term moves the shear-strain
    uncertainty. Errors at *different* POI are assumed independent (assumption
    A1 of the module docstring).

    ``nan`` is passed through exactly as the kernel produced it -- a point with
    no covariance has no uncertainty, and this layer does not re-mask by status:
    the validity criterion is applied once, by the strain fit, so that the two
    cannot diverge (IR2-F3 section 3 item 3).
    """

    u_var: np.ndarray  # (P,) Var(u), in squared displacement units
    v_var: np.ndarray  # (P,) Var(v)
    uv_cov: np.ndarray  # (P,) Cov(u, v)
    shape_order: int  # 1 = affine, 2 = quadratic; echoed from the solution

    @property
    def u_std(self) -> np.ndarray:
        """``uncertainty/u_std``: ``sqrt(Var(u))``, ``nan`` preserved."""
        return np.sqrt(self.u_var)

    @property
    def v_std(self) -> np.ndarray:
        """``uncertainty/v_std``: ``sqrt(Var(v))``, ``nan`` preserved."""
        return np.sqrt(self.v_var)


def displacement_variances(result: Any) -> DisplacementVariances:
    """Segment B: read the displacement block out of ``ICGNResult.covariance``.

    ``result`` is an :class:`hl3.correlate.ICGNResult` solved with
    ``ICGNParams(compute_covariance=True, image_noise_sigma=...)``. The columns
    of ``p`` are located through the kernel's own
    :func:`hl3.correlate.icgn.shape_param_labels` layout rather than a second
    copy of the index convention, so ``u`` is always ``p[0]`` and ``v`` is
    ``p[3]`` (affine) or ``p[6]`` (quadratic) by construction.

    Fail-closed: a solution without a covariance raises rather than substituting
    a proxy such as ZNCC. No covariance means no uncertainty, and inventing one
    would be worse than reporting none. The covariance is also only as
    meaningful as ``image_noise_sigma``: with the default 0 the kernel reports
    exactly zero, and so does this.
    """
    covariance = getattr(result, "covariance", None)
    if covariance is None:
        raise ValueError(
            "result carries no covariance; solve with "
            "ICGNParams(compute_covariance=True, image_noise_sigma=...) -- "
            "there is no uncertainty to extract otherwise"
        )
    cov = np.asarray(covariance, dtype=float)
    if cov.ndim != 3 or cov.shape[1] != cov.shape[2]:
        raise ValueError(f"covariance must have shape (P, k, k), got {cov.shape}")

    labels = tuple(getattr(result, "p_labels", ()))
    if "u" not in labels or "v" not in labels:
        raise ValueError(
            "result does not expose the frozen shape-parameter labels; "
            "expected an ICGNResult with p_labels containing 'u' and 'v'"
        )
    index_u, index_v = labels.index("u"), labels.index("v")
    if max(index_u, index_v) >= cov.shape[1]:
        raise ValueError(
            f"covariance is {cov.shape[1]}x{cov.shape[1]} but the shape "
            f"function has {len(labels)} parameters"
        )

    u_var = cov[:, index_u, index_u].copy()
    v_var = cov[:, index_v, index_v].copy()
    uv_cov = cov[:, index_u, index_v].copy()
    _reject_negative_variance(u_var, "Var(u)")
    _reject_negative_variance(v_var, "Var(v)")
    return DisplacementVariances(
        u_var=u_var,
        v_var=v_var,
        uv_cov=uv_cov,
        shape_order=int(getattr(result, "shape_order", 1)),
    )


# --------------------------------------------------------------------------
# Segments C and D: displacement variance -> strain sigma
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StrainStdField:
    """Per-POI strain component sigma, with the assumptions it rests on.

    Arrays are flat and indexed by POI in the correlator's point order (row
    major, ``index = iy * nx + ix``), exactly like
    :class:`hl3.strain.StrainField`; :meth:`as_grid` gives the ``(ny, nx)`` view
    for an uncertainty map. Like the strain field and unlike the displacement
    field, the arrays carry their ``nan``: an invalid point is ``nan`` in all
    three components, so ``valid == isfinite(exx_std)`` is exact.
    """

    exx_std: np.ndarray  # (P,)
    eyy_std: np.ndarray  # (P,)
    exy_std: np.ndarray  # (P,) tensor shear; gamma_xy_std = 2 * exy_std
    tensor: str
    window_pts: int
    grid_shape: tuple[int, int]
    method: str = UQ_METHOD
    neighbor_correlation: str = NEIGHBOR_CORRELATION_INDEPENDENT
    image_noise_sigma_dn: float | None = None

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.exx_std)

    @property
    def n_points(self) -> int:
        return int(self.exx_std.size)

    @property
    def gamma_xy_std(self) -> np.ndarray:
        """``2 * exy_std`` -- the other side of the factor-2 shear trap."""
        return 2.0 * self.exy_std

    def as_grid(self, name: str) -> np.ndarray:
        """A ``(ny, nx)`` view of one field, for plotting and line probes."""
        values = np.asarray(getattr(self, name))
        if values.shape[:1] != (self.n_points,):
            raise ValueError(
                f"{name} is not a per-POI array of length {self.n_points}"
            )
        return values.reshape(self.grid_shape + values.shape[1:])

    def schema_datasets(self) -> dict[str, np.ndarray]:
        """Datasets of ``uncertainty/strain_std/<name>`` (schema section 9.4).

        The keys are the names of the ``strain/<strain_id>`` datasets they
        qualify, which is the alignment rule the schema states.
        """
        return {"exx": self.exx_std, "eyy": self.eyy_std, "exy": self.exy_std}

    def schema_attrs(self) -> dict[str, object]:
        """Attributes of the ``uncertainty/`` group."""
        attrs: dict[str, object] = {"method": self.method}
        if self.image_noise_sigma_dn is not None:
            attrs["image_noise_sigma_dn"] = float(self.image_noise_sigma_dn)
        return attrs


def propagate_strain_std(
    u: np.ndarray,
    v: np.ndarray,
    u_var: np.ndarray,
    v_var: np.ndarray,
    params: StrainParams | None = None,
    *,
    step_px: float,
    uv_cov: np.ndarray | None = None,
    valid: np.ndarray | None = None,
    check_against: StrainField | None = None,
    image_noise_sigma_dn: float | None = None,
) -> StrainStdField:
    """Segments C and D: strain sigma for the fit ``compute_strain`` performs.

    The signature mirrors :func:`hl3.strain.compute_strain` deliberately. A
    standard deviation describes *an estimator*, so it must be computed for the
    same displacements, the same ``params``, the same ``step_px`` and the same
    validity mask as the strain it qualifies; anything else produces a plausible
    number for a field nobody computed. The gradients themselves are taken from
    :func:`hl3.strain.pls_gradients` rather than recomputed here, so the
    linearisation point and the ``nan`` pattern are the fitter's own.

    Parameters
    ----------
    u, v
        Displacement grids, ``(ny, nx)``, ``nan`` where unsolved.
    u_var, v_var
        Per-POI displacement *variance* grids, same shape, in squared
        displacement units (px^2 for the uncalibrated 2-D chain). ``nan`` means
        "no covariance for this POI".
    params
        The :class:`hl3.strain.StrainParams` that produced the strain field.
        The tensor must be one of :data:`PROPAGATED_TENSORS`.
    step_px
        The POI pitch used for the strain, in the units of ``u`` and ``v``.
    uv_cov
        Per-POI ``Cov(u, v)``; ``None`` is treated as zero (assumption A2).
    valid
        The same neighbour criterion the strain fit used, i.e.
        ``status == Status.CONVERGED``.
    check_against
        When given, the strain field this sigma is meant to qualify. Its
        ``nan`` pattern and its ``tensor``/``method``/``window_pts``/
        ``weighting`` metadata must match, or :class:`ValueError` -- parameter
        drift between the strain and its uncertainty is the most easily missed
        error in this chain, and the cross-check is cheap insurance.
    image_noise_sigma_dn
        Echoed into the result and onto ``uncertainty/@image_noise_sigma_dn``;
        never used in the arithmetic.

    Notes
    -----
    Missing data is ``nan``, never an exception, and never a zero: a point whose
    fit window contains a valid neighbour with no known variance gets ``nan``
    sigma, because using zero there would understate the uncertainty and
    shrinking the window would describe a different estimator. Bad data is an
    exception: a finite negative variance, or a ``uv_cov`` that violates
    Cauchy-Schwarz, is not a missing measurement but an impossible one.
    """
    params = params or StrainParams()
    if params.tensor not in PROPAGATED_TENSORS:
        raise ValueError(
            f"tensor {params.tensor!r} has no frozen Jacobian in S3; "
            f"propagation is implemented for {PROPAGATED_TENSORS}. Refusing to "
            "approximate it by the engineering tensor"
        )
    step = float(step_px)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError(f"step_px must be finite and > 0, got {step_px!r}")

    u_grid = _as_grid(u, "u", None)
    shape = u_grid.shape
    v_grid = _as_grid(v, "v", shape)
    u_var_grid = _as_grid(u_var, "u_var", shape)
    v_var_grid = _as_grid(v_var, "v_var", shape)
    uv_cov_grid = (
        np.zeros(shape)
        if uv_cov is None
        else _as_grid(uv_cov, "uv_cov", shape)
    )
    _reject_negative_variance(u_var_grid, "u_var")
    _reject_negative_variance(v_var_grid, "v_var")
    _reject_impossible_cross_term(u_var_grid, v_var_grid, uv_cov_grid)

    if u_grid.size == 0:
        # An empty AOI is a legitimate question with an empty answer. The
        # fitter cannot be called on one (its window is wider than the padded
        # grid), so the short-circuit is here rather than a special case there.
        empty = np.empty(0)
        return StrainStdField(
            exx_std=empty,
            eyy_std=empty.copy(),
            exy_std=empty.copy(),
            tensor=params.tensor,
            window_pts=params.window_pts,
            grid_shape=(int(shape[0]), int(shape[1])),
            image_noise_sigma_dn=(
                None if image_noise_sigma_dn is None else float(image_noise_sigma_dn)
            ),
        )

    gradients = pls_gradients(
        u_grid,
        v_grid,
        step_px=step,
        window_pts=params.window_pts,
        fit_order=params.fit_order,
        weighting=params.weighting,
        sigma=params.sigma,
        valid=valid,
        neighbor_min=params.neighbor_min,
        require_center=params.require_center,
    )
    if check_against is not None:
        _cross_check(check_against, gradients, params)

    std = _propagate(
        gradients=gradients,
        mask=_fit_mask(u_grid, v_grid, valid),
        u_var=u_var_grid,
        v_var=v_var_grid,
        uv_cov=uv_cov_grid,
        params=params,
        step=step,
        std=np.full((u_grid.size, 3), np.nan),
    )

    return StrainStdField(
        exx_std=std[:, 0],
        eyy_std=std[:, 1],
        exy_std=std[:, 2],
        tensor=params.tensor,
        window_pts=params.window_pts,
        grid_shape=gradients.shape,
        image_noise_sigma_dn=(
            None if image_noise_sigma_dn is None else float(image_noise_sigma_dn)
        ),
    )


# --------------------------------------------------------------------------
# Implementation
# --------------------------------------------------------------------------


def _propagate(
    *,
    gradients: Any,
    mask: np.ndarray,
    u_var: np.ndarray,
    v_var: np.ndarray,
    uv_cov: np.ndarray,
    params: StrainParams,
    step: float,
    std: np.ndarray,
) -> np.ndarray:
    """Fill ``std`` at the points where both the fit and the variances exist."""
    win = int(params.window_pts)
    radius = win // 2
    terms = _TERMS[params.fit_order]

    design, weights = _window_design(win, terms, params.weighting, params.sigma)
    mask_win = _windows(mask.astype(float), radius)  # (ny, nx, W)
    flat_mask = mask_win.reshape(-1, win * win)

    accepted = np.isfinite(gradients.u_x).ravel()
    # A valid neighbour with no known variance makes the whole fit's variance
    # unknown: zero would understate it and a shrunken window would describe a
    # different estimator (IR2-F3 section 7).
    known = np.isfinite(u_var) & np.isfinite(v_var) & np.isfinite(uv_cov)
    contributing_unknown = (
        _windows((mask & ~known).astype(float), radius).reshape(-1, win * win).sum(
            axis=-1
        )
        > 0.0
    )
    index = np.flatnonzero(accepted & ~contributing_unknown)
    if index.size == 0:
        return std

    gram = np.einsum(
        "pi,it,is->pts", flat_mask[index] * weights, design, design
    )
    # Same rank test, same threshold as the fitter: a window this operator
    # would invert but the fitter refuses (or the reverse) is a silent
    # disagreement between a strain and its uncertainty.
    eig = np.linalg.eigvalsh(gram)
    keep = eig[:, 0] > _REL_EPS * eig[:, -1]
    index, gram = index[keep], gram[keep]
    if index.size == 0:
        return std

    weighted = flat_mask[index] * weights  # (p, W)
    rows = np.linalg.solve(gram, design.T[None, :, :] * weighted[:, None, :])
    # The two rows of the hat matrix the fitter reads u_x and u_y off, already
    # divided by the step, so they map displacements straight to gradients.
    c_x = rows[:, 1, :] / step
    c_y = rows[:, 2, :] / step

    var_u = _windows(u_var, radius).reshape(-1, win * win)[index]
    var_v = _windows(v_var, radius).reshape(-1, win * win)[index]
    cov_uv = _windows(uv_cov, radius).reshape(-1, win * win)[index]

    cov_g = np.zeros((index.size, 4, 4))
    rows_xy = (c_x, c_y)
    for a in range(2):
        for b in range(2):
            product = rows_xy[a] * rows_xy[b]
            cov_g[:, a, b] = np.einsum("pj,pj->p", product, var_u)
            cov_g[:, 2 + a, 2 + b] = np.einsum("pj,pj->p", product, var_v)
            cross = np.einsum("pj,pj->p", product, cov_uv)
            cov_g[:, a, 2 + b] = cross
            cov_g[:, 2 + b, a] = cross

    jac = _tensor_jacobian(gradients, index, params.tensor)  # (p, 3, 4)
    variance = np.einsum("pij,pjk,pik->pi", jac, cov_g, jac)
    std[index] = np.sqrt(np.clip(variance, 0.0, None))
    return std


def _window_design(
    window_pts: int,
    terms: tuple[tuple[int, int], ...],
    weighting: str,
    sigma: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    """``(X, w)``: the basis matrix and window weights, ordered ``dy`` then ``dx``."""
    radius = window_pts // 2
    offsets = np.arange(-radius, radius + 1, dtype=float)
    dy, dx = np.meshgrid(offsets, offsets, indexing="ij")
    design = np.stack([dx.ravel() ** a * dy.ravel() ** b for a, b in terms], axis=1)
    profile = _weights_1d(window_pts, weighting, sigma)
    return design, np.outer(profile, profile).ravel()


def _windows(field: np.ndarray, radius: int) -> np.ndarray:
    """``(ny, nx, W)`` zero-padded neighbourhoods, ordered ``dy`` then ``dx``.

    Matches the correlation orientation of ``hl3.strain.pls._correlate1d``:
    entry ``(dy + radius) * win + (dx + radius)`` of point ``(iy, ix)`` is the
    grid value at ``(iy + dy, ix + dx)``, or 0 outside the grid. Zero padding is
    right rather than merely convenient -- a POI off the edge of the grid
    contributes nothing, and mirroring would invent a measurement.
    """
    padded = np.pad(np.nan_to_num(field, nan=0.0), ((radius, radius),) * 2)
    win = 2 * radius + 1
    view = sliding_window_view(padded, (win, win))
    return view.reshape(field.shape[0], field.shape[1], win * win)


def _tensor_jacobian(gradients: Any, index: np.ndarray, tensor: str) -> np.ndarray:
    """``d(exx, eyy, exy) / d(u_x, u_y, v_x, v_y)``, shape ``(p, 3, 4)``.

    The frozen table of IR2-F3 section 5, evaluated at the fitted gradients.
    Written out rather than differenced numerically because both entries are
    two lines of algebra and an exact Jacobian costs nothing:

    * ``engineering`` is linear, so its Jacobian is constant and the whole
      propagation is exact;
    * ``green_lagrange`` has ``E_xx = u_x + (u_x^2 + v_x^2) / 2`` and friends,
      so the Jacobian is the deformation gradient's own entries -- and the
      first-order delta method it feeds is an approximation whose error grows
      with the strain (assumption A4).
    """
    u_x = gradients.u_x.ravel()[index]
    u_y = gradients.u_y.ravel()[index]
    v_x = gradients.v_x.ravel()[index]
    v_y = gradients.v_y.ravel()[index]
    jac = np.zeros((index.size, 3, 4))
    if tensor == "engineering":
        jac[:, 0, 0] = 1.0
        jac[:, 1, 3] = 1.0
        jac[:, 2, 1] = 0.5
        jac[:, 2, 2] = 0.5
        return jac
    jac[:, 0, 0] = 1.0 + u_x
    jac[:, 0, 2] = v_x
    jac[:, 1, 1] = u_y
    jac[:, 1, 3] = 1.0 + v_y
    jac[:, 2, 0] = 0.5 * u_y
    jac[:, 2, 1] = 0.5 * (1.0 + u_x)
    jac[:, 2, 2] = 0.5 * (1.0 + v_y)
    jac[:, 2, 3] = 0.5 * v_x
    return jac


def _fit_mask(
    u: np.ndarray, v: np.ndarray, valid: np.ndarray | None
) -> np.ndarray:
    """The POI the fit actually uses, combined exactly as the fitter does."""
    mask = np.isfinite(u) & np.isfinite(v)
    if valid is None:
        return mask
    valid_arr = np.asarray(valid)
    if valid_arr.shape != u.shape:
        raise ValueError(
            f"valid must have the same shape as u, got {valid_arr.shape} and "
            f"{u.shape}"
        )
    if valid_arr.dtype != np.bool_:
        raise ValueError(f"valid must be a boolean mask, got dtype {valid_arr.dtype}")
    return mask & valid_arr


def _cross_check(
    strain: StrainField, gradients: Any, params: StrainParams
) -> None:
    """Refuse to describe a strain field this sigma was not computed for."""
    for name, expected, got in (
        ("tensor", strain.tensor, params.tensor),
        ("method", strain.method, params.method),
        ("window_pts", int(strain.window_pts), int(params.window_pts)),
        ("weighting", strain.weighting, params.weighting),
    ):
        if expected != got:
            raise ValueError(
                f"check_against disagrees on {name}: the strain field says "
                f"{expected!r}, these parameters say {got!r}; the uncertainty "
                "would describe a different estimator"
            )
    if strain.grid_shape != gradients.shape:
        raise ValueError(
            f"check_against has grid shape {strain.grid_shape}, the "
            f"propagation grid is {gradients.shape}"
        )
    if not np.array_equal(strain.valid, np.isfinite(gradients.u_x).ravel()):
        raise ValueError(
            "check_against has a different validity pattern than the "
            "re-fitted gradients; the displacements or the mask differ from "
            "the ones that produced the strain field"
        )


def _as_grid(
    values: np.ndarray, name: str, shape: tuple[int, ...] | None
) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ValueError(
            f"{name} must be a 2-D (ny, nx) grid of POI values, got shape "
            f"{array.shape}"
        )
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    return array


def _reject_negative_variance(values: np.ndarray, name: str) -> None:
    """A finite negative variance is impossible input, not a missing one."""
    bad = np.isfinite(values) & (values < 0.0)
    if np.any(bad):
        raise ValueError(
            f"{name} is negative at {int(np.count_nonzero(bad))} point(s); a "
            "variance cannot be negative, so this is a broken input rather "
            "than a missing measurement (which would be nan)"
        )


def _reject_impossible_cross_term(
    u_var: np.ndarray, v_var: np.ndarray, uv_cov: np.ndarray
) -> None:
    """Cauchy-Schwarz on the per-POI 2x2 block."""
    known = np.isfinite(u_var) & np.isfinite(v_var) & np.isfinite(uv_cov)
    bound = np.sqrt(np.where(known, u_var * v_var, 0.0))
    bad = known & (np.abs(uv_cov) > bound * (1.0 + 1e-9) + 1e-300)
    if np.any(bad):
        raise ValueError(
            f"uv_cov violates |Cov(u, v)| <= sqrt(Var(u) Var(v)) at "
            f"{int(np.count_nonzero(bad))} point(s); that 2x2 point covariance "
            "is not positive semi-definite"
        )
