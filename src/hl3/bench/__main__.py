# SPDX-License-Identifier: Apache-2.0
"""``python -m hl3.bench download|2d|stereo``."""

from __future__ import annotations

import sys

from hl3.bench.download import EXIT_NOT_RUN, main as download_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: python -m hl3.bench {download|2d|stereo} ...")
        return EXIT_NOT_RUN if not args else 0
    command, rest = args[0], args[1:]
    if command == "download":
        return download_main(rest)
    if command == "2d":
        from hl3.bench.challenge2d import main as run_2d

        return run_2d(rest)
    if command in {"stereo", "3d"}:
        from hl3.bench.challenge_stereo import main as run_stereo

        return run_stereo(rest)
    print(f"error: unknown bench command {command!r}", file=sys.stderr)
    return EXIT_NOT_RUN


if __name__ == "__main__":
    raise SystemExit(main())
