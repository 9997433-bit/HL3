# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points.

    python -m hl3 doctor              # hl3.cli.__main__.doctor
    python -m hl3 run --synthetic     # hl3.cli.run
    python -m hl3 validate spec.hl3   # hl3.cli.validate
    python -m hl3.cli.validate spec.hl3   # the same function, direct

:mod:`hl3.cli.validate` is the container check -- a schema promise nobody can
check is a README, not a format -- and :mod:`hl3.cli.run` is the correlation
command. :mod:`hl3.cli.__main__` is the umbrella that dispatches between them
and holds ``doctor``.

This package intentionally contains nothing but this docstring. Importing
``hl3.cli`` has no side effects, pulls in no submodule and needs neither h5py
nor numpy, so a tool that only wants :mod:`hl3.cli.validate` pays for exactly
that -- and so ``doctor`` can still report a broken environment instead of
dying in it. The remaining commands of spec section 12 (``hl3 export``,
``hl3 diff``) are deliberately absent rather than stubbed: a subcommand that
exists and does nothing is worse than one that does not exist.
"""

from __future__ import annotations
