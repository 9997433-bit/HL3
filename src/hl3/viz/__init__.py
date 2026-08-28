# SPDX-License-Identifier: Apache-2.0
"""Field visualisation: a picture of a DIC result, matplotlib optional.

Stage S4 of the implementation rounds. Three modules, in the order data flows
through them:

1. :mod:`hl3.viz.colormaps` -- NumPy colour lookup tables under matplotlib's
   names, so a backend switch does not change the picture;
2. :mod:`hl3.viz.plot2d` -- normalisation, colour mapping, colour bar, and the
   two renderers (matplotlib when installed, built-in otherwise);
3. :mod:`hl3.viz.imwrite` -- PNG via ``zlib`` and Netpbm via nothing at all.

The point of the split is the middle one. ``hl3`` depends on NumPy and nothing
else, and a plotting call that raises ``ImportError`` on a cluster node is a
plotting call that gets deleted from the analysis script. So::

    from hl3.viz import save_field, save_run_field

    save_run_field("exx.png", run, "exx")          # last frame, sequence scale
    save_field("u.png", u_grid, quantity="u")      # any (ny, nx) array

writes a PNG whether or not matplotlib is present. With it, the file is a
figure with axes and a labelled colour bar; without it, the file is the field
plus a colour bar with numeric end labels, drawn by this package. The mapping
from value to colour is computed once, in shared code, so the two differ in
their furniture and not in what they say about the data.
:attr:`hl3.viz.FieldImage.backend` records which one ran.

Install the extra with ``pip install hl3[viz]``, or set ``HL3_VIZ_BACKEND`` to
``builtin`` to pin the reproducible path even where matplotlib exists.

Not here: 3D surface rendering (``plot3d``), animations, contour lines, HTML
reports and FEA overlays. This module draws one scalar field on one POI
lattice, which is the piece the rest of them are built on.
"""

from __future__ import annotations

from . import colormaps, imwrite, plot2d
from .colormaps import (
    COLORMAPS,
    DEFAULT_COLORMAP,
    DEFAULT_NAN_RGB,
    Colormap,
    apply_colormap,
    colormap_lut,
    colormap_names,
)
from .imwrite import (
    IMAGE_FORMATS,
    encode_png,
    encode_pnm,
    write_image,
    write_pgm,
    write_png,
    write_ppm,
)
from .plot2d import (
    BACKEND_ENV_VAR,
    MATPLOTLIB_FORMATS,
    QUANTITIES,
    Backend,
    FieldImage,
    PlotStyle,
    QuantitySpec,
    ValueRange,
    matplotlib_available,
    normalise,
    quantity_spec,
    render_field,
    resolve_backend,
    run_field,
    save_field,
    save_field_png,
    save_run_field,
    value_range,
)

__all__ = [
    "BACKEND_ENV_VAR",
    "COLORMAPS",
    "DEFAULT_COLORMAP",
    "DEFAULT_NAN_RGB",
    "IMAGE_FORMATS",
    "MATPLOTLIB_FORMATS",
    "QUANTITIES",
    "Backend",
    "Colormap",
    "FieldImage",
    "PlotStyle",
    "QuantitySpec",
    "ValueRange",
    "apply_colormap",
    "colormap_lut",
    "colormap_names",
    "colormaps",
    "encode_png",
    "encode_pnm",
    "imwrite",
    "matplotlib_available",
    "normalise",
    "plot2d",
    "quantity_spec",
    "render_field",
    "resolve_backend",
    "run_field",
    "save_field",
    "save_field_png",
    "save_run_field",
    "value_range",
    "write_image",
    "write_pgm",
    "write_png",
    "write_ppm",
]
