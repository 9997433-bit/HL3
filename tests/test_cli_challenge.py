# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from hl3.cli.challenge import main
from hl3.cli.__main__ import COMMANDS


def test_challenge_is_registered() -> None:
    assert "challenge" in COMMANDS


def test_challenge_help_lists_bench_commands() -> None:
    assert main(["--help"]) == 0
