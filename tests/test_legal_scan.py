# SPDX-License-Identifier: Apache-2.0
"""Fail-closed L-2 scan: proprietary-string hits must be allowlisted.

The needle is assembled so this file does not itself contain the product or
bypass vocabulary that the gate is hunting for.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("src", "tests", "benchmarks", "docs")
_TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".toml", ".json", ".cfg"}

# Assembled so the source of this test is not a hit for the same regex.
_NEEDLE = "cr" + "ack"
_PATTERN = re.compile(
    rf"(\.z3d|vic-snap|vic-gauge|keygen|{_NEEDLE}|"
    rf"license.{{0,10}}bypass|patch.{{0,10}}serial)",
    re.IGNORECASE,
)


def _allowlist() -> list[tuple[str, str]]:
    path = ROOT / "legal" / "scan-allowlist.txt"
    assert path.is_file(), "legal/scan-allowlist.txt is required by the L-2 gate"
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        assert len(parts) >= 3, f"allowlist row must be path<TAB>pattern<TAB>reason: {raw!r}"
        rows.append((parts[0], parts[1]))
    return rows


def _allowed(rel: str, line: str, rows: list[tuple[str, str]]) -> bool:
    for path, pattern in rows:
        if rel != path and not rel.startswith(path.rstrip("/") + "/"):
            continue
        if pattern.lower() in line.lower() or pattern.lower() in rel.lower():
            return True
    return False


def test_l2_hits_are_allowlisted() -> None:
    rows = _allowlist()
    unlisted: list[str] = []
    for scope in SCOPES:
        root = ROOT / scope
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(ROOT).as_posix()
            for number, line in enumerate(text.splitlines(), 1):
                if not _PATTERN.search(line):
                    continue
                if not _allowed(rel, line, rows):
                    unlisted.append(f"{rel}:{number}: {line.strip()[:160]}")
    assert unlisted == [], "unallowlisted L-2 hits:\n" + "\n".join(unlisted)
