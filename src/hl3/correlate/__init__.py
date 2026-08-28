"""Correlation kernels for HL3.

The CPU reference IC-GN (ZNSSD) solver comes in two shape-function orders:
first order (affine, 6 parameters) via :func:`icgn_first_order` and second
order (quadratic, 12 parameters) via :func:`icgn_second_order`; :func:`icgn`
dispatches on :attr:`ICGNParams.shape_order`. GPU backends are future work and
must reproduce this module's numbers.
"""

from __future__ import annotations

from .icgn import (
    BSplineInterpolator,
    ICGNParams,
    ICGNResult,
    Status,
    compose_inverse,
    compose_inverse_second_order,
    first_to_second_order,
    icgn,
    icgn_first_order,
    icgn_second_order,
    integer_search_fftcc,
    make_grid,
    reference_gradients,
    second_to_first_order,
    shape_param_count,
    shape_param_labels,
    warp_matrix,
    warp_matrix_second_order,
    warp_params,
    warp_params_second_order,
)

__all__ = [
    "BSplineInterpolator",
    "ICGNParams",
    "ICGNResult",
    "Status",
    "compose_inverse",
    "compose_inverse_second_order",
    "first_to_second_order",
    "icgn",
    "icgn_first_order",
    "icgn_second_order",
    "integer_search_fftcc",
    "make_grid",
    "reference_gradients",
    "second_to_first_order",
    "shape_param_count",
    "shape_param_labels",
    "warp_matrix",
    "warp_matrix_second_order",
    "warp_params",
    "warp_params_second_order",
]
