# Round 3 派工单（10 = 4 fable + 3 opus-fast + 3 gpt-sol）

前置上下文：`ROUND1_BRIEF.md` + `ROUND2_BRIEF.md` + `round2/R2-F1-sota-reconciliation.md`。

第一行必须：`ACTUAL_MODEL_SLUG: <slug>`

**分支纪律**：尽量只改下方「独占路径」；`git add` 不要用 `.`；不要把别人的半成品 sweep 进你的提交。

| ID | slug | 独占路径 |
|----|------|----------|
| R3-F1 | claude-fable-5-thinking-xhigh | `round3/R3-F1-final-sota-accept.md` |
| R3-F2 | claude-fable-5-thinking-xhigh | `round3/R3-F2-claims-legal-scan.md` |
| R3-F3 | claude-fable-5-thinking-xhigh | `round3/R3-F3-master-plan-final.md`（可更新 `MASTER_PLAN.md` 末节） |
| R3-F4 | claude-fable-5-thinking-xhigh | `round3/R3-F4-beyond-vic-roadmap.md` |
| R3-O1 | claude-opus-5-thinking-high-fast | `src/hl3/correlate/**`、`tests/test_icgn_*.py`、`round3/R3-O1-icgn-harden.md` |
| R3-O2 | claude-opus-5-thinking-high-fast | `src/hl3/stereo/**`、`tests/test_stereo_*.py`、`round3/R3-O2-stereo-harden.md` |
| R3-O3 | claude-opus-5-thinking-high-fast | `README.md`、`docs/**`、`round3/R3-O3-docs-align.md`（勿改 correlate/stereo 算法） |
| R3-G1 | gpt-5.6-sol-xhigh-fast | `round3/R3-G1-sbom-legal.md` |
| R3-G2 | gpt-5.6-sol-xhigh-fast | `benchmarks/metrology/metrics.json`、`round3/R3-G2-metrics-run.md` |
| R3-G3 | gpt-5.6-sol-xhigh-fast | `.github/workflows/ci.yml`、`pyproject.toml` 测试配置、`round3/R3-G3-ci-final.md` |
