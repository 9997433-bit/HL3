# SPDX-License-Identifier: Apache-2.0
"""Make ``python -m hl3`` the umbrella command.

The dispatcher itself lives in :mod:`hl3.cli.__main__`; this file exists only
so that the shortest spelling of the invocation works, and so that the ``prog``
in every help text matches the way the user actually got here. Keep it a shim:
anything implemented here would be unreachable from ``python -m hl3.cli``.
"""

from __future__ import annotations

from hl3.cli.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(prog="python -m hl3"))
