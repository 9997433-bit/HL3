# HL3 DIC 应变分析软件 — 主调度器进度

- **任务目标**：规划并分阶段建设两款 DIC 应变分析软件（二维 / 三维），对标并最终超过 Correlated Solutions 的 VIC-2D 与 VIC-3D。
- **当前阶段**：竞品公开分析 + 开源算法调研 + 详细实施计划（不做盗版安装、不做逆向）。
- **工作分支**：`cursor/dic-sota-plan-259d`  
  （平台强制模板 `cursor/<name>-259d`；SOP 中的 `agent/<task-name>` 映射为本分支。）
- **父模型**：Cursor Grok 4.6（`cursor-grok-4.6-high`）
- **并发规则**：每轮固定 6 个子代理 = 2×fable + 2×opus-fast + 2×gpt-sol  
  （SOP 后文写“10 个”与前文“各 2 个共 6 个”冲突；按可执行的固定模型矩阵执行 6 个/轮，共 3 轮。）

## 模型映射（禁止静默降级）

| 简称 | 实际 slug | 推荐职能 |
|------|-----------|----------|
| fable | `claude-fable-5-thinking-xhigh` | 架构规划、多维审计、SOTA 标准与验收 |
| opus-fast | `claude-opus-5-thinking-high-fast` | 核心算法/模块落地、高覆盖单测、原子修复 |
| gpt-sol | `gpt-5.6-sol-xhigh-fast` | 探针脚本、基准、边界探索、兜底校验 |

## Round 状态

| 轮次 | 状态 | 派发 | 产物 |
|------|------|------|------|
| Round 1 初始构建与基线探索 | IN_PROGRESS | 6 | `round1/` |
| Round 2 靶向重构与深度优化 | PENDING | 6 | `round2/` |
| Round 3 SOTA 打磨与最终验收 | PENDING | 6 | `round3/` |

## 法律与环境红线

- **禁止**破解、盗版镜像、密钥生成、逆向 VIC 二进制。
- 官方 30 天评估版存在，但为 **Windows 安装包 + PC 专属 12 位密钥申请**。本 Cloud Agent 环境为 Linux，无法完成合法许可评估安装。
- 分析基线仅使用：官方公开网页/宣传册、已发表论文、iDICs 良好实践、GitHub 开源实现、公开评测集。

## 关键发现（父调度器预研）

详见 `research/`。摘要：

1. 对标产品是 **VIC-2D 8** 与 **VIC-3D 11.4**，不是可自由分发的科研代码。
2. 产品形态是“软件 + 相机/标定/散斑/采集（VIC-Snap）+ 实时（VIC-Gauge）+ 可视化（iris）+ Python 扩展（vicpyx）”的闭环，而不仅是相关算法。
3. 要超过它们，必须在 **算法精度/鲁棒性、吞吐、跨平台、不确定度量化、FEA 闭环、多相机、开源生态与可重复性** 上同时超越，而不是只写一个相关器。
