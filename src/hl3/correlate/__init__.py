"""Correlation kernels for HL3.

Currently only the CPU reference first-order IC-GN (ZNSSD) solver is
implemented; GPU and second-order shape-function backends are future work and
must reproduce this module's numbers.
"""

from __future__ import annotations

from .icgn import (
    BSplineInterpolator,
    ICGNParams,
    ICGNResult,
    Status,
    compose_inverse,
    icgn_first_order,
    integer_search_fftcc,
    make_grid,
    reference_gradients,
    warp_matrix,
    warp_params,
)

__all__ = [
    "BSplineInterpolator",
    "ICGNParams",
    "ICGNResult",
    "Status",
    "compose_inverse",
    "icgn_first_order",
    "integer_search_fftcc",
    "make_grid",
    "reference_gradients",
    "warp_matrix",
    "warp_params",
]
