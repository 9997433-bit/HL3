# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`hl3.cli.validate`, the command around ``validate_file``.

The rules are tested in ``tests/test_hdf5_schema.py``; what is tested here is
the command's own contract (``.agent_workspace/s1s4/IR2-F4-validate-cli.md``),
which is what scripts and CI actually depend on:

* **the command adds no rules of its own**. Its output lines are asserted to be
  ``validate_file``'s return list verbatim, so the CLI cannot drift into a
  second, informal definition of conformance -- checked structurally as well,
  by walking the module's own import list;
* **exit codes 0 / 1 / 2 are stable and mean what the table says**, including
  the ruling that an unopenable file is 2 rather than 1;
* **importing the module never needs h5py**, matching the dependency layering
  of :mod:`hl3.io.hdf5_schema`, so a validation-only environment can import it
  and get a clean "not run" instead of an ImportError;
* **``python -m`` works from a clean interpreter**, which is the documented
  invocation and is not exercised by in-process ``main()`` calls.

Everything that touches a file is skipped without h5py; the import, parsing and
h5py-missing paths run either way, so the file is never entirely skipped.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Allow running against a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import hl3.cli  # noqa: E402
from hl3.cli import validate as cli  # noqa: E402
from hl3.io import hdf5_schema  # noqa: E402

requires_h5py = pytest.mark.skipif(
    hdf5_schema.skip_reason() is not None, reason=hdf5_schema.skip_reason() or ""
)


@pytest.fixture()
def conforming_file(tmp_path: Path) -> Path:
    return hdf5_schema.write_synthetic_hl3(tmp_path / "synthetic.hl3")


@pytest.fixture()
def broken_file(tmp_path: Path) -> Path:
    """A synthetic file with one required root attribute deleted."""
    import h5py

    path = hdf5_schema.write_synthetic_hl3(tmp_path / "broken.hl3")
    with h5py.File(path, "r+") as handle:
        del handle.attrs[hdf5_schema.A_SCHEMA_VERSION]
    return path


# --------------------------------------------------------------------------
# Exit codes and output
# --------------------------------------------------------------------------


@requires_h5py
def test_conforming_file_prints_one_line_and_exits_zero(conforming_file, capsys):
    assert cli.main([str(conforming_file)]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"OK {conforming_file}\n"
    assert captured.err == ""


@requires_h5py
def test_strict_reports_the_writers_one_should_level_gap(conforming_file, capsys):
    """``--strict`` on the synthetic sample: one finding, exit code 1.

    IR2-F4 section 8 item 2 expects 0 here, on the reading that the schema
    selftest guarantees a clean strict run. It does not -- the selftest prints
    the strict count without asserting it, and
    :func:`hl3.io.hdf5_schema.write_synthetic_hl3` does not write the
    SHOULD-level ``@git_sha``. The behaviour asserted here is therefore the
    library's, not the contract's expectation of it; the CLI is a wrapper and
    cannot fix the gap, which is registered for the schema owner in
    ``.agent_workspace/s1s4/IR2-O3-uq.md``.
    """
    assert cli.main([str(conforming_file), "--strict"]) == 1
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "/analyses/ana_01: 应当写 @git_sha",
        f"FAIL {conforming_file}: 1 条违规",
    ]
    # The non-strict run, which is the one the contract's exit-code table is
    # really about, is clean.
    assert cli.main([str(conforming_file)]) == 0


@requires_h5py
def test_violations_are_printed_verbatim_and_exit_one(broken_file, capsys):
    problems = hdf5_schema.validate_file(broken_file)
    assert problems  # the fixture really did break the file

    assert cli.main([str(broken_file)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[:-1] == problems
    assert lines[-1] == f"FAIL {broken_file}: {len(problems)} 条违规"


@requires_h5py
def test_strict_can_only_add_findings(conforming_file, broken_file):
    for path in (conforming_file, broken_file):
        plain = hdf5_schema.validate_file(path)
        strict = hdf5_schema.validate_file(path, strict=True)
        assert set(plain) <= set(strict)
        assert cli.main([str(path)]) <= cli.main([str(path), "--strict"])


@requires_h5py
def test_missing_file_exits_two(tmp_path, capsys):
    """The ruling of IR2-F4 section 5: unopenable is "did not run", not "fails"."""
    assert cli.main([str(tmp_path / "nowhere.hl3")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")


@requires_h5py
def test_a_file_that_is_not_hdf5_exits_two(tmp_path, capsys):
    path = tmp_path / "not-really.hl3"
    path.write_text("这不是 HDF5\n", encoding="utf-8")
    assert cli.main([str(path)]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_missing_h5py_exits_two_on_stderr(monkeypatch, capsys):
    """A missing optional dependency is an environment fault, not a finding."""

    def unavailable(*args, **kwargs):
        raise hdf5_schema.Hdf5Unavailable("h5py 缺失（测试注入）")

    monkeypatch.setattr(cli, "validate_file", unavailable)
    assert cli.main(["anything.hl3"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: h5py 缺失（测试注入）\n"


def test_usage_error_exits_two():
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


@requires_h5py
def test_output_is_byte_for_byte_reproducible(broken_file, capsys):
    assert cli.main([str(broken_file)]) == 1
    first = capsys.readouterr().out
    assert cli.main([str(broken_file)]) == 1
    assert capsys.readouterr().out == first


# --------------------------------------------------------------------------
# Thin-wrapper discipline
# --------------------------------------------------------------------------


def test_module_imports_without_h5py_and_exposes_only_main():
    """Importing must not need h5py, numpy or any kernel subpackage."""
    assert cli.__all__ == ["main"]
    assert callable(cli.main)

    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= {
        "__future__",
        "argparse",
        "sys",
        "collections.abc",
        "hl3.io.hdf5_schema",
    }, imported


def test_cli_package_has_no_import_side_effects():
    assert not hasattr(hl3.cli, "validate_file")
    assert hl3.cli.__doc__ and "python -m hl3.cli.validate" in hl3.cli.__doc__


def test_help_advertises_a_working_invocation(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: python -m hl3.cli.validate")
    assert "--strict" in out


@requires_h5py
def test_command_reports_exactly_what_the_library_returns(
    conforming_file, broken_file, capsys, monkeypatch
):
    """The single-source-of-truth rule, made structural.

    A stubbed ``validate_file`` proves the command prints its return value and
    nothing else -- no filtering, no reordering, no de-duplication, no
    translation.
    """
    injected = ["/x: 第一条", "/x: 第一条", "/y: 第二条"]
    monkeypatch.setattr(cli, "validate_file", lambda path, strict=False: injected)
    assert cli.main([str(conforming_file)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[:-1] == injected

    monkeypatch.setattr(cli, "validate_file", lambda path, strict=False: [])
    assert cli.main([str(broken_file)]) == 0


@requires_h5py
def test_strict_flag_reaches_the_library(conforming_file, monkeypatch):
    seen: list[bool] = []

    def record(path, strict=False):
        seen.append(strict)
        return []

    monkeypatch.setattr(cli, "validate_file", record)
    cli.main([str(conforming_file)])
    cli.main([str(conforming_file), "--strict"])
    assert seen == [False, True]


# --------------------------------------------------------------------------
# The documented invocation
# --------------------------------------------------------------------------


@requires_h5py
def test_python_dash_m_invocation(conforming_file):
    """The ``-m`` wiring: package import, module execution, ``__main__`` guard."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", "hl3.cli.validate",
         str(conforming_file)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(_SRC), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"OK {conforming_file}\n"
    assert proc.stderr == ""


@requires_h5py
def test_python_dash_m_exit_code_for_a_broken_file(broken_file):
    proc = subprocess.run(
        [sys.executable, "-m", "hl3.cli.validate", str(broken_file)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(_SRC), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 1
    assert proc.stdout.rstrip().endswith("条违规")
