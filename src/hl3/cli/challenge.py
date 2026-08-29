# SPDX-License-Identifier: Apache-2.0
"""``python -m hl3 challenge ...`` — thin alias of ``python -m hl3.bench``."""

from __future__ import annotations

from collections.abc import Sequence

from hl3.bench.__main__ import main as bench_main
from hl3.bench.download import EXIT_NOT_RUN

DEFAULT_PROG = "python -m hl3 challenge"


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    del prog  # advertised by the umbrella dispatcher
    args = None if argv is None else list(argv)
    if args is None:
        return bench_main()
    return bench_main(args)
