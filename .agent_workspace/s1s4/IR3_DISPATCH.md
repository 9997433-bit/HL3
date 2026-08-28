# Impl-R3 派工（S4，本循环最后一轮）

完成后父调度器总结停止。禁止 GPU 内核、禁止相机 SDK、禁止显微镜。

| ID | slug | 独占路径 |
|----|------|----------|
| IR3-F1 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR3-F1-s4-gates.md` |
| IR3-F2 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR3-F2-cli-contract.md` |
| IR3-F3 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR3-F3-gui-scope.md` |
| IR3-F4 | claude-fable-5-thinking-xhigh | `.agent_workspace/s1s4/IR3-F4-fea-contract.md` |
| IR3-O1 | claude-opus-5-thinking-high-fast | `src/hl3/cli/run.py`、`src/hl3/cli/__main__.py`、`tests/test_cli_run.py`、`IR3-O1-cli.md` |
| IR3-O2 | claude-opus-5-thinking-high-fast | `src/hl3/viz/**`、`tests/test_viz.py`、`IR3-O2-viz.md` |
| IR3-O3 | claude-opus-5-thinking-high-fast | `src/hl3/fea/**`、`src/hl3/gui/**`、对应测试、`IR3-O3-fea-gui.md` |
| IR3-G1 | gpt-5.6-sol-xhigh-fast | `IR3-G1-legal.md` |
| IR3-G2 | gpt-5.6-sol-xhigh-fast | `tests/test_s4_smoke.py`、`IR3-G2-smoke.md` |
| IR3-G3 | gpt-5.6-sol-xhigh-fast | `.github/workflows/ci.yml`（可加 matplotlib 可选）、`pyproject.toml` extras `viz`、`IR3-G3-ci.md` |
