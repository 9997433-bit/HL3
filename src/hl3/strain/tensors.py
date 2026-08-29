# SPDX-License-Identifier: Apache-2.0
"""Plane strain-tensor family, principal values and equivalent measures.

Step 2 and step 3 of spec R1-O1 section 2.11. Everything here is a pure function
of the in-plane deformation gradient

    F = I + [[u_x, u_y], [v_x, v_y]]

and everything is vectorised over leading axes: a tensor argument of shape
``(..., 2, 2)`` describes a whole field, and ``nan`` entries propagate to ``nan``
outputs without raising. That last property is why the eigen-decompositions
below are written out in closed form instead of calling :func:`numpy.linalg.eigh`
-- ``eigh`` raises for the entire batch when a single window failed, and a
failed POI is normal, not exceptional.

Which tensor to use is not a matter of taste, and the choice must appear in the
report (GPG section 6.2.1). The decisive property is behaviour under rigid body
rotation by an angle ``theta``:

============================  ==========================  ====================
measure                       rigid rotation gives         valid when
============================  ==========================  ====================
``engineering``               ``e_xx = cos(theta) - 1``    ``|theta| << 1``
``green_lagrange``            exactly 0                    always
``euler_almansi``             exactly 0                    always
``hencky``                    exactly 0                    always
============================  ==========================  ====================

An engineering strain of ``cos(theta) - 1 ~ -theta^2 / 2`` is a pure artefact:
2 degrees of unintended rotation fabricates -610 microstrain of apparent
compression, which is comparable to the elastic strain in a metal coupon. This
module therefore defaults to nothing -- :func:`strain_tensor` requires the
caller to name the tensor -- while :class:`hl3.strain.StrainParams` defaults to
``green_lagrange`` as the spec requires.

Conventions
-----------
``x`` is the image column direction and ``y`` the image row direction, so with
the usual top-left origin the ``y`` axis points *down* and a positive rotation
angle from :func:`rotation_angle` is clockwise on screen. Angles are radians.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "TENSOR_KINDS",
    "PrincipalStrain",
    "deformation_gradient",
    "dilatation",
    "engineering_shear",
    "engineering_strain",
    "euler_almansi_strain",
    "green_lagrange_strain",
    "hencky_strain",
    "principal_strains",
    "rotation_angle",
    "strain_tensor",
    "tresca_strain",
    "von_mises_strain",
]

# The tensors this module computes. Every name is a member of
# ``hl3.io.hdf5_schema.STRAIN_TENSORS``; ``logarithmic`` is that vocabulary's
# second name for Hencky strain (they are the same tensor -- IR1-F4 gap G-4) and
# is accepted so that a schema-legal request is never refused.
TENSOR_KINDS = (
    "engineering",
    "green_lagrange",
    "euler_almansi",
    "hencky",
    "logarithmic",
)

_I2 = np.eye(2)


def _as_tensor_field(T: np.ndarray, name: str) -> np.ndarray:
    A = np.asarray(T, dtype=float)
    if A.ndim < 2 or A.shape[-2:] != (2, 2):
        raise ValueError(
            f"{name} must have shape (..., 2, 2) for a plane tensor field, "
            f"got shape {A.shape}"
        )
    return A


def _components(T: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(xx, yy, xy)`` of a symmetric tensor field, symmetrised on the way out.

    Symmetrising rather than reading ``T[..., 0, 1]`` costs nothing and makes
    the principal-value routines exact for tensors that are symmetric only up to
    rounding, which is what ``F^T F`` products are.
    """
    return T[..., 0, 0], T[..., 1, 1], 0.5 * (T[..., 0, 1] + T[..., 1, 0])


def _sym_eig2(
    a_xx: np.ndarray, a_yy: np.ndarray, a_xy: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Closed-form spectrum of a symmetric 2x2 field.

    Returns ``(lambda_1, lambda_2, theta)`` with ``lambda_1 >= lambda_2`` and
    ``theta`` the angle from the ``x`` axis to the first eigenvector, in
    radians and in ``[-pi/2, pi/2]``.

    ``hypot`` rather than ``sqrt`` of a sum of squares keeps the radius exact
    for the tiny strains DIC actually measures; ``atan2`` rather than ``atan``
    keeps the branch right when ``a_xx == a_yy`` (pure shear), where the naive
    formula divides by zero.
    """
    mean = 0.5 * (a_xx + a_yy)
    half_diff = 0.5 * (a_xx - a_yy)
    radius = np.hypot(half_diff, a_xy)
    return mean + radius, mean - radius, 0.5 * np.arctan2(2.0 * a_xy, a_xx - a_yy)


def deformation_gradient(
    u_x: np.ndarray, u_y: np.ndarray, v_x: np.ndarray, v_y: np.ndarray
) -> np.ndarray:
    """Assemble ``F = I + grad(displacement)``, shape ``(..., 2, 2)``."""
    arrays = np.broadcast_arrays(
        *(np.asarray(a, dtype=float) for a in (u_x, u_y, v_x, v_y))
    )
    F = np.stack(
        [
            np.stack([1.0 + arrays[0], arrays[1]], axis=-1),
            np.stack([arrays[2], 1.0 + arrays[3]], axis=-1),
        ],
        axis=-2,
    )
    return F


def engineering_strain(F: np.ndarray) -> np.ndarray:
    """Cauchy small-strain tensor ``eps = (grad u + grad u^T) / 2``.

    Linear in the displacement gradients, hence cheap and hence the default in
    much older software -- and wrong by ``-theta^2 / 2`` under rigid rotation.
    Use it when the rotation is known to be negligible, or to *demonstrate* that
    it is not.
    """
    F = _as_tensor_field(F, "F")
    H = F - _I2
    return 0.5 * (H + np.swapaxes(H, -1, -2))


def green_lagrange_strain(F: np.ndarray) -> np.ndarray:
    """Green-Lagrange strain ``E = (F^T F - I) / 2``, referred to the reference
    configuration.

    The spec default. Exactly zero for any rigid motion, which makes it the only
    member of the family that can be asserted against zero in a unit test
    without a tolerance that hides real error.
    """
    F = _as_tensor_field(F, "F")
    return 0.5 * (np.swapaxes(F, -1, -2) @ F - _I2)


def _inverse2(F: np.ndarray) -> np.ndarray:
    """Batched 2x2 inverse; singular entries become ``nan`` instead of raising."""
    det = F[..., 0, 0] * F[..., 1, 1] - F[..., 0, 1] * F[..., 1, 0]
    det = np.where(det == 0.0, np.nan, det)
    adj = np.stack(
        [
            np.stack([F[..., 1, 1], -F[..., 0, 1]], axis=-1),
            np.stack([-F[..., 1, 0], F[..., 0, 0]], axis=-1),
        ],
        axis=-2,
    )
    return adj / det[..., None, None]


def euler_almansi_strain(F: np.ndarray) -> np.ndarray:
    """Euler-Almansi strain ``e = (I - F^-T F^-1) / 2``, referred to the current
    configuration.

    The Eulerian counterpart of Green-Lagrange: same information, different
    reference. Report which one you used; at 20% strain they differ by 20%.
    """
    F = _as_tensor_field(F, "F")
    Finv = _inverse2(F)
    return 0.5 * (_I2 - np.swapaxes(Finv, -1, -2) @ Finv)


def hencky_strain(F: np.ndarray) -> np.ndarray:
    """Material logarithmic (Hencky) strain ``E_H = ln(U) = ln(F^T F) / 2``.

    Additive over successive load steps for coaxial deformation, which is why
    plasticity work wants it. Computed from the closed-form spectrum of
    ``C = F^T F``; a non-positive eigenvalue (only reachable from a
    non-physical, non-invertible ``F``) yields ``nan`` rather than a complex
    number cast to garbage.
    """
    F = _as_tensor_field(F, "F")
    C = np.swapaxes(F, -1, -2) @ F
    lam1, lam2, theta = _sym_eig2(*_components(C))
    with np.errstate(invalid="ignore", divide="ignore"):
        e1 = 0.5 * np.where(lam1 > 0.0, np.log(np.where(lam1 > 0.0, lam1, 1.0)), np.nan)
        e2 = 0.5 * np.where(lam2 > 0.0, np.log(np.where(lam2 > 0.0, lam2, 1.0)), np.nan)
    c, s = np.cos(theta), np.sin(theta)
    xx = e1 * c * c + e2 * s * s
    yy = e1 * s * s + e2 * c * c
    xy = (e1 - e2) * c * s
    return np.stack(
        [np.stack([xx, xy], axis=-1), np.stack([xy, yy], axis=-1)], axis=-2
    )


_TENSOR_FUNCS = {
    "engineering": engineering_strain,
    "green_lagrange": green_lagrange_strain,
    "euler_almansi": euler_almansi_strain,
    "hencky": hencky_strain,
    "logarithmic": hencky_strain,
}


def strain_tensor(F: np.ndarray, tensor: str) -> np.ndarray:
    """Dispatch to one member of the tensor family by its schema name.

    Names match ``@tensor`` in ``docs/schema-hdf5.md`` section 9.3, so a stored
    field can be recomputed from its own metadata. ``logarithmic`` and
    ``hencky`` resolve to the same function.
    """
    try:
        func = _TENSOR_FUNCS[tensor]
    except (KeyError, TypeError):
        raise ValueError(
            f"tensor must be one of {TENSOR_KINDS}, got {tensor!r}"
        ) from None
    return func(F)


@dataclass(frozen=True)
class PrincipalStrain:
    """Principal values, direction and in-plane maximum shear of a strain field."""

    e1: np.ndarray  # major principal strain
    e2: np.ndarray  # minor principal strain
    theta_p: np.ndarray  # radians, x axis to the e1 direction

    @property
    def gamma_max(self) -> np.ndarray:
        """In-plane maximum shear strain ``e1 - e2`` (engineering convention)."""
        return self.e1 - self.e2


def principal_strains(E: np.ndarray) -> PrincipalStrain:
    """Principal strains and principal direction of a symmetric strain field."""
    E = _as_tensor_field(E, "E")
    e1, e2, theta = _sym_eig2(*_components(E))
    return PrincipalStrain(e1=e1, e2=e2, theta_p=theta)


def engineering_shear(E: np.ndarray) -> np.ndarray:
    """``gamma_xy = 2 * E_xy``, the engineering shear component.

    Tensor shear and engineering shear differ by exactly the factor 2 that
    causes more unit confusion than any other convention in the field, so both
    are exposed explicitly and neither is implied.
    """
    E = _as_tensor_field(E, "E")
    return 2.0 * _components(E)[2]


def von_mises_strain(E: np.ndarray) -> np.ndarray:
    """Von Mises equivalent strain under plane stress and incompressibility.

    With ``e3 = -(e1 + e2)`` (incompressible, ``nu = 0.5``) the strain is already
    deviatoric, so ``e_eq = sqrt(2/3 * e_ij e_ij)`` reduces to

        e_eq = 2 / sqrt(3) * sqrt(e1^2 + e1 e2 + e2^2)

    which returns ``e`` for uniaxial ``(e, -e/2)``, as an equivalent measure
    must. Spec section 2.11 quotes the prefactor as ``2/3`` and asks for the
    explicit formula and its assumptions; ``2/3`` fails that uniaxial check by a
    factor of exactly ``sqrt(3)``, so the derived prefactor is used here and the
    discrepancy is recorded in the IR1-O2 report.

    The two assumptions are load-bearing: on an elastic metal (``nu ~ 0.3``)
    this overstates the equivalent strain, because the real ``e3`` is smaller
    than the incompressible one.
    """
    p = principal_strains(E)
    return (2.0 / np.sqrt(3.0)) * np.sqrt(p.e1**2 + p.e1 * p.e2 + p.e2**2)


def tresca_strain(E: np.ndarray) -> np.ndarray:
    """Tresca equivalent strain, ``max - min`` over all three principal strains.

    Uses the same incompressible out-of-plane closure ``e3 = -(e1 + e2)`` as
    :func:`von_mises_strain`. It equals the in-plane
    :attr:`PrincipalStrain.gamma_max` only when ``e3`` happens to lie between
    ``e1`` and ``e2``; for equibiaxial tension it does not, and the difference
    is a factor of 2. This is why the in-plane and the three-dimensional shear
    measures are separate functions rather than one convenient alias.
    """
    p = principal_strains(E)
    e3 = -(p.e1 + p.e2)
    stack = np.stack([p.e1, p.e2, e3], axis=0)
    return np.max(stack, axis=0) - np.min(stack, axis=0)


def dilatation(F: np.ndarray) -> np.ndarray:
    """Relative area change ``det(F) - 1`` of the imaged surface."""
    F = _as_tensor_field(F, "F")
    return F[..., 0, 0] * F[..., 1, 1] - F[..., 0, 1] * F[..., 1, 0] - 1.0


def rotation_angle(F: np.ndarray) -> np.ndarray:
    """In-plane rigid rotation from the polar decomposition ``F = R U``, radians.

    ``R`` is the rotation of angle ``atan2(F10 - F01, F00 + F11)``; the closed
    form is exact and needs no iteration in 2-D. Positive angles turn ``+x``
    towards ``+y``, i.e. clockwise on screen under the image convention where
    ``y`` points down. Entries with ``det(F) <= 0`` -- a reflection, which no
    physical deformation produces -- give ``nan``.
    """
    F = _as_tensor_field(F, "F")
    det = F[..., 0, 0] * F[..., 1, 1] - F[..., 0, 1] * F[..., 1, 0]
    angle = np.arctan2(F[..., 1, 0] - F[..., 0, 1], F[..., 0, 0] + F[..., 1, 1])
    with np.errstate(invalid="ignore"):
        return np.where(det > 0.0, angle, np.nan)
