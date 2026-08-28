# SPDX-License-Identifier: Apache-2.0
"""Uncertainty quantification: from displacement covariance to strain sigma.

Stage S3 of the implementation plan, and the module behind the claim of spec
R1-O1 section 6.2 that HL3 reports uncertainty *by default* rather than leaving
it to the user as a manual GPG exercise. The calling surface is frozen in
``.agent_workspace/s1s4/IR2-F3-uq-contract.md`` section 2 and is exactly four
names::

    from hl3.uq import (
        DisplacementVariances,
        StrainStdField,
        displacement_variances,
        propagate_strain_std,
    )

    variances = displacement_variances(icgn_result)          # segment B
    std = propagate_strain_std(                              # segments C + D
        u_grid, v_grid,
        variances.u_var.reshape(grid_shape),
        variances.v_var.reshape(grid_shape),
        params, step_px=5.0,
        uv_cov=variances.uv_cov.reshape(grid_shape),
        valid=converged, check_against=strain,
    )
    exx_std = std.as_grid("exx_std")

What this package deliberately does not do is *invent* an uncertainty. It has no
noise model of its own: hand it a variance and it reports what that variance
implies about the strain, which is the part the strain window makes non-obvious.
Estimating the input is the job of the correlator (spec section 2.6) or of a
noise-floor measurement (section 6.2 item 2), and which one was used is recorded
in ``uncertainty/@method`` so a reader can tell them apart.

See :mod:`hl3.uq.propagate` for the propagation chain and, importantly, for the
four registered assumptions the numbers rest on.
"""

from __future__ import annotations

from .propagate import (
    DisplacementVariances,
    StrainStdField,
    displacement_variances,
    propagate_strain_std,
)

__all__ = [
    "DisplacementVariances",
    "StrainStdField",
    "displacement_variances",
    "propagate_strain_std",
]
