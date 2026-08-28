ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
# IR1-G2 S1 metrology

## Pytest result

Command:

```text
python3 -m pytest tests/test_s1_metrology.py -q -rs -s
```

Outcome: `1 passed, 1 skipped in 0.42s`.

## Translation accuracy

- Kernel: `hl3.correlate.icgn_first_order`
- Synthetic source: `.agent_workspace/round1/scripts/synth_speckle.py`
- Truth: `u = 0.37 px`, `v = -0.42 px`
- Image: `128 x 128 px`, `8x` oversampling
- Evaluated points: `16`
- Mean absolute component error: `0.001180712 px`
- Maximum absolute component error: `0.006686373 px`
- Acceptance gate: mean `|error| < 0.05 px` — **PASS**

## Uniform strain smoke test

`hl3.strain` was not present in this checkout, so pytest skipped the smoke test
with reason `hl3.strain is not available`, as required for an optional/missing
module.
