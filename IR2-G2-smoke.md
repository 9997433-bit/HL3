ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# IR2-G2 S2/S3 import smoke report

`tests/test_s2_s3_smoke.py` independently exercises these future package
surfaces with `pytest.importorskip`:

- `hl3.stereo.match`
- `hl3.pipeline.dic3d`
- `hl3.uq`
- `hl3.cli.validate`

Verification command:

```text
python3 -m pytest tests/test_s2_s3_smoke.py -q -rs
```

Current result: `4 skipped in 0.17s`. Each skip names the corresponding
not-yet-implemented module. Once a surface exists, its case performs a real
import and exposes import-time failures.
