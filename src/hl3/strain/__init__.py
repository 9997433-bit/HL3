# SPDX-License-Identifier: Apache-2.0
"""Strain from DIC displacement fields: PLS gradients, tensor family, VSG.

Round IR1 (stage S1) implementation of spec R1-O1 sections 1.6, 1.7 and 2.11 --
the ``hl3_strain`` module of the architecture in section 4.1 -- against the
calling surface frozen in ``.agent_workspace/s1s4/IR1-F3-public-api.md``. NumPy
only, double precision, vectorised over the whole POI grid.

Three pieces, in the order data flows through them:

1. :mod:`hl3.strain.pls` -- pointwise least squares fit of the displacement grid
   (Pan et al. 2007), giving ``u_x, u_y, v_x, v_y`` with an explicit validity
   rule instead of a differenced noise amplifier;
2. :mod:`hl3.strain.tensors` -- deformation gradient, the engineering /
   Green-Lagrange / Euler-Almansi / Hencky family, principal values and
   equivalent measures;
3. :mod:`hl3.strain.vsg` -- the virtual strain gauge size of iDICs GPG Eq. (7.2),
   which is what makes a strain number comparable between analyses.

:func:`compute_strain` runs all three from one :class:`StrainParams` and returns
the :class:`StrainField` that ``hl3.pipeline`` re-exports::

    from hl3.strain import StrainParams, compute_strain

    strain = compute_strain(u_grid, v_grid, StrainParams(window_pts=5),
                            step_px=5, subset_px=21, valid=converged)
    exx_map = strain.as_grid("exx")
    assert strain.vsg_px == 41.0

Implemented here, and deliberately not more: the PLS route to strain. The three
alternatives of spec section 2.11 -- ``FROM_SHAPE_FUNCTION`` (strain straight out
of the correlator's shape-function parameters, ``L_VSG = L_subset``),
``FE_SHAPE_FUNCTION`` and ``GLOBAL_SPLINE`` -- are future work; the VSG module
already handles the ``window_pts = 1`` case that the first of them reports.
Post-filtering (spec section 2.11 step 4) is likewise not applied here, but
:func:`effective_window_pts` exists so that a filter applied downstream still
lands in the VSG size, which is the part that must not be lost.
"""

from __future__ import annotations

from .field import (
    StrainField,
    StrainParams,
    compute_strain,
    grid_from_points,
)
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
    TENSOR_KINDS,
    PrincipalStrain,
    deformation_gradient,
    dilatation,
    engineering_shear,
    engineering_strain,
    euler_almansi_strain,
    green_lagrange_strain,
    hencky_strain,
    principal_strains,
    rotation_angle,
    strain_tensor,
    tresca_strain,
    von_mises_strain,
)
from .vsg import (
    effective_window_pts,
    subset_px_from_radius,
    vsg_size_mm,
    vsg_size_px,
    window_pts_for_vsg,
)

__all__ = [
    "DEFAULT_FIT_ORDER",
    "DEFAULT_MIN_VALID_FRACTION",
    "DEFAULT_WEIGHTING",
    "DEFAULT_WINDOW_PTS",
    "TENSOR_KINDS",
    "GradientField",
    "PrincipalStrain",
    "StrainField",
    "StrainParams",
    "compute_strain",
    "deformation_gradient",
    "dilatation",
    "effective_window_pts",
    "engineering_shear",
    "engineering_strain",
    "euler_almansi_strain",
    "green_lagrange_strain",
    "grid_from_points",
    "hencky_strain",
    "neighbor_min_for",
    "pls_gradients",
    "principal_strains",
    "rotation_angle",
    "strain_tensor",
    "subset_px_from_radius",
    "tresca_strain",
    "von_mises_strain",
    "vsg_size_mm",
    "vsg_size_px",
    "window_pts_for_vsg",
]
