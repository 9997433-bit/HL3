# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points.

One command so far, and it is the one the container format needs most: a schema
promise nobody can check is a README, not a format.

    python -m hl3.cli.validate specimen.hl3

This package intentionally contains nothing but this docstring. Importing
``hl3.cli`` has no side effects, pulls in no submodule and needs neither h5py
nor numpy, so a tool that only wants :mod:`hl3.cli.validate` pays for exactly
that. The rest of the CLI surface of spec section 12 (``hl3 run``,
``hl3 export``, the umbrella ``hl3`` console script) belongs to stage S4 and is
deliberately absent rather than stubbed -- a subcommand that exists and does
nothing is worse than one that does not exist.
"""

from __future__ import annotations
