ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# R3-G3 CI final

- Pytest discovery now includes both `tests/` and `src/tests/` in `pyproject.toml`.
- CI invokes both test directories explicitly.
- CI installs `numpy`, `pytest`, and optional HDF5 support via `h5py`.
- Existing `test`, `hdf5`, and `hash` optional dependency groups remain unchanged.

Validation command: `python -m pytest -q tests src/tests`
