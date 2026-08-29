# IR5-G3 CI

`.github/workflows/ci.yml` 仍只装 numpy/pytest/h5py，不 fetch Drive。
无缓存时 `test_challenge_*` skip（未标 slow 的单元测试仍跑）。
`metrics.json` 增加 `challenge` 段，`exit_gate_pass: false`。
