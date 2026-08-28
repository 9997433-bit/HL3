# Impl-R2 派工（S2 + S3）

前置：`.agent_workspace/s1s4/IR1_BRIEF.md`。禁止显微镜畸变实现。git add 只用独占路径。

| ID | slug | 独占路径 |
|----|------|----------|
| IR2-F1 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR2-F1-s2s3-gates.md` |
| IR2-F2 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR2-F2-stereo-match-spec.md` |
| IR2-F3 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR2-F3-uq-contract.md` |
| IR2-F4 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR2-F4-validate-cli.md` |
| IR2-O1 | claude-opus-5-thinking-high-fast | `src/hl3/stereo/match.py`、`tests/test_stereo_match.py`、报告 `IR2-O1-match.md` |
| IR2-O2 | claude-opus-5-thinking-high-fast | `src/hl3/pipeline/dic3d.py`、`tests/test_pipeline_3d.py`、报告 `IR2-O2-dic3d.md` |
| IR2-O3 | claude-opus-5-thinking-high-fast | `src/hl3/uq/**`、`src/hl3/cli/validate.py`、`tests/test_uq.py`、`tests/test_validate.py`、报告 `IR2-O3-uq.md` |
| IR2-G1 | gpt-5.6-sol-xhigh-fast | `.agent_workspace/s1s4/IR2-G1-legal.md` |
| IR2-G2 | gpt-5.6-sol-xhigh-fast | `tests/test_s2_s3_smoke.py`、`.agent_workspace/s1s4/IR2-G2-smoke.md` |
| IR2-G3 | gpt-5.6-sol-xhigh-fast | `benchmarks/metrology/metrics.json` s2/s3 段、`IR2-G3-metrics.md` |
