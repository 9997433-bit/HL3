# SPDX-License-Identifier: Apache-2.0
"""Virtual strain gauge (VSG) size, the one number a strain field cannot omit.

The VSG size is the spatial-resolution figure of a DIC strain field: the side
length of the image region that actually contributes to one strain value. It is
*not* an object the user places on the field -- that is a virtual extensometer
(spec R1-O1 section 1.7 keeps the two apart deliberately, because conflating
them is the most common misreading in practice).

iDICs GPG Eq. (7.2)::

    L_VSG = (L_window - 1) * L_step + L_subset          [px]
    L_VSG_mm = L_VSG / image_scale                      [mm]

``L_window`` counts *data points* (POI), not pixels; ``L_step`` and ``L_subset``
are pixels. The formula itself lives in :func:`hl3.io.hdf5_schema.vsg_size_px`
and is re-exported here rather than reimplemented: IR1-F4 section 10 item 2 and
gate G-S1-STR-1 both require exactly one copy of it in the tree, because a
second copy is how the reported gauge size and the stored ``@vsg_px`` attribute
drift apart. This module adds the things around it -- post-filter windows, the
millimetre conversion, the inverse used by VSG studies.

Windows are counted in POI and must be odd: a strain value belongs to the POI at
the centre of its fitting window, and an even window has no centre. The one
exception is ``window_pts = 1``, which is legal in the formula and means "no
local fit at all" -- the strain came straight out of the subset shape function,
so ``L_VSG = L_subset`` (spec section 2.11, ``FROM_SHAPE_FUNCTION``). The PLS
fitter in :mod:`hl3.strain.pls` needs at least 3.
"""

from __future__ import annotations

import math

from hl3.io.hdf5_schema import vsg_size_px as _schema_vsg_size_px

__all__ = [
    "effective_window_pts",
    "subset_px_from_radius",
    "vsg_size_mm",
    "vsg_size_px",
    "window_pts_for_vsg",
]

# How a post-filter window combines with the strain window into the single
# ``L_window`` that Eq. (7.2) takes.
_COMBINE_MODES = ("max", "cascade")


def _as_window_pts(value: int, name: str) -> int:
    """Validate a window measured in data points: odd, positive, integral."""
    if isinstance(value, bool) or value != int(value):
        raise ValueError(
            f"{name} must be an integer number of data points, got {value!r}"
        )
    window = int(value)
    if window < 1:
        raise ValueError(f"{name} must be >= 1 data point, got {window}")
    if window % 2 == 0:
        raise ValueError(
            f"{name} must be odd so the window has a centre point, got {window}"
        )
    return window


def _as_positive(value: float, name: str) -> float:
    x = float(value)
    if not math.isfinite(x) or x <= 0.0:
        raise ValueError(f"{name} must be finite and > 0, got {value!r}")
    return x


def subset_px_from_radius(subset_radius: int) -> int:
    """Full subset side length in pixels from the radius used by the correlator.

    :class:`hl3.correlate.ICGNParams` stores a radius; Eq. (7.2) wants the side
    length ``2 * radius + 1``. Converting in one named place keeps the
    off-by-one out of every call site.
    """
    if isinstance(subset_radius, bool) or subset_radius != int(subset_radius):
        raise ValueError(f"subset_radius must be an integer, got {subset_radius!r}")
    radius = int(subset_radius)
    if radius < 1:
        raise ValueError(f"subset_radius must be >= 1, got {radius}")
    return 2 * radius + 1


def effective_window_pts(
    window_pts: int,
    filter_window_pts: int | None = None,
    combine: str = "max",
) -> int:
    """The ``L_window`` that enters Eq. (7.2) once post-filtering is considered.

    Spec section 2.11 step 4: when a post-filter is enabled, its window is the
    one that enters the VSG formula. Two readings of "whichever actually takes
    effect" are supported, because they differ and the difference is reportable:

    * ``"max"`` (default, spec-conformant) -- the larger of the strain window
      and the filter window. For the usual case of a filter at least as wide as
      the strain window this is exactly "use the filter window".
    * ``"cascade"`` -- the support of the composition of the two windows,
      ``window + filter - 1``. This is the honest extent of the data that
      touches one output value when a ``W1`` fit is followed by a ``W2`` filter,
      and it is always the larger, more conservative number.

    ``"max"`` is the default so that reported numbers stay comparable with other
    GPG-conformant software; a report that uses ``"cascade"`` must say so.
    """
    window = _as_window_pts(window_pts, "window_pts")
    if filter_window_pts is None:
        return window
    filt = _as_window_pts(filter_window_pts, "filter_window_pts")
    if combine == "max":
        return max(window, filt)
    if combine == "cascade":
        return window + filt - 1
    raise ValueError(f"combine must be one of {_COMBINE_MODES}, got {combine!r}")


def vsg_size_px(
    window_pts: int,
    step_px: float,
    subset_px: int,
    filter_window_pts: int | None = None,
    combine: str = "max",
) -> float:
    """Virtual strain gauge size in pixels, iDICs GPG Eq. (7.2).

    Thin wrapper around :func:`hl3.io.hdf5_schema.vsg_size_px`, which owns the
    arithmetic; this adds the post-filter window rule of
    :func:`effective_window_pts` and validation messages in the vocabulary of
    this package. ``subset_px`` is the full subset side length -- use
    :func:`subset_px_from_radius` to convert from a correlator radius.
    """
    window = effective_window_pts(window_pts, filter_window_pts, combine)
    step = _as_positive(step_px, "step_px")
    subset = _as_window_pts(subset_px, "subset_px")
    if step < 1.0:
        raise ValueError(f"step_px must be >= 1 px, got {step_px!r}")
    return _schema_vsg_size_px(window, step, subset)


def vsg_size_mm(vsg_px: float, image_scale_px_per_mm: float) -> float:
    """Convert a VSG size to millimetres given the image scale in px/mm.

    The GPG asks for both units in the report, and they carry different
    information: pixels compare analyses of the same images, millimetres compare
    analyses of the same specimen.
    """
    px = _as_positive(vsg_px, "vsg_px")
    scale = _as_positive(image_scale_px_per_mm, "image_scale_px_per_mm")
    return px / scale


def window_pts_for_vsg(target_vsg_px: float, step_px: float, subset_px: int) -> int:
    """Smallest odd window whose VSG reaches ``target_vsg_px``.

    The inverse of Eq. (7.2), for the VSG study of spec section 1.3 step 5 and
    for matching the gauge length of a physical strain gauge. The result is
    clamped at 1 because no choice of window makes the VSG smaller than the
    subset -- when the target is below ``subset_px`` the honest answer is "not
    reachable with this subset", and the caller can detect that by feeding the
    returned window back through :func:`vsg_size_px`.
    """
    target = _as_positive(target_vsg_px, "target_vsg_px")
    step = _as_positive(step_px, "step_px")
    subset = _as_window_pts(subset_px, "subset_px")
    raw = (target - subset) / step + 1.0
    if raw <= 1.0:
        return 1
    window = math.ceil(raw - 1e-12)
    if window % 2 == 0:
        window += 1
    return window
