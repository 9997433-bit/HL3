# SPDX-License-Identifier: Apache-2.0
"""Community GUI baseline: field viewer + polygon AOI. Not a publication tool.

Importing this package has no side effects and does not require matplotlib,
tkinter, or h5py. Interactive windows live in :mod:`hl3.gui.viewer` and are
imported only when the user asks for a window.
"""

from __future__ import annotations

from .aoi import PolygonAOI, load_aoi, save_aoi

__all__ = ["PolygonAOI", "load_aoi", "save_aoi"]
