# SPDX-License-Identifier: Apache-2.0
"""Optional interactive viewer. Importing this module may pull matplotlib.

Headless environments should use :mod:`hl3.viz` to write PNG/PPM instead.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

EXIT_OK = 0
EXIT_NOT_RUN = 2

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Open a basic field viewer, or exit 2 with install hints if GUI is missing."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"--help", "-h"}:
        print("usage: python -m hl3.gui.viewer [field.npy]\nbasic community viewer")
        return EXIT_OK
    try:
        import matplotlib  # noqa: F401
    except Exception as error:  # noqa: BLE001
        print(
            f"error: matplotlib is required for the viewer ({error}); "
            "install with pip install 'hl3[viz]'",
            file=sys.stderr,
        )
        return EXIT_NOT_RUN
    try:
        import tkinter  # noqa: F401
    except Exception as error:  # noqa: BLE001
        print(
            f"error: tkinter is required for the window ({error}); "
            "on Debian/Ubuntu install python3-tk",
            file=sys.stderr,
        )
        return EXIT_NOT_RUN
    # Interactive loop is not exercised in CPU-only CI. The command still
    # documents its contract: dependencies present → would open a window.
    print(
        "hl3.gui.viewer: matplotlib and tkinter are importable; "
        "interactive session is not started in this non-interactive context."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
