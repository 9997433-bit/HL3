# Round 2 派工单（10 = 4 fable + 3 opus-fast + 3 gpt-sol）

**前置上下文（全量注入）**：`.agent_workspace/ROUND1_BRIEF.md` 以及 `round1/` 全部报告。

每份报告第一行：`ACTUAL_MODEL_SLUG: <slug>`

| ID | 简称 | slug | 主攻 | 输出 |
|----|------|------|------|------|
| R2-F1 | fable | claude-fable-5-thinking-xhigh | SOTA 复审 + 冲突消解裁决 | `round2/R2-F1-sota-reconciliation.md` |
| R2-F2 | fable | claude-fable-5-thinking-xhigh | 交叉审计 R1 十份文档 | `round2/R2-F2-cross-audit.md` |
| R2-F3 | fable | claude-fable-5-thinking-xhigh | 统一 PRD / 超越定义冻结 | `round2/R2-F3-prd-surpass.md` |
| R2-F4 | fable | claude-fable-5-thinking-xhigh | Round 3 验收包与剩余差距 | `round2/R2-F4-r3-gates.md` |
| R2-O1 | opus-fast | claude-opus-5-thinking-high-fast | CPU 一阶 ICGN 最小内核 + 单测 | `round2/R2-O1-icgn-impl.md` + `src/` |
| R2-O2 | opus-fast | claude-opus-5-thinking-high-fast | 立体标定/三角化轻量实现 | `round2/R2-O2-stereo-impl.md` + `src/` |
| R2-O3 | opus-fast | claude-opus-5-thinking-high-fast | HDF5 schema 与仓库骨架冻结 | `round2/R2-O3-schema-tree.md` + `src/`/`docs/` |
| R2-G1 | gpt-sol | gpt-5.6-sol-xhigh-fast | 许可证 ADR + FTO 检索清单 | `round2/R2-G1-license-adr.md` |
| R2-G2 | gpt-sol | gpt-5.6-sol-xhigh-fast | 扩展基准脚本并跑通 | `round2/R2-G2-bench-run.md` + scripts |
| R2-G3 | gpt-sol | gpt-5.6-sol-xhigh-fast | CI/Mock 采集/边界探针 | `round2/R2-G3-ci-mock.md` |
