ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# IR1-G3 S1 metrology metrics

## Result

The CPU-only test suite passed: **232 passed, 0 failed, 0 skipped** in
11.07 s (11.551 s wall clock). The new `s1` object in
`benchmarks/metrology/metrics.json` records the exact tested revision, source
blob IDs, environment, gate values, limits, and scope qualifications.

S1 is **partial** and its aggregate exit gate is **not ready**:

| Gate | Result | Evidence |
|---|---|---|
| A1 displacement noise floor | Diagnostic pass; formal gate not evaluable | Three synthetic static speckle seeds at 2 gray noise gave mean spatial `std(u) = 0.0034261256 px`, below `0.01 px`; 432/432 POIs valid. The required DIC Challenge 2.0 noisy-static data are absent. |
| A2 interpolation S-curve | Pass on the current test grid | Prefiltered cubic B-spline IC-GN gave horizontal phase-bias peak-to-peak `0.0017295130 px`, below `0.01 px`; 294/294 POIs valid. |
| A4 strain noise floor | Not evaluated | The tested revision has no production strain implementation/test, so no VSG-qualified value can be reported. |
| G6 schema freeze | Pending | The implemented schema remains `1.0.0-draft.2`, not frozen `1.0.0`. |

A1 is deliberately not promoted to a formal pass: the synthetic three-seed
run satisfies the numeric limit but is not the specified Challenge dataset.
A2 covers the six phases in the current test; it is not represented as the
full multi-direction, multi-subset, multi-seed protocol.

## Commands

```bash
TIMEFORMAT='WALL_SECONDS=%R'
time CUDA_VISIBLE_DEVICES='' python3 -m pytest tests src/tests -q
```

The A1/A2 values were then measured through the existing
`tests/test_icgn_synth.py` generator and public `hl3.correlate` API using
`CUDA_VISIBLE_DEVICES=''`; the full per-seed and per-phase values are in the
JSON artifact.

## Provenance

- Tested revision: `e43e22281bca8e29f7cffbd93f164a65d0d86904`
- Platform: Linux `6.12.94+` x86_64
- Python: `3.12.3`
- NumPy: `2.4.4`
- Device: CPU only; GPU not used

No algorithm source, including `src/hl3/correlate/icgn.py`, was changed.
