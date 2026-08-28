# SPDX-License-Identifier: Apache-2.0
"""Colour maps of a 2D DIC field, with or without matplotlib installed.

The picture of a displacement or strain field is how almost everyone reads a
DIC result, so it cannot be the part of the toolkit that needs an extra install
to work. This module renders ``u``, ``v``, ``exx`` and the rest of the field
family two ways:

* **matplotlib backend** -- a real figure: axes, tick labels, a labelled colour
  bar, and PNG/PDF/SVG output. Used automatically when matplotlib is
  importable.
* **built-in backend** -- NumPy for the colour mapping,
  :mod:`hl3.viz.imwrite` for the bytes. It produces a PNG (or a Netpbm
  ``.ppm``/``.pgm``) with the field, a colour bar and numeric end labels drawn
  from a 3x5 pixel font, and it needs nothing that is not already a dependency
  of ``hl3``.

Both backends are driven by one :class:`PlotStyle` and one :func:`value_range`,
so the two pictures agree on the thing that decides what a field *looks* like:
the value-to-colour mapping. The frame around it differs -- the built-in
backend has no fonts, so it labels the colour bar with numbers and nothing
else -- and :attr:`FieldImage.backend` records which one drew the file, because
a figure in a report should be attributable.

Three defaults worth knowing, all of them reversible:

1. **Signed quantities get a symmetric range and a diverging table.** ``exx``
   on ``[-e, +e]`` with white at zero shows tension and compression as
   different colours; the same field auto-scaled to ``[min, max]`` puts the
   colour boundary at whatever the extremes happened to be, and the sign of the
   strain stops being readable. Displacements auto-scale, because their zero is
   the choice of reference, not a material state.
2. **Non-converged points are painted, not interpolated.** They arrive as NaN
   from :meth:`hl3.pipeline.Dic2DRun.field` and leave as ``style.nan_rgb``, a
   gray no colour table in this package produces. A masked point that renders
   as "dark blue" reads as a minimum.
3. **A sequence is scaled once.** :func:`save_run_field` takes its range from
   the whole run rather than the frame being drawn, so consecutive frames are
   comparable. Pass ``scope="frame"`` for per-frame auto-scaling.

Nothing here interprets the numbers. A field is an array with a name; the units
come from the caller (or, in :func:`save_run_field`, from the run type), and no
smoothing, interpolation or contouring is applied between the data and the
pixels -- one POI is one square of colour, which is the only rendering that
cannot invent spatial resolution the correlation never had.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from .colormaps import (
    DEFAULT_COLORMAP,
    DEFAULT_NAN_RGB,
    apply_colormap,
    colormap_names,
    is_diverging,
)
from .colormaps import _as_rgb as _as_rgb_triple
from .imwrite import IMAGE_FORMATS, format_for_path, write_image

__all__ = [
    "BACKEND_ENV_VAR",
    "DEFAULT_NAN_RGB",
    "MATPLOTLIB_FORMATS",
    "QUANTITIES",
    "Backend",
    "FieldImage",
    "PlotStyle",
    "QuantitySpec",
    "ValueRange",
    "colormap_choices",
    "matplotlib_available",
    "normalise",
    "quantity_spec",
    "render_field",
    "resolve_backend",
    "run_field",
    "save_field",
    "save_field_png",
    "save_run_field",
    "value_range",
]

#: Set to ``builtin`` or ``matplotlib`` to pin the backend for a whole process.
#: A CI lane that wants byte-reproducible figures sets it to ``builtin``.
BACKEND_ENV_VAR = "HL3_VIZ_BACKEND"

#: File formats the matplotlib backend can write.
MATPLOTLIB_FORMATS: tuple[str, ...] = ("png", "pdf", "svg")

# Built-in colour bar geometry, in pixels before any text scaling.
_BAR_WIDTH = 14
_BAR_GAP = 8
_TEXT_GAP = 4
_BAR_EDGE_RGB = (90, 90, 90)
_TEXT_RGB = (0, 0, 0)

# Guard against a scale factor turning a POI grid into a gigapixel canvas.
_MAX_OUTPUT_PIXELS = 64_000_000


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


class Backend(enum.Enum):
    """Which renderer draws the file."""

    AUTO = "auto"
    MATPLOTLIB = "matplotlib"
    BUILTIN = "builtin"


def matplotlib_available() -> bool:
    """Whether matplotlib can be imported in this interpreter.

    Import failure is treated as absence whatever its cause: a broken install
    is as unusable as a missing one, and the built-in backend covers both.
    """
    try:  # noqa: SIM105 - the point is the boolean, not the exception
        import matplotlib  # noqa: F401
    except Exception:
        return False
    return True


def _as_backend(backend: Backend | str) -> Backend:
    if isinstance(backend, Backend):
        return backend
    try:
        return Backend(str(backend).lower())
    except ValueError:
        raise ValueError(
            f"unknown backend {backend!r}; expected one of "
            + ", ".join(b.value for b in Backend)
        ) from None


def resolve_backend(
    backend: Backend | str = Backend.AUTO,
    image_format: str = "png",
) -> Backend:
    """Turn ``AUTO`` into the backend that will actually run.

    ``AUTO`` prefers matplotlib when it is importable *and* can write the
    requested format, and falls back to the built-in renderer otherwise, so a
    ``.ppm`` request never fails just because matplotlib happens to be
    installed. An explicit choice is honoured or refused, never silently
    downgraded: a report that says "matplotlib" must not have been drawn by
    something else.
    """
    requested = _as_backend(backend)
    fmt = image_format.lower().lstrip(".")
    if requested is Backend.AUTO:
        override = os.environ.get(BACKEND_ENV_VAR, "").strip().lower()
        if override:
            requested = _as_backend(override)
    if requested is Backend.AUTO:
        if fmt in MATPLOTLIB_FORMATS and matplotlib_available():
            return Backend.MATPLOTLIB
        if fmt in IMAGE_FORMATS:
            return Backend.BUILTIN
        raise ValueError(
            f"no backend can write {fmt!r}; matplotlib writes "
            f"{', '.join(MATPLOTLIB_FORMATS)} and the built-in backend writes "
            f"{', '.join(IMAGE_FORMATS)}"
        )
    if requested is Backend.MATPLOTLIB:
        if not matplotlib_available():
            raise ImportError(
                "the matplotlib backend was requested explicitly but matplotlib "
                "is not importable; install hl3[viz] or use backend='builtin'"
            )
        if fmt not in MATPLOTLIB_FORMATS:
            raise ValueError(
                f"the matplotlib backend does not write {fmt!r} here; it writes "
                f"{', '.join(MATPLOTLIB_FORMATS)}"
            )
        return Backend.MATPLOTLIB
    if fmt not in IMAGE_FORMATS:
        raise ValueError(
            f"the built-in backend does not write {fmt!r}; it writes "
            f"{', '.join(IMAGE_FORMATS)}"
        )
    return Backend.BUILTIN


# --------------------------------------------------------------------------
# Quantities
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantitySpec:
    """How one named field wants to be drawn, before the caller overrides it.

    ``source`` says where a run keeps it: ``"field"`` for
    :meth:`hl3.pipeline.Dic2DRun.field` (displacement and per-point
    bookkeeping), ``"strain"`` for :meth:`~hl3.pipeline.Dic2DRun.strain_field`.
    :func:`run_field` needs it because the two accessors raise different errors
    for the same mistake.
    """

    name: str
    label: str
    colormap: str
    symmetric: bool
    source: str = "field"


def _spec(
    name: str, label: str, colormap: str, symmetric: bool, source: str = "field"
) -> QuantitySpec:
    return QuantitySpec(name, label, colormap, symmetric, source)


#: Drawing defaults per field name. Names match the accessors on
#: :class:`hl3.pipeline.Dic2DRun` / :class:`hl3.pipeline.Dic3DRun` and the
#: schema names of :class:`hl3.strain.StrainField`, so a quantity is spelled
#: the same way everywhere it appears.
QUANTITIES: dict[str, QuantitySpec] = {
    q.name: q
    for q in (
        # Displacement: the zero is where the reference happened to be, so the
        # range is not forced symmetric.
        _spec("u", "u", "viridis", False),
        _spec("v", "v", "viridis", False),
        _spec("w", "w", "viridis", False),
        _spec("magnitude", "|U|", "viridis", False),
        # Strain: the sign is a material state. Symmetric range, white at zero.
        _spec("exx", "exx", "bwr", True, "strain"),
        _spec("eyy", "eyy", "bwr", True, "strain"),
        _spec("exy", "exy", "bwr", True, "strain"),
        _spec("e1", "e1", "bwr", True, "strain"),
        _spec("e2", "e2", "bwr", True, "strain"),
        # Non-negative by construction; a symmetric range would waste half the
        # colour table on values that cannot occur.
        _spec("gamma_max", "gamma_max", "viridis", False, "strain"),
        _spec("von_mises", "von Mises strain", "viridis", False, "strain"),
        # Quality maps.
        _spec("zncc", "ZNCC", "viridis", False),
        _spec("zncc_left", "ZNCC (left)", "viridis", False),
        _spec("zncc_right", "ZNCC (right)", "viridis", False),
        _spec("position_sigma_mm", "position sigma", "viridis", False),
        _spec("loop_px", "loop closure", "viridis", False),
        _spec("reprojection_px", "reprojection", "viridis", False),
    )
}


def quantity_spec(name: str | None) -> QuantitySpec | None:
    """The drawing defaults for a quantity, or ``None`` when it has no name.

    An unregistered name is an error rather than a silent default: it is
    usually a typo, and a typo that renders looks exactly like a result.
    """
    if name is None:
        return None
    if not isinstance(name, str):
        raise TypeError(f"quantity must be a string or None, got {type(name).__name__}")
    if name not in QUANTITIES:
        raise ValueError(
            f"unknown quantity {name!r}; known quantities are "
            + ", ".join(sorted(QUANTITIES))
            + ". Pass quantity=None to draw an unnamed array."
        )
    return QUANTITIES[name]


def _named_quantity(name: str) -> QuantitySpec:
    """:func:`quantity_spec` where a name is mandatory, e.g. reading from a run."""
    if name is None:
        raise TypeError(
            "quantity is required here; name the field to read, one of "
            + ", ".join(sorted(QUANTITIES))
        )
    return QUANTITIES[quantity_spec(name).name]  # type: ignore[union-attr]


# --------------------------------------------------------------------------
# Value range
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueRange:
    """The value-to-colour mapping of one picture, and how it was reached.

    Kept as data rather than two floats because a colour scale is a claim
    about the data: how many points it covers (``n_finite`` of ``n_total``),
    how many it clips at each end, and whether it had to be widened because the
    field is constant. A caption can be written from this; ``vmin``/``vmax``
    alone cannot say whether a saturated red patch is a real maximum or a
    percentile cut.
    """

    vmin: float
    vmax: float
    n_total: int
    n_finite: int
    n_below: int
    n_above: int
    symmetric: bool
    degenerate: bool
    empty: bool

    @property
    def span(self) -> float:
        return self.vmax - self.vmin

    @property
    def clipped(self) -> int:
        """Finite points that fall outside the range and render saturated."""
        return self.n_below + self.n_above

    @property
    def n_masked(self) -> int:
        """Points with no value: non-converged POI and points off the AOI."""
        return self.n_total - self.n_finite


def _nonsingular(vmin: float, vmax: float, expander: float = 1e-3) -> tuple[float, float]:
    """Widen a zero-width range so it can still be divided by.

    Mirrors ``matplotlib.transforms.nonsingular`` (same rule, same expander) so
    that a constant field renders identically under both backends instead of
    coming out flat under one and mid-scale under the other.
    """
    if vmax > vmin:
        return vmin, vmax
    if vmin == 0.0 and vmax == 0.0:
        return -expander, expander
    return vmin - expander * abs(vmin), vmax + expander * abs(vmax)


def value_range(
    values: Any,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
    symmetric: bool = False,
    percentile: tuple[float, float] | None = None,
) -> ValueRange:
    """The colour range for an array, from explicit limits or from the data.

    Accepts any shape, so the range for a whole sequence is
    ``value_range(run.field("u"))`` and the range for one frame is the same
    call on one slice. Order of decisions:

    1. a limit the caller gave is used as given;
    2. otherwise the data decides -- the finite min and max, or the
       ``percentile`` pair when one is supplied (``(2, 98)`` keeps a single
       blown-out POI from flattening the whole field);
    3. ``symmetric`` then mirrors the auto-chosen side about zero, but never
       moves a limit the caller pinned;
    4. a range that came out empty (all points masked) becomes ``[0, 1]``, and
       a zero-width one is widened by :func:`_nonsingular`. Both are flagged on
       the result rather than hidden, because "the field is constant" and "the
       field spans 1e-9" produce the same picture and must not read the same.
    """
    array = np.asarray(values, dtype=np.float64)
    finite_mask = np.isfinite(array)
    finite = array[finite_mask]
    n_total = int(array.size)
    n_finite = int(finite.size)

    if percentile is not None:
        low, high = (float(p) for p in percentile)
        if not 0.0 <= low < high <= 100.0:
            raise ValueError(
                f"percentile must be (low, high) with 0 <= low < high <= 100, "
                f"got {percentile!r}"
            )
    if vmin is not None and not np.isfinite(float(vmin)):
        raise ValueError(f"vmin must be finite, got {vmin!r}")
    if vmax is not None and not np.isfinite(float(vmax)):
        raise ValueError(f"vmax must be finite, got {vmax!r}")
    if vmin is not None and vmax is not None and float(vmin) > float(vmax):
        raise ValueError(f"vmin {vmin!r} is above vmax {vmax!r}")

    empty = n_finite == 0
    if empty:
        auto_low, auto_high = 0.0, 1.0
    elif percentile is not None:
        auto_low, auto_high = (
            float(x) for x in np.percentile(finite, [percentile[0], percentile[1]])
        )
    else:
        auto_low, auto_high = float(finite.min()), float(finite.max())

    if symmetric and not empty:
        extent = max(abs(auto_low), abs(auto_high))
        auto_low, auto_high = -extent, extent

    low = auto_low if vmin is None else float(vmin)
    high = auto_high if vmax is None else float(vmax)
    if low > high:
        # Only reachable when one side was pinned across the data; the pinned
        # value wins and the other collapses onto it.
        low, high = (high, high) if vmin is None else (low, low)
    degenerate = not (high > low)
    low, high = _nonsingular(low, high)

    return ValueRange(
        vmin=low,
        vmax=high,
        n_total=n_total,
        n_finite=n_finite,
        n_below=int(np.count_nonzero(finite < low)) if n_finite else 0,
        n_above=int(np.count_nonzero(finite > high)) if n_finite else 0,
        symmetric=bool(symmetric),
        degenerate=bool(degenerate),
        empty=bool(empty),
    )


def normalise(values: Any, values_range: ValueRange) -> np.ndarray:
    """Map a field onto ``[0, 1]`` for a colour table, keeping NaN as NaN.

    Values outside the range are *not* clipped here -- the colour mapper clips
    them, and :class:`ValueRange` has already counted them, so a caller
    inspecting the normalised array can still see which way a point ran off.
    """
    array = np.asarray(values, dtype=np.float64)
    span = values_range.vmax - values_range.vmin
    if span <= 0.0:  # pragma: no cover - _nonsingular rules this out
        raise ValueError("value range has non-positive span")
    return (array - values_range.vmin) / span


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlotStyle:
    """Everything about a figure that is a choice rather than data.

    The fields divide in two. ``colormap`` through ``percentile`` decide the
    value-to-colour mapping and mean the same thing in both backends. The rest
    -- ``scale``, ``margin``, ``dpi``, ``figsize`` -- are backend-specific
    framing: the built-in renderer works in pixels per POI, matplotlib works in
    inches and dots per inch, and neither can honour the other's numbers.
    """

    colormap: str | None = None
    vmin: float | None = None
    vmax: float | None = None
    symmetric: bool | None = None
    percentile: tuple[float, float] | None = None
    nan_rgb: tuple[int, int, int] = DEFAULT_NAN_RGB
    background_rgb: tuple[int, int, int] = (255, 255, 255)
    origin: str = "upper"
    colorbar: bool = True
    annotate: bool = True
    title: str | None = None
    label: str | None = None
    unit: str | None = None
    # Built-in backend only.
    scale: int = 1
    margin: int = 0
    text_scale: int | None = None
    compress_level: int = 6
    # matplotlib backend only.
    dpi: int = 150
    figsize: tuple[float, float] = (6.0, 4.5)

    def __post_init__(self) -> None:
        if self.colormap is not None and not isinstance(self.colormap, str):
            raise TypeError("colormap must be a string or None")
        for name in ("vmin", "vmax"):
            limit = getattr(self, name)
            if limit is not None and not np.isfinite(float(limit)):
                raise ValueError(f"{name} must be finite or None, got {limit!r}")
        if self.origin not in ("upper", "lower"):
            raise ValueError(
                f"origin must be 'upper' or 'lower', got {self.origin!r}"
            )
        _as_rgb_triple(self.nan_rgb, "nan_rgb")
        _as_rgb_triple(self.background_rgb, "background_rgb")
        _positive_int(self.scale, "scale")
        _non_negative_int(self.margin, "margin")
        if self.text_scale is not None:
            _positive_int(self.text_scale, "text_scale")
        if not 0 <= int(self.compress_level) <= 9:
            raise ValueError(
                f"compress_level must be in 0..9, got {self.compress_level!r}"
            )
        if self.dpi <= 0 or not np.isfinite(self.dpi):
            raise ValueError(f"dpi must be > 0, got {self.dpi!r}")
        if len(self.figsize) != 2 or any(
            not np.isfinite(x) or x <= 0 for x in self.figsize
        ):
            raise ValueError(f"figsize must be two positive numbers, got {self.figsize!r}")
        if self.percentile is not None:
            low, high = (float(p) for p in self.percentile)
            if not 0.0 <= low < high <= 100.0:
                raise ValueError(
                    f"percentile must be (low, high) with 0 <= low < high <= 100, "
                    f"got {self.percentile!r}"
                )

    def resolved_colormap(self, spec: QuantitySpec | None) -> str:
        if self.colormap is not None:
            return self.colormap
        return spec.colormap if spec is not None else DEFAULT_COLORMAP

    def resolved_symmetric(self, spec: QuantitySpec | None, colormap: str) -> bool:
        """Whether to centre the range on zero.

        An explicit choice wins; then the quantity's; then the colour table's
        own nature, so that asking for ``bwr`` on an unnamed array still puts
        white at zero instead of somewhere arbitrary.
        """
        if self.symmetric is not None:
            return bool(self.symmetric)
        if spec is not None:
            return spec.symmetric
        try:
            return is_diverging(colormap)
        except ValueError:
            return False

    def resolved_label(self, spec: QuantitySpec | None) -> str:
        if self.label is not None:
            base = self.label
        elif spec is not None:
            base = spec.label
        else:
            base = ""
        if self.unit:
            return f"{base} [{self.unit}]".strip()
        return base


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or value != int(value) or int(value) < 1:
        raise ValueError(f"{name} must be an integer >= 1, got {value!r}")
    return int(value)


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or value != int(value) or int(value) < 0:
        raise ValueError(f"{name} must be an integer >= 0, got {value!r}")
    return int(value)


# --------------------------------------------------------------------------
# A 3x5 pixel font, enough to label a colour bar
# --------------------------------------------------------------------------

_GLYPH_W, _GLYPH_H = 3, 5

# Only the characters ``format(x, '.4g')`` can produce, plus a box for anything
# else. A colour bar needs numbers; text needs a font, and a font is not a
# thing to hand-roll.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "0": ("###", "# #", "# #", "# #", "###"),
    "1": (" # ", "## ", " # ", " # ", "###"),
    "2": ("###", "  #", "###", "#  ", "###"),
    "3": ("###", "  #", "###", "  #", "###"),
    "4": ("# #", "# #", "###", "  #", "  #"),
    "5": ("###", "#  ", "###", "  #", "###"),
    "6": ("###", "#  ", "###", "# #", "###"),
    "7": ("###", "  #", " # ", " # ", " # "),
    "8": ("###", "# #", "###", "# #", "###"),
    "9": ("###", "# #", "###", "  #", "###"),
    "+": ("   ", " # ", "###", " # ", "   "),
    "-": ("   ", "   ", "###", "   ", "   "),
    ".": ("   ", "   ", "   ", "   ", " # "),
    "e": ("   ", "###", "#  ", "###", "   "),
    "n": ("   ", "## ", "# #", "# #", "   "),
    "a": ("   ", "###", "# #", "# #", "   "),
    "i": (" # ", "   ", " # ", " # ", "   "),
    "f": (" ##", " # ", "###", " # ", " # "),
    " ": ("   ", "   ", "   ", "   ", "   "),
}
_UNKNOWN_GLYPH = ("###", "# #", "# #", "# #", "###")

_GLYPH_ADVANCE = _GLYPH_W + 1


def _text_width(text: str, scale: int) -> int:
    if not text:
        return 0
    return (_GLYPH_ADVANCE * len(text) - 1) * scale


def _draw_text(
    canvas: np.ndarray,
    top: int,
    left: int,
    text: str,
    scale: int,
    rgb: tuple[int, int, int] = _TEXT_RGB,
) -> None:
    """Blit ``text`` at ``(top, left)``; anything off-canvas is dropped."""
    colour = np.asarray(rgb, dtype=np.uint8)
    height, width = canvas.shape[:2]
    for position, char in enumerate(text):
        glyph = _GLYPHS.get(char, _UNKNOWN_GLYPH)
        x0 = left + position * _GLYPH_ADVANCE * scale
        for row, line in enumerate(glyph):
            for column, pixel in enumerate(line):
                if pixel == " ":
                    continue
                y = top + row * scale
                x = x0 + column * scale
                if y + scale <= 0 or x + scale <= 0 or y >= height or x >= width:
                    continue
                canvas[max(y, 0) : y + scale, max(x, 0) : x + scale] = colour


def _format_value(value: float) -> str:
    """A short label for a colour-bar end, in the characters the font has."""
    if not np.isfinite(value):
        return "nan" if np.isnan(value) else ("inf" if value > 0 else "-inf")
    text = f"{value:.4g}"
    return text.replace("E", "e")


def _auto_text_scale(height: int) -> int:
    """Pick a font size from the image height, clamped to something legible."""
    return int(max(1, min(6, round(height / 120.0))))


# --------------------------------------------------------------------------
# Built-in rendering
# --------------------------------------------------------------------------


def _as_field(field: Any, name: str = "field") -> np.ndarray:
    array = np.asarray(field, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(
            f"{name} must be a 2D (ny, nx) grid, got shape {array.shape}; "
            "index the frame first, e.g. run.field('u')[frame]"
        )
    if array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError(f"{name} must be non-empty, got shape {array.shape}")
    return array


def _field_rgb(
    field: np.ndarray,
    colormap: str,
    values: ValueRange,
    style: PlotStyle,
) -> np.ndarray:
    """The data area alone: one square of colour per POI, upscaled by ``scale``."""
    oriented = field if style.origin == "upper" else field[::-1]
    rgb = apply_colormap(
        normalise(oriented, values), colormap, nan_rgb=tuple(style.nan_rgb)
    )
    if style.scale > 1:
        rgb = np.repeat(np.repeat(rgb, style.scale, axis=0), style.scale, axis=1)
    return rgb


def _colorbar_rgb(colormap: str, height: int, width: int) -> np.ndarray:
    """A vertical gradient with a one-pixel frame, high value at the top."""
    ramp = np.linspace(1.0, 0.0, height)
    column = apply_colormap(ramp, colormap)
    bar = np.repeat(column[:, None, :], width, axis=1)
    edge = np.asarray(_BAR_EDGE_RGB, dtype=np.uint8)
    bar[0, :] = bar[-1, :] = edge
    bar[:, 0] = bar[:, -1] = edge
    return bar


def render_field(
    field: Any,
    *,
    quantity: str | None = None,
    style: PlotStyle | None = None,
) -> np.ndarray:
    """Render a field to an ``(h, w, 3)`` ``uint8`` RGB array, no file involved.

    With ``colorbar=False`` and ``margin=0`` the result is exactly
    ``(ny * scale, nx * scale, 3)`` -- one POI per square, nothing added -- so
    the array can be composited, diffed against a reference, or handed to
    :mod:`hl3.viz.imwrite` unchanged.
    """
    rgb, _, _ = _render(field, quantity, style or PlotStyle())
    return rgb


def _render(
    field: Any,
    quantity: str | None,
    style: PlotStyle,
) -> tuple[np.ndarray, ValueRange, str]:
    array = _as_field(field)
    spec = quantity_spec(quantity)
    colormap = style.resolved_colormap(spec)
    symmetric = style.resolved_symmetric(spec, colormap)
    values = value_range(
        array,
        vmin=style.vmin,
        vmax=style.vmax,
        symmetric=symmetric,
        percentile=style.percentile,
    )

    data = _field_rgb(array, colormap, values, style)
    data_h, data_w = data.shape[:2]
    text_scale = style.text_scale or _auto_text_scale(data_h)

    labels: list[str] = []
    if style.colorbar and style.annotate:
        midpoint = 0.5 * (values.vmin + values.vmax)
        labels = [
            _format_value(values.vmax),
            _format_value(midpoint),
            _format_value(values.vmin),
        ]
    text_w = max((_text_width(text, text_scale) for text in labels), default=0)

    extra_w = 0
    if style.colorbar:
        extra_w = _BAR_GAP + _BAR_WIDTH
        if text_w:
            extra_w += _TEXT_GAP + text_w

    margin = style.margin
    canvas_h = data_h + 2 * margin
    canvas_w = data_w + extra_w + 2 * margin
    if canvas_h * canvas_w > _MAX_OUTPUT_PIXELS:
        raise ValueError(
            f"the requested image is {canvas_w}x{canvas_h} px, above the "
            f"{_MAX_OUTPUT_PIXELS} pixel guard; lower style.scale"
        )

    if extra_w == 0 and margin == 0:
        return data, values, colormap

    canvas = np.empty((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:, :] = np.asarray(style.background_rgb, dtype=np.uint8)
    canvas[margin : margin + data_h, margin : margin + data_w] = data

    if style.colorbar:
        bar_x = margin + data_w + _BAR_GAP
        canvas[margin : margin + data_h, bar_x : bar_x + _BAR_WIDTH] = _colorbar_rgb(
            colormap, data_h, _BAR_WIDTH
        )
        if labels:
            glyph_h = _GLYPH_H * text_scale
            text_x = bar_x + _BAR_WIDTH + _TEXT_GAP
            tops = (
                margin,
                margin + (data_h - glyph_h) // 2,
                margin + data_h - glyph_h,
            )
            for text, top in zip(labels, tops):
                _draw_text(canvas, top, text_x, text, text_scale)

    return canvas, values, colormap


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldImage:
    """What was written, and the mapping it was written with.

    Returned by every save function so that a caption, a provenance record or a
    test can be built from the call itself instead of by re-deriving the colour
    scale afterwards.
    """

    path: Path
    backend: str
    image_format: str
    colormap: str
    values: ValueRange
    width: int
    height: int
    bytes_written: int
    quantity: str | None = None
    label: str = ""
    image: np.ndarray | None = None

    @property
    def vmin(self) -> float:
        return self.values.vmin

    @property
    def vmax(self) -> float:
        return self.values.vmax


def _to_gray(rgb: np.ndarray, image_format: str, colormap: str) -> np.ndarray:
    """Collapse an RGB rendering to one channel for PGM, or refuse to."""
    if np.array_equal(rgb[..., 0], rgb[..., 1]) and np.array_equal(
        rgb[..., 1], rgb[..., 2]
    ):
        return rgb[..., 0]
    raise ValueError(
        f"{image_format} is a single-channel format but the picture is in colour "
        f"(colormap {colormap!r}, and possibly a coloured nan_rgb); use "
        "colormap='gray' with a gray nan_rgb, or write .ppm/.png instead"
    )


def save_field(
    path: str | Path,
    field: Any,
    *,
    quantity: str | None = None,
    style: PlotStyle | None = None,
    backend: Backend | str = Backend.AUTO,
) -> FieldImage:
    """Draw a 2D field to ``path``; the suffix picks the format.

    ``.png`` goes through matplotlib when it is installed and through the
    built-in encoder when it is not -- the same call works either way, which is
    the whole point of this module. ``.pdf``/``.svg`` need matplotlib;
    ``.ppm``/``.pgm`` are built-in only. ``.pgm`` additionally defaults the
    colour table to ``gray``, since the format has one channel.
    """
    target = Path(path)
    image_format = format_for_path(target)
    chosen = resolve_backend(backend, image_format)
    style = style or PlotStyle()
    if image_format == "pgm" and style.colormap is None:
        style = replace(style, colormap="gray")

    if chosen is Backend.MATPLOTLIB:
        return _save_matplotlib(target, field, quantity, style, image_format)

    rgb, values, colormap = _render(field, quantity, style)
    payload = _to_gray(rgb, image_format, colormap) if image_format == "pgm" else rgb
    write_image(
        target,
        payload,
        image_format=image_format,
        compress_level=style.compress_level,
    )
    return FieldImage(
        path=target,
        backend=Backend.BUILTIN.value,
        image_format=image_format,
        colormap=colormap,
        values=values,
        width=int(rgb.shape[1]),
        height=int(rgb.shape[0]),
        bytes_written=target.stat().st_size,
        quantity=quantity,
        label=style.resolved_label(quantity_spec(quantity)),
        image=rgb,
    )


def _save_matplotlib(
    target: Path,
    field: Any,
    quantity: str | None,
    style: PlotStyle,
    image_format: str,
) -> FieldImage:
    """The matplotlib path: same mapping, real axes, a labelled colour bar.

    Built on ``Figure`` and the Agg canvas rather than ``pyplot`` -- pyplot
    keeps a global figure registry that a library has to remember to clean up,
    and it picks an interactive backend on a machine that has a display, which
    is not something a save function should decide.
    """
    from matplotlib import colormaps as mpl_colormaps
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    array = _as_field(field)
    spec = quantity_spec(quantity)
    colormap = style.resolved_colormap(spec)
    symmetric = style.resolved_symmetric(spec, colormap)
    values = value_range(
        array,
        vmin=style.vmin,
        vmax=style.vmax,
        symmetric=symmetric,
        percentile=style.percentile,
    )
    if colormap not in mpl_colormaps:
        raise ValueError(
            f"unknown colormap {colormap!r}; matplotlib does not have it either"
        )
    nan_rgb = tuple(c / 255.0 for c in _as_rgb_triple(style.nan_rgb, "nan_rgb"))
    cmap = mpl_colormaps[colormap].with_extremes(bad=nan_rgb)

    figure = Figure(figsize=style.figsize, dpi=style.dpi)
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)
    image = axes.imshow(
        np.ma.masked_invalid(array),
        cmap=cmap,
        vmin=values.vmin,
        vmax=values.vmax,
        origin=style.origin,
        interpolation="nearest",
    )
    axes.set_xlabel("POI column")
    axes.set_ylabel("POI row")
    if style.title:
        axes.set_title(style.title)
    if style.colorbar:
        figure.colorbar(image, ax=axes, label=style.resolved_label(spec))
    figure.tight_layout()
    figure.savefig(target, format=image_format, dpi=style.dpi)
    width, height = figure.canvas.get_width_height()

    return FieldImage(
        path=target,
        backend=Backend.MATPLOTLIB.value,
        image_format=image_format,
        colormap=colormap,
        values=values,
        width=int(width),
        height=int(height),
        bytes_written=target.stat().st_size,
        quantity=quantity,
        label=style.resolved_label(spec),
        image=None,
    )


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


def run_field(run: Any, quantity: str, frame: int | None = None) -> np.ndarray:
    """Pull one quantity out of a pipeline run, without importing the pipeline.

    Duck-typed on ``field`` / ``strain_field`` so that a
    :class:`hl3.pipeline.Dic2DRun`, a :class:`hl3.pipeline.Dic3DRun` and a test
    double are all acceptable, and so that ``hl3.viz`` never becomes an import
    dependency of the analysis chain -- plotting must be able to fail without
    taking a correlation run with it.

    ``frame=None`` returns the whole ``(n_frames, ny, nx)`` stack; an integer
    indexes it, negative from the end.
    """
    spec = _named_quantity(quantity)
    accessors = ("field", "strain_field")
    if spec.source == "strain":
        accessors = ("strain_field", "field")

    errors: list[str] = []
    stack: np.ndarray | None = None
    for accessor in accessors:
        getter = getattr(run, accessor, None)
        if getter is None:
            errors.append(f"{accessor}: not available on {type(run).__name__}")
            continue
        try:
            stack = np.asarray(getter(quantity), dtype=np.float64)
        except Exception as exc:  # the accessors raise several types
            errors.append(f"{accessor}: {exc}")
            continue
        break
    if stack is None:
        raise ValueError(
            f"cannot read {quantity!r} from this run -- " + "; ".join(errors)
        )

    if stack.ndim != 3:
        raise ValueError(
            f"{quantity!r} came back with shape {stack.shape}; a picture needs a "
            "(n_frames, ny, nx) lattice, and this run has no POI grid "
            "(grid_shape is None)"
        )
    if frame is None:
        return stack
    n_frames = int(stack.shape[0])
    if n_frames == 0:
        raise ValueError("this run has no frames to draw")
    if not -n_frames <= int(frame) < n_frames:
        raise IndexError(
            f"frame {frame} is out of range for a run of {n_frames} frame(s)"
        )
    return stack[int(frame)]


def _run_unit(run: Any, quantity: str) -> str | None:
    """The unit a run's fields are in, inferred from which run it is.

    :class:`hl3.pipeline.Dic2DRun` works in the image plane and its
    displacements are pixels; :class:`~hl3.pipeline.Dic3DRun` reports world
    coordinates in millimetres. Strain is dimensionless in both. Anything that
    is not clearly one of the two gets no unit rather than a guessed one.
    """
    if quantity not in ("u", "v", "w", "magnitude"):
        return None
    if hasattr(run, "X_ref"):
        return "mm"
    if hasattr(run, "strain_field"):
        return "px"
    return None


def save_run_field(
    path: str | Path,
    run: Any,
    quantity: str,
    *,
    frame: int = -1,
    scope: str = "sequence",
    style: PlotStyle | None = None,
    backend: Backend | str = Backend.AUTO,
) -> FieldImage:
    """Draw one frame of a run.

    ``scope="sequence"`` (the default) takes the colour range from every frame
    of the run, so a series of files can be flipped through as an animation and
    a colour means the same thing in each of them. ``scope="frame"`` scales to
    the frame being drawn, which shows more detail in a quiet frame and makes
    frames incomparable. Explicit ``style.vmin``/``style.vmax`` override both.

    The title and the colour-bar label default to the quantity and the run's
    unit -- pixels for a 2D run, millimetres for a stereo one.
    """
    if scope not in ("sequence", "frame"):
        raise ValueError(f"scope must be 'sequence' or 'frame', got {scope!r}")
    style = style or PlotStyle()
    spec = _named_quantity(quantity)

    stack = run_field(run, quantity, None)
    n_frames = int(stack.shape[0])
    if n_frames == 0:
        raise ValueError("this run has no frames to draw")
    if not -n_frames <= int(frame) < n_frames:
        raise IndexError(
            f"frame {frame} is out of range for a run of {n_frames} frame(s)"
        )
    index = int(frame) % n_frames

    if scope == "sequence" and (style.vmin is None or style.vmax is None):
        colormap = style.resolved_colormap(spec)
        whole = value_range(
            stack,
            vmin=style.vmin,
            vmax=style.vmax,
            symmetric=style.resolved_symmetric(spec, colormap),
            percentile=style.percentile,
        )
        style = replace(style, vmin=whole.vmin, vmax=whole.vmax)
    if style.unit is None:
        style = replace(style, unit=_run_unit(run, quantity))
    if style.title is None:
        style = replace(style, title=f"{spec.label} -- frame {index}")

    return save_field(
        path, stack[index], quantity=quantity, style=style, backend=backend
    )


def save_field_png(
    path: str | Path,
    field: Any,
    *,
    quantity: str | None = None,
    style: PlotStyle | None = None,
    backend: Backend | str = Backend.AUTO,
) -> FieldImage:
    """:func:`save_field` with the suffix forced to ``.png``."""
    target = Path(path)
    if target.suffix.lower() != ".png":
        target = target.with_suffix(".png")
    return save_field(
        target, field, quantity=quantity, style=style, backend=backend
    )


def colormap_choices() -> tuple[str, ...]:
    """Colour tables the built-in backend can draw, for error messages and CLIs."""
    return colormap_names(include_reversed=True)
