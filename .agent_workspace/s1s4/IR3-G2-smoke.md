ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# IR3-G2 S4 import smoke report

`tests/test_s4_smoke.py` independently exercises these optional S4 package
surfaces with `pytest.importorskip`:

- `hl3.cli.run`
- `hl3.viz`
- `hl3.fea`

Verification command:

```text
python3 -m pytest tests/test_s4_smoke.py -q -rs
```

Current result: `3 skipped in 0.01s`. Each skip names the corresponding
not-yet-implemented module. Once a surface exists, its case performs a real
import and exposes import-time failures.
