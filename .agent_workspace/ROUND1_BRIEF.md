# Round 1 结论简报（父调度器）

- **轮次**：Round 1 / 3（初始构建与基线探索）
- **派发**：10 = **4×fable** (`claude-fable-5-thinking-xhigh`) + **3×opus-fast** (`claude-opus-5-thinking-high-fast`) + **3×gpt-sol** (`gpt-5.6-sol-xhigh-fast`)
- **模型声明**：10 份报告首行均已声明实际 slug，无静默降级
- **法律**：未下载、未安装、未逆向任何 VIC 二进制；官方评估为 Windows MSI + PC 密钥，本 Linux 环境无法合法完成

## 1. 已实现 / 已冻结（本轮产出）

| ID | 模型 | 产物 | 价值 |
|----|------|------|------|
| R1-F1 | fable（云端） | 全局架构与 SOTA 规划 | 测量链对照、分层架构、Python-first、open-core |
| R1-F2 | fable | 13 维审计 + MVP/v1/SOTA Gate | iDICs GPG / Challenge 数字锚点 |
| R1-F3 | fable | 36×8 竞品矩阵 + Top 15 楔子 | 对 VIC/MatchID/GOM/Eiko/OSS 公开差距 |
| R1-F4 | fable | P0–P9 阶段门 + 风险登记 | 技术依赖路线，非法务日历估算 |
| R1-O1 | opus-fast | HL3-2D 内核规格 | ZNSSD+ICGN、HYBRID 路径、UQ 默认开 |
| R1-O2 | opus-fast | HL3-3D 立体规格 | 不做校正重采样、标定协方差、四路闭环自检 |
| R1-O3 | opus-fast | 共享内核 + `docs/schema-hdf5.md` | 命令总线、HDF5 公开 schema |
| R1-G1 | gpt-sol | GitHub 许可证探针 | 独立实现 + 宽松许可作参照 |
| R1-G2 | gpt-sol | 基准协议 + `synth_speckle.py` | 父调度器已跑通 128² 合成平移 |
| R1-G3 | gpt-sol | 环境/合法下载探针 | CPU-only Linux，无 Wine/CUDA |

**产品定义已收敛**：HL3-2D 对标 VIC-2D 8，HL3-3D 对标 VIC-3D 11；共享 `hl3-core`；要超过的是整条测量链（采集–标定–相关–应变–可视化–Python–报告–实时），不是一个相关器 demo。

**超越策略（Top 楔子，已交叉一致）**：跨平台与自助评估；Python-first；UQ 默认输出；GPU 相关器 + 公开可复现 benchmark；open-core 可审计内核；局部+全局双内核与 FEA 原生闭环；公开 HDF5 schema。

## 2. 遗留缺陷 / 文档冲突（Round 2 必须消解）

1. **许可证 ADR 未决**：F1 倾向 Apache-2.0/BSD open-core；O3 提出 OpenCorr 为 MPL-2.0 故需文件级 copyleft 评估；G1 结论是**不要拼装 OpenCorr GPU 闭源库，独立实现 ICGN/CUDA**。Round 2 必须写出唯一 ADR。
2. **GPU 目标 vs 本环境**：架构要求 CUDA/Vulkan；G3 实测本云机无 GPU、无 CUDA、无 Wine。内核必须 CPU 参考实现为规范，GPU 为可选后端，CI 在本环境只跑 CPU。
3. **吞吐口号需统一协议**：F1 ≥5×10⁶ POI/s、O2 ≥3×10⁶ 3D 点/s、F4 >1×10⁶ GPU vs VIC 公开 1×10⁶/32 核 CPU。必须采用 G2 的公平对比协议（子集、阶数、2D/3D、硬件清单），禁止无协议数字。
4. **显微镜畸变专利**：O2 检索到 US7133570B1 公开状态 Expired-Fee-Related（约 2025-05-11）；F4 仍要求 FTO 书面结论后才写显微镜模块。Round 2 维持：**零显微镜实现代码，只做法务检索清单**。
5. **VIC UI 未知**：无合法 Windows 评估，iris/vicpyx/许可管理 UX 不能写进“已对齐”清单。
6. **全局 DIC 边界**：muDIC/ALDIC/EikoTwin 路线与局部 ICGN 的产品切分（核心 vs 插件）未冻结。
7. **尚无相关器代码**：只有合成散斑脚本与规格，Round 2 必须落地可测的 2D ICGN 最小内核。

## 3. 性能瓶颈（规划期）

- 本环境 4 vCPU、无 GPU → 不能在此验证 VIC 级吞吐。
- 路径无关 GPU 批处理与确定性（约化顺序、Philox RNG）是后续最大工程风险（F4 R-02）。
- 立体精度上限在标定而非相关器（Stereo Challenge 1.0 公开结论）→ P3 标定模块权重最高。

## 4. Round 2 攻坚重点（强制注入全体子代理）

1. 消解第 2 节全部冲突，输出 **单一** `MASTER_PLAN.md` 与许可证 ADR。
2. 实现 **CPU 参考 2D ICGN**（一阶），对 `synth_speckle.py` 合成平移做可重复测试（bias 目标量级 0.01 px 级，本轮先跑通再收紧）。
3. 冻结 HDF5 schema 草案与目录树，开始 `src/` 骨架（不要大而全 GUI）。
4. 补齐基准脚本：噪声底板、插值 S 曲线骨架；不下载超大 Challenge 包除非体积可接受。
5. 立体：标定+三角化接口与伪代码/轻量实现，不写显微镜。
6. 继续禁止盗版/逆向；Windows VIC 评估仍列为用户侧后续。
