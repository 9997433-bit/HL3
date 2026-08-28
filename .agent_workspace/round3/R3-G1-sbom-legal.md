# R3-G1 — Dependency Inventory and Legal Artifact Check

Audit scope: repository state and the direct declarations in `pyproject.toml` on
2026-08-28. This is a declaration-level inventory, not a fully resolved SBOM:
the repository has no dependency lock file, so transitive packages and the
licenses bundled in a selected wheel must be checked again against release
artifacts.

## Direct dependency inventory

| Scope | Package | Declared constraint | Upstream license | Note |
|---|---|---:|---|---|
| Build | `setuptools` | `>=68` | MIT | Build backend is `setuptools.build_meta`. |
| Runtime | `numpy` | `>=1.24` | BSD-3-Clause (primary project license) | NumPy wheels can carry additional permissively licensed components; retain the wheel's bundled notices. |
| Optional: `test` | `pytest` | `>=7` | MIT | Test-only dependency. |
| Optional: `hdf5` | `h5py` | `>=3.8` | BSD-3-Clause | Used only for `.hl3` container I/O. |
| Optional: `hash` | `blake3` | `>=0.3` | CC0-1.0 OR Apache-2.0 | Optional canonical BLAKE3-256 hashing backend. |

The package requires Python `>=3.10`. The project metadata declares
`Apache-2.0` and includes the Apache Software License classifier.

## Repository legal and artifact checks

- **Apache-2.0 license present — PASS.** Root `LICENSE` contains the complete
  Apache License, Version 2.0 text, and `pyproject.toml` declares
  `license = { text = "Apache-2.0" }`.
- **No vendored OpenCorr — PASS.** Tracked-path and content review found no
  OpenCorr source tree, headers, libraries, tests, examples, resources, or
  vendor/third-party dependency directory. Repository documents mention
  OpenCorr as a citation, comparison target, and prohibited asset; those
  textual references are not vendored OpenCorr material.
- **No Windows MSI — PASS.** No tracked or working-tree file with a
  case-insensitive `.msi` extension is present. The tracked binary/path scan
  also found no `.msix`, `.exe`, `.dll`, or `.lib` artifact.

Conclusion: the declared direct dependencies are permissively licensed, the
repository carries its declared Apache-2.0 license, and the prohibited
OpenCorr/Windows-installer artifacts are absent. A release SBOM should resolve
and pin the dependency graph, then record the exact distributions and bundled
license notices.
