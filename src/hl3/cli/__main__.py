# SPDX-License-Identifier: Apache-2.0
"""The umbrella command: ``python -m hl3 <command>``.

    python -m hl3 doctor            # is this machine able to run HL3, and how?
    python -m hl3 run --synthetic   # correlate a sequence, write results
    python -m hl3 validate f.hl3    # route into hl3.cli.validate, unchanged

Spec section 12 asks for one ``hl3`` entry point with subcommands. Until the
console script is registered in ``pyproject.toml`` the invocation is
``python -m hl3`` (this module is reached both as ``python -m hl3``, through the
three-line shim in ``hl3/__main__.py``, and as ``python -m hl3.cli``), and that
is the string this dispatcher advertises in every ``usage:`` line -- a help text
naming a command the shell cannot find is a bug report waiting to happen.

**Dispatch is lazy, on purpose.** A subcommand's module is imported only once
that subcommand has been named, so ``doctor`` still runs -- and still reports
the failure in words -- on a machine where NumPy is missing or where a kernel
module raises on import. That is the whole point of a doctor: the command that
diagnoses a broken environment must not be the command that dies in it. Nothing
at this module's import time touches NumPy or any :mod:`hl3` subpackage.

``validate`` is routed to :func:`hl3.cli.validate.main` *without* an argument
being rewritten. Its ``--help`` therefore still says
``python -m hl3.cli.validate``, which remains a working invocation and is the
one frozen in ``.agent_workspace/s1s4/IR2-F4-validate-cli.md`` section 2. Two
routes to the same function is a feature; two spellings of its contract is not.

Exit codes are the ones the validate command already established, so a script
can treat every HL3 command alike:

===== ===========================================================
    0 the command ran and found nothing wrong
    1 the command ran and something is wrong (a failed check, a
      violation, a quality gate the run did not meet)
    2 the command could not run -- usage error, unreadable input,
      missing dependency
===== ===========================================================
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
from collections.abc import Sequence
from typing import Any

__all__ = ["COMMANDS", "collect_report", "doctor", "main"]

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_NOT_RUN = 2

#: Advertised invocation. Overridden by ``hl3/__main__.py`` only if that shim
#: is ever reached by another name.
DEFAULT_PROG = "python -m hl3"

#: Floors taken from ``pyproject.toml`` (``requires-python``, ``dependencies``).
#: Duplicated here rather than read back from the metadata because ``doctor``
#: has to work in a source checkout where no distribution is installed.
MIN_PYTHON = (3, 10)
MIN_NUMPY = (1, 24)


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


class _Command:
    """One subcommand: what it does, and how to reach it without importing it.

    ``takes_prog`` records whether the handler lets the dispatcher name it.
    :func:`hl3.cli.validate.main` deliberately does not -- its ``prog`` is
    frozen -- and pretending otherwise by inspecting signatures at call time
    would turn a contract into a guess.
    """

    def __init__(self, target: str, summary: str, takes_prog: bool = True) -> None:
        self.target = target
        self.summary = summary
        self.takes_prog = takes_prog

    def load(self) -> Any:
        module_name, _, attribute = self.target.rpartition(".")
        return getattr(importlib.import_module(module_name), attribute)


COMMANDS: dict[str, _Command] = {
    "doctor": _Command(
        "hl3.cli.__main__.doctor",
        "report the environment HL3 would run in, and check it",
    ),
    "run": _Command(
        "hl3.cli.run.main",
        "correlate an image sequence and write displacement fields",
    ),
    "validate": _Command(
        "hl3.cli.validate.main",
        "validate a .hl3 container against docs/schema-hdf5.md",
        takes_prog=False,
    ),
    "challenge": _Command(
        "hl3.cli.challenge.main",
        "download or run official DIC Challenge samples",
    ),
}


def _root_parser(prog: str) -> argparse.ArgumentParser:
    width = max(len(name) for name in COMMANDS)
    listing = "\n".join(
        f"  {name.ljust(width)}  {command.summary}"
        for name, command in COMMANDS.items()
    )
    parser = argparse.ArgumentParser(
        prog=prog,
        description="HL3 -- open-core digital image correlation toolkit.",
        epilog=(
            f"commands:\n{listing}\n\n"
            f"Run '{prog} <command> --help' for a command's own options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the installed hl3 version and exit",
    )
    parser.add_argument(
        "command",
        nargs="?",
        metavar="command",
        help="one of: " + ", ".join(COMMANDS),
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        metavar="...",
        help="arguments for the command",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    """Dispatch one subcommand. Returns its exit code rather than exiting."""
    parser = _root_parser(prog)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.version:
        print(f"hl3 {hl3_version()}")
        return EXIT_OK
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_NOT_RUN
    if args.command not in COMMANDS:
        print(
            f"error: unknown command {args.command!r}; expected one of "
            + ", ".join(COMMANDS),
            file=sys.stderr,
        )
        return EXIT_NOT_RUN

    command = COMMANDS[args.command]
    try:
        handler = command.load()
    except Exception as error:  # noqa: BLE001
        # An unimportable subcommand is an environment fault, not a crash to
        # be shown as a traceback -- and it is exactly what `doctor` explains.
        print(
            f"error: command {args.command!r} is unavailable "
            f"({type(error).__name__}: {error}); try '{prog} doctor'",
            file=sys.stderr,
        )
        return EXIT_NOT_RUN

    if command.takes_prog:
        return int(handler(args.args, prog=f"{prog} {args.command}"))
    return int(handler(args.args))


def hl3_version() -> str:
    """Installed distribution version, or a truthful stand-in for a checkout."""
    try:
        from importlib.metadata import version

        return version("hl3")
    except Exception:  # noqa: BLE001
        return "unknown (not installed; running from a source checkout)"


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def doctor(
    argv: Sequence[str] | None = None,
    *,
    prog: str = f"{DEFAULT_PROG} doctor",
) -> int:
    """Describe the environment and check it. 0 = usable, 1 = something failed."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Report the interpreter, CPU, NumPy and HL3 modules this machine "
            "would run a correlation with, and check the required ones. "
            "Exit code 0 when every required check passes, 1 otherwise."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="write the whole report as JSON instead of an aligned table",
    )
    parser.add_argument(
        "--no-selftest",
        dest="selftest",
        action="store_false",
        help=(
            "skip the correlation self-test (a 48x48 two-frame synthetic run, "
            "about 0.2 s) and only inspect versions"
        ),
    )
    args = parser.parse_args(argv)

    report = collect_report(selftest=args.selftest)
    if args.as_json:
        print(
            json.dumps(
                report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
            )
        )
    else:
        _print_report(report)
    return EXIT_OK if report["ok"] else EXIT_PROBLEM


def collect_report(*, selftest: bool = True) -> dict[str, Any]:
    """The whole doctor report as plain JSON-able data.

    Split out from the printing so both output formats -- and the tests --
    read the same facts, and so another tool can call it as a library.
    """
    checks = _checks(selftest=selftest)
    return {
        "tool": "hl3 doctor",
        "environment": _environment(),
        "checks": checks,
        "ok": all(check["ok"] for check in checks if check["required"]),
    }


def _environment() -> dict[str, Any]:
    numpy_info: dict[str, Any] = {"available": False}
    try:
        numpy = importlib.import_module("numpy")
    except Exception as error:  # noqa: BLE001
        numpy_info["error"] = f"{type(error).__name__}: {error}"
    else:
        numpy_info = {
            "available": True,
            "version": str(numpy.__version__),
            "path": str(getattr(numpy, "__file__", "") or ""),
        }

    hl3_path = ""
    try:
        hl3_path = str(getattr(importlib.import_module("hl3"), "__file__", "") or "")
    except Exception:  # noqa: BLE001
        pass

    return {
        "hl3": {"version": hl3_version(), "path": hl3_path},
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "cpu": _cpu(),
        "numpy": numpy_info,
        # The reference kernels are single-threaded pure NumPy, so these
        # variables change speed, not numbers -- but they are the first thing
        # anyone asks about when a run is slower than expected.
        "thread_env": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "backend": "cpu-numpy",
    }


def _cpu() -> dict[str, Any]:
    """Cores, usable cores and, on Linux, the model string.

    ``os.cpu_count`` is the machine; ``sched_getaffinity`` is what this process
    may actually use, and in a container the two routinely disagree.
    """
    logical = os.cpu_count()
    try:
        usable: int | None = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        usable = logical
    return {
        "logical": logical,
        "usable": usable,
        "machine": platform.machine(),
        "model": _cpu_model(),
    }


def _cpu_model() -> str:
    model = platform.processor()
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key.strip() in ("model name", "Model", "cpu model"):
                    return value.strip()
    except OSError:
        pass
    return model


def _checks(*, selftest: bool) -> list[dict[str, Any]]:
    checks = [_python_check(), _numpy_check()]
    for module, required, note in (
        ("hl3.correlate", True, "IC-GN correlation kernels"),
        ("hl3.pipeline", True, "sequence orchestration behind 'run'"),
        ("hl3.capture", True, "MockCapture, the source behind 'run --synthetic'"),
        ("hl3.strain", False, "strain fields; 'run' reports displacement without it"),
        ("hl3.stereo", False, "stereo matching and triangulation (3D)"),
        ("hl3.uq", False, "uncertainty propagation"),
        ("hl3.io.hdf5_schema", False, ".hl3 container schema and 'validate'"),
    ):
        checks.append(_import_check(module, required=required, note=note))
    for module, note in (
        ("h5py", "reading and writing .hl3 containers"),
        ("blake3", "spec @hash_algo; without it hashing falls back to blake2b-256"),
        ("PIL", "PNG/TIFF input for 'run'; .npy and Netpbm need no dependency"),
        ("matplotlib", "plotting; not needed by any command in this module"),
    ):
        checks.append(_import_check(module, required=False, note=note))
    if selftest:
        checks.append(_selftest_check())
    return checks


def _python_check() -> dict[str, Any]:
    floor = ".".join(str(part) for part in MIN_PYTHON)
    ok = sys.version_info[:2] >= MIN_PYTHON
    return _check(
        "python",
        ok,
        required=True,
        detail=(
            f"{platform.python_version()} ({platform.python_implementation()})"
            + ("" if ok else f" -- HL3 requires >= {floor}")
        ),
    )


def _numpy_check() -> dict[str, Any]:
    floor = ".".join(str(part) for part in MIN_NUMPY)
    try:
        numpy = importlib.import_module("numpy")
    except Exception as error:  # noqa: BLE001
        return _check(
            "numpy",
            False,
            required=True,
            detail=f"not importable ({type(error).__name__}: {error}); need >= {floor}",
        )
    version = str(numpy.__version__)
    ok = _version_tuple(version) >= MIN_NUMPY
    return _check(
        "numpy",
        ok,
        required=True,
        detail=version + ("" if ok else f" -- HL3 requires >= {floor}"),
    )


def _import_check(module: str, *, required: bool, note: str) -> dict[str, Any]:
    try:
        imported = importlib.import_module(module)
    except Exception as error:  # noqa: BLE001
        return _check(
            module,
            False,
            required=required,
            detail=f"{type(error).__name__}: {error} -- {note}",
        )
    version = getattr(imported, "__version__", None)
    detail = f"{version} -- {note}" if version else note
    return _check(module, True, required=required, detail=detail)


def _selftest_check() -> dict[str, Any]:
    """Correlate two synthetic frames and check the answer, not just the import.

    A version table says the parts are present; only arithmetic says they work.
    :class:`hl3.capture.MockCapture` shifts frame ``i`` by ``(2i, i)`` pixels,
    so frame 1 has a known ``(u, v) = (2, 1)`` and a wrong number here is a
    broken build rather than a tolerance question.
    """
    try:
        import numpy as np

        from hl3.capture import MockCapture
        from hl3.correlate import ICGNParams
        from hl3.pipeline import Dic2DConfig, StrainMode, run_sequence

        run = run_sequence(
            MockCapture(frame_count=2, shape=(48, 48), seed=0),
            Dic2DConfig(
                icgn=ICGNParams(subset_radius=8, step=8),
                strain_mode=StrainMode.OFF,
            ),
        )
        u = float(np.nanmean(run.field("u")[1]))
        v = float(np.nanmean(run.field("v")[1]))
        valid = run.frames[1].valid_fraction
    except Exception as error:  # noqa: BLE001
        return _check(
            "selftest",
            False,
            required=True,
            detail=f"{type(error).__name__}: {error}",
        )

    ok = valid == 1.0 and abs(u - 2.0) < 1e-3 and abs(v - 1.0) < 1e-3
    return _check(
        "selftest",
        ok,
        required=True,
        detail=(
            f"48x48 synthetic pair: {valid:.0%} converged, "
            f"u={u:+.4f} v={v:+.4f} (expected u=+2 v=+1)"
        ),
    )


def _check(name: str, ok: bool, *, required: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "required": required, "detail": detail}


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split(".")[:3]:
        digits = ""
        for character in chunk:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _print_report(report: dict[str, Any]) -> None:
    environment = report["environment"]
    python = environment["python"]
    system = environment["platform"]
    cpu = environment["cpu"]
    numpy_info = environment["numpy"]
    threads = ", ".join(
        f"{name}={value if value is not None else 'unset'}"
        for name, value in sorted(environment["thread_env"].items())
    )

    lines = [
        ("hl3", environment["hl3"]["version"]),
        ("python", f"{python['version']} ({python['implementation']}) "
                   f"at {python['executable']}"),
        ("platform", f"{system['system']} {system['release']} ({system['machine']})"),
        ("cpu", f"{cpu['logical']} logical cores, {cpu['usable']} usable"
                + (f"; {cpu['model']}" if cpu["model"] else "")),
        (
            "numpy",
            f"{numpy_info['version']} at {numpy_info['path']}"
            if numpy_info["available"]
            else f"unavailable ({numpy_info.get('error', 'unknown reason')})",
        ),
        ("backend", f"{environment['backend']} (single-threaded reference kernels)"),
        ("threads", threads),
    ]
    if environment["hl3"]["path"]:
        lines.insert(1, ("hl3 path", environment["hl3"]["path"]))

    width = max(len(label) for label, _ in lines)
    print("environment")
    for label, value in lines:
        print(f"  {label.ljust(width)}  {value}")

    print()
    print("checks")
    name_width = max(len(check["name"]) for check in report["checks"])
    for check in report["checks"]:
        if check["ok"]:
            state = "ok"
        else:
            state = "FAIL" if check["required"] else "warn"
        print(f"  {state:<4}  {check['name'].ljust(name_width)}  {check['detail']}")

    failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
    print()
    if failed:
        print(f"{len(failed)} required check(s) failed: " + ", ".join(failed))
    else:
        optional = sum(1 for c in report["checks"] if not c["required"] and not c["ok"])
        note = f"; {optional} optional component(s) absent" if optional else ""
        print(f"all required checks passed{note}")


if __name__ == "__main__":
    raise SystemExit(main(prog="python -m hl3.cli"))
