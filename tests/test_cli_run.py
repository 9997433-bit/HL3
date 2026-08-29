# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from hl3.cli.__main__ import doctor, main
from hl3.cli.run import main as run_main


def test_doctor_no_selftest_exits_zero() -> None:
    assert doctor(["--no-selftest"]) == 0


def test_umbrella_help_exits_usage() -> None:
    assert main([]) == 2


def test_run_rejects_second_order_shape() -> None:
    code = run_main(
        [
            "--synthetic",
            "--frames",
            "2",
            "--size",
            "48x48",
            "--subset",
            "17",
            "--shape-order",
            "2",
            "--strain",
            "off",
            "--quiet",
        ]
    )
    assert code == 2


def test_run_synthetic(tmp_path: Path) -> None:
    summary = tmp_path / "run.json"
    out = tmp_path / "fields.npz"
    code = run_main(
        [
            "--synthetic",
            "--frames",
            "2",
            "--size",
            "48x48",
            "--subset",
            "17",
            "--step",
            "8",
            "--strain",
            "off",
            "--quiet",
            "--summary",
            str(summary),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert summary.is_file()
    assert out.is_file()
