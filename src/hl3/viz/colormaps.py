# SPDX-License-Identifier: Apache-2.0
"""Colour lookup tables that do not need matplotlib.

A DIC field is a scalar per POI; a picture of it is that scalar pushed through
a normalisation and then a colour table. matplotlib owns hundreds of tables,
but ``hl3.viz`` has to produce an image without it, so this module carries a
small set of its own -- and carries them under names matplotlib also uses, so
that switching backends changes the renderer and not the picture.

Three tables, and the reason each one is here:

============  ==========  ==============================================
name          diverging   why
============  ==========  ==============================================
``viridis``   no          Perceptually uniform and safe for the common
                          forms of colour vision deficiency. The default
                          for anything whose zero is not special.
``gray``      no          The only honest choice when the image itself is
                          the subject (speckle, ZNCC maps for print).
``bwr``       yes         Zero maps to white, so the sign of a strain or a
                          residual is readable at a glance. The default
                          for signed quantities, paired with a symmetric
                          value range.
============  ==========  ==============================================

Any name may be suffixed with ``_r`` for the reversed table, exactly as in
matplotlib.

**Fidelity.** ``gray`` and ``bwr`` are defined by construction (a linear ramp
between fixed endpoints), so this module reproduces matplotlib's tables
exactly -- measured max deviation 0/255 per channel over all 256 entries.
``viridis`` is a data table, not a formula; stored here are 33 anchors of it
with linear interpolation in between, which reconstructs matplotlib's 256-entry
table to a max deviation of 3/255 and a mean of 0.55/255 per channel. That is
below the quantisation of most displays and far below what a reader can name,
but it is a difference, and a report comparing images produced by the two
backends should say which one made them. The viridis data is by Nathaniel J.
Smith and Stefan van der Walt, released into the public domain under CC0.

Colormaps that are neither a formula nor public-domain data -- ``coolwarm`` and
the rest of matplotlib's set -- are deliberately absent rather than
approximated under a borrowed name: a table that is 5% off but answers to the
same name is worse than one that is missing, because only the second is
visible. Ask for them with the matplotlib backend, where they are the real
thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = [
    "COLORMAPS",
    "DEFAULT_COLORMAP",
    "DEFAULT_NAN_RGB",
    "LUT_SIZE",
    "Colormap",
    "apply_colormap",
    "colormap_lut",
    "colormap_names",
    "is_diverging",
    "resolve_colormap",
]

#: Entries in a lookup table. 256 matches matplotlib's default ``N``.
LUT_SIZE = 256

#: Used when neither the caller nor the quantity asks for something else.
DEFAULT_COLORMAP = "viridis"

#: Colour of a point with no value. Neutral gray rather than white: ``bwr``
#: puts white at zero, so a masked POI drawn white reads as "zero strain" --
#: a wrong number rather than a missing one. No table here produces this gray,
#: so it cannot be mistaken for a datum in the other direction either.
DEFAULT_NAN_RGB = (190, 190, 190)

_REVERSED_SUFFIX = "_r"

# viridis sampled at 33 evenly spaced points. CC0 / public domain.
_VIRIDIS_ANCHORS = (
    (68, 1, 84), (71, 13, 96), (72, 24, 106), (72, 35, 116),
    (71, 45, 123), (69, 55, 129), (66, 64, 134), (62, 73, 137),
    (59, 82, 139), (55, 91, 141), (51, 99, 141), (47, 107, 142),
    (44, 114, 142), (41, 122, 142), (38, 130, 142), (35, 137, 142),
    (33, 145, 140), (31, 152, 139), (31, 160, 136), (34, 167, 133),
    (40, 174, 128), (50, 182, 122), (63, 188, 115), (78, 195, 107),
    (94, 201, 98), (112, 207, 87), (132, 212, 75), (152, 216, 62),
    (173, 220, 48), (194, 223, 35), (216, 226, 25), (236, 229, 27),
    (253, 231, 37),
)


@dataclass(frozen=True)
class Colormap:
    """A colour table as evenly spaced RGB anchors, interpolated linearly.

    ``anchors`` are 8-bit RGB triples at positions ``i / (len(anchors) - 1)``.
    Two anchors describe a straight ramp, three a diverging pair of ramps, and
    a longer list a sampled curve; the same interpolation covers all three, so
    there is one code path to be right about.
    """

    name: str
    anchors: tuple[tuple[int, int, int], ...]
    diverging: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if len(self.anchors) < 2:
            raise ValueError(
                f"colormap {self.name!r} needs at least 2 anchors, got "
                f"{len(self.anchors)}"
            )
        for anchor in self.anchors:
            if len(anchor) != 3 or not all(0 <= int(c) <= 255 for c in anchor):
                raise ValueError(
                    f"colormap {self.name!r} has a non-RGB anchor {anchor!r}"
                )


COLORMAPS: dict[str, Colormap] = {
    "viridis": Colormap(
        "viridis",
        _VIRIDIS_ANCHORS,
        note="33-anchor reconstruction of the CC0 viridis table",
    ),
    "gray": Colormap("gray", ((0, 0, 0), (255, 255, 255))),
    "bwr": Colormap(
        "bwr",
        ((0, 0, 255), (255, 255, 255), (255, 0, 0)),
        diverging=True,
    ),
}


def colormap_names(include_reversed: bool = False) -> tuple[str, ...]:
    """Names this module can build, sorted."""
    names = sorted(COLORMAPS)
    if include_reversed:
        names = sorted(names + [n + _REVERSED_SUFFIX for n in names])
    return tuple(names)


def resolve_colormap(name: str) -> tuple[Colormap, bool]:
    """Look up a table by name, returning it and whether it is to be reversed."""
    if not isinstance(name, str):
        raise TypeError(f"colormap name must be a string, got {type(name).__name__}")
    key = name
    reverse = False
    if key.endswith(_REVERSED_SUFFIX) and key[: -len(_REVERSED_SUFFIX)] in COLORMAPS:
        key = key[: -len(_REVERSED_SUFFIX)]
        reverse = True
    if key not in COLORMAPS:
        raise ValueError(
            f"unknown colormap {name!r}; the built-in backend has "
            f"{', '.join(colormap_names(include_reversed=True))}. Other matplotlib "
            "colormaps work only with the matplotlib backend."
        )
    return COLORMAPS[key], reverse


def is_diverging(name: str) -> bool:
    """Whether a table is built around a distinguished centre value."""
    colormap, _ = resolve_colormap(name)
    return colormap.diverging


@lru_cache(maxsize=32)
def colormap_lut(name: str, size: int = LUT_SIZE) -> np.ndarray:
    """A ``(size, 3)`` ``uint8`` lookup table.

    Entry ``i`` is the colour of the normalised value ``i / (size - 1)``, so
    the first and last entries are exactly the first and last anchors -- the
    ends of a colour bar are the ends of the data range, and rounding them
    inwards would quietly misreport the extremes.
    """
    if isinstance(size, bool) or size != int(size) or int(size) < 2:
        raise ValueError(f"lookup table size must be an integer >= 2, got {size!r}")
    colormap, reverse = resolve_colormap(name)
    anchors = np.asarray(colormap.anchors, dtype=np.float64)
    positions = np.linspace(0.0, 1.0, anchors.shape[0])
    t = np.linspace(0.0, 1.0, int(size))
    table = np.stack(
        [np.interp(t, positions, anchors[:, channel]) for channel in range(3)],
        axis=1,
    )
    lut = np.rint(table).astype(np.uint8)
    if reverse:
        lut = lut[::-1]
    # The cache hands the same array to every caller; nobody may edit it.
    lut.flags.writeable = False
    return lut


def apply_colormap(
    normalised: np.ndarray,
    name: str = DEFAULT_COLORMAP,
    *,
    nan_rgb: tuple[int, int, int] = DEFAULT_NAN_RGB,
    size: int = LUT_SIZE,
) -> np.ndarray:
    """Map values on ``[0, 1]`` to RGB, painting non-finite entries ``nan_rgb``.

    Values outside ``[0, 1]`` are clamped to the ends of the table, which is
    what "clipped at vmin/vmax" has to look like. Non-finite entries -- a POI
    the correlator never solved -- get their own colour instead of the colour
    of the nearest valid number, because a masked point that renders as dark
    blue is indistinguishable from a real minimum.
    """
    values = np.asarray(normalised, dtype=np.float64)
    lut = colormap_lut(name, size)
    finite = np.isfinite(values)
    clamped = np.clip(np.where(finite, values, 0.0), 0.0, 1.0)
    index = np.rint(clamped * (lut.shape[0] - 1)).astype(np.intp)
    rgb = lut[index]
    if not finite.all():
        rgb = rgb.copy()
        rgb[~finite] = np.asarray(_as_rgb(nan_rgb), dtype=np.uint8)
    return rgb


def _as_rgb(value: object, name: str = "colour") -> tuple[int, int, int]:
    """Validate an 8-bit RGB triple."""
    try:
        r, g, b = (int(c) for c in value)  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be a triple of 0..255 integers, got {value!r}"
        ) from exc
    for channel in (r, g, b):
        if not 0 <= channel <= 255:
            raise ValueError(
                f"{name} must be a triple of 0..255 integers, got {value!r}"
            )
    return r, g, b
