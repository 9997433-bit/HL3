# Round 1 派工单（已更正：10 = 4 fable + 3 opus-fast + 3 gpt-sol）

每份子代理报告**第一行必须**写：`ACTUAL_MODEL_SLUG: <slug>`

先前 2+2+2=6 的矩阵作废。本轮及后续两轮一律 4/3/3。

| ID | 简称 | slug | 环境 | 主攻 | 输出文件 |
|----|------|------|------|------|----------|
| R1-F1 | fable | claude-fable-5-thinking-xhigh | **cloud** | 全局架构 / 竞品 SOTA 规划 | `.agent_workspace/round1/R1-F1-architecture-sota.md` |
| R1-F2 | fable | claude-fable-5-thinking-xhigh | local | 多维审计与验收标准 | `.agent_workspace/round1/R1-F2-audit-acceptance.md` |
| R1-F3 | fable | claude-fable-5-thinking-xhigh | local | 功能差距矩阵与超越策略 | `.agent_workspace/round1/R1-F3-gap-matrix.md` |
| R1-F4 | fable | claude-fable-5-thinking-xhigh | local | 路线图 / WBS / 风险 | `.agent_workspace/round1/R1-F4-roadmap-wbs.md` |
| R1-O1 | opus-fast | claude-opus-5-thinking-high-fast | local | HL3-2D 核心规格与算法落地 | `.agent_workspace/round1/R1-O1-hl3-2d-spec.md` |
| R1-O2 | opus-fast | claude-opus-5-thinking-high-fast | local | HL3-3D 核心规格与算法落地 | `.agent_workspace/round1/R1-O2-hl3-3d-spec.md` |
| R1-O3 | opus-fast | claude-opus-5-thinking-high-fast | local | 共享内核 / 数据模型 / API | `.agent_workspace/round1/R1-O3-shared-kernel.md` |
| R1-G1 | gpt-sol | gpt-5.6-sol-xhigh-fast | local | GitHub 开源探针与许可证 | `.agent_workspace/round1/R1-G1-github-probe.md` |
| R1-G2 | gpt-sol | gpt-5.6-sol-xhigh-fast | local | 基准协议 / Challenge / 合成散斑 | `.agent_workspace/round1/R1-G2-benchmark-protocol.md` |
| R1-G3 | gpt-sol | gpt-5.6-sol-xhigh-fast | local | 环境探针 / 合法下载边界 / Mock | `.agent_workspace/round1/R1-G3-env-legal-probe.md` |

约束：禁止盗版/逆向；仅公开资料与开源许可证允许的范围。R1-F1 为用户指定的云端子代理（slug 不得降级）。
