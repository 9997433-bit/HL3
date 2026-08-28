# SPDX-License-Identifier: Apache-2.0
"""``python -m hl3.cli.validate`` -- check a ``.hl3`` file against the schema.

    python -m hl3.cli.validate path.hl3            # structure, required fields,
                                                   # cross-reference integrity
    python -m hl3.cli.validate path.hl3 --strict   # plus SHOULD-level findings

Spec section 12 asks the reference implementation for a ``hl3 validate``
command; :func:`hl3.io.hdf5_schema.validate_file` is the function behind it and
this module is the shell around that function -- nothing more, on purpose.

**The command implements no checks of its own.** Every rule, every violation
string and the meaning of ``--strict`` live in ``validate_file``; this file
parses two arguments, prints what it is handed, and turns the outcome into an
exit code. When ``validate_file`` grows the hash and unit checks the schema
still owes (docs/schema-hdf5.md section 12), the command inherits them with no
edit here -- and, just as importantly, the command can never disagree with the
library about whether a file conforms.

Violations are printed verbatim, one per line, including their language: a
second, translated vocabulary for the same rules is how two tools come to
describe the same file differently.

Exit codes (frozen in ``.agent_workspace/s1s4/IR2-F4-validate-cli.md``):

===== ===========================================================
    0 validation ran, no violations
    1 validation ran, at least one violation
    2 validation could not run -- usage error, unreadable file, or
      h5py missing
===== ===========================================================

An unopenable file is 2 rather than 1 because the only source of violations is
``validate_file``'s return list, and the command is not allowed to invent an
entry for it. If "unopenable" is ever ruled to be a conformance failure, that
ruling belongs inside ``validate_file``, and exit code 1 then follows here with
no change.

Importing this module must work without h5py, like the schema module itself;
the missing dependency surfaces only when validation is attempted, as
``Hdf5Unavailable`` on stderr and exit code 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hl3.io.hdf5_schema import Hdf5Unavailable, validate_file

__all__ = ["main"]

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_NOT_RUN = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one file. Returns the exit code instead of calling ``sys.exit``.

    Returning rather than exiting is what lets the tests call ``main([...])``
    in-process and assert on both the code and the captured output; the
    ``__main__`` guard below is the only place that turns it into a process
    status. argparse still raises ``SystemExit(2)`` on a usage error, which is
    the one permitted exception and already agrees with the exit-code table.
    """
    parser = argparse.ArgumentParser(
        # sys.argv[0] under -m is a file path, which would make the help text
        # advertise an invocation that does not work.
        prog="python -m hl3.cli.validate",
        description=(
            "Validate an HL3 container file against docs/schema-hdf5.md. "
            "Prints one line per violation, verbatim from "
            "hl3.io.hdf5_schema.validate_file."
        ),
    )
    parser.add_argument("path", help="path to the .hl3 file to validate")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "also report SHOULD-level findings (provenance, @git_sha, "
            "calibration covariance). A strict finding is a recommendation "
            "rather than a broken file, but it still sets exit code 1."
        ),
    )
    args = parser.parse_args(argv)

    try:
        problems = validate_file(args.path, strict=args.strict)
    except Hdf5Unavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN
    except OSError as exc:
        print(f"error: 无法打开 {args.path}: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN

    for problem in problems:
        print(problem)
    if problems:
        print(f"FAIL {args.path}: {len(problems)} 条违规")
        return EXIT_VIOLATIONS
    print(f"OK {args.path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
