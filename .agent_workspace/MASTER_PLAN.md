# HL3 DIC 主计划（Round 1 收敛稿，Round 2 将覆盖冲突项）

## 产品

- **HL3-2D**：单相机二维 DIC，对标并超过 VIC-2D 8。
- **HL3-3D**：双目/多目立体 DIC，对标并超过 VIC-3D 11。
- 共享内核 `hl3-core`，Python-first，公开 HDF5 schema，CPU 参考实现为计量规范，GPU 为加速后端。

## 调度 SOP

每轮 **10** 子代理：**4×fable** (`claude-fable-5-thinking-xhigh`) + **3×opus-fast** (`claude-opus-5-thinking-high-fast`) + **3×gpt-sol** (`gpt-5.6-sol-xhigh-fast`)。共 3 轮。禁止静默降级。

## 阶段（技术依赖，非法务日历）

P0 研究冻结与法务 → P1 共享内核（ICGN+应变+HDF5）→ P2 HL3-2D MVP → P3 立体标定+HL3-3D MVP → P4 GPU 路径无关+实时 Gauge → P5 GenICam 采集 → P6 可视化+FEA+Python → P7 UQ+Challenge → P8 多相机/FFT/IR（显微镜 FTO 门）→ P9 产品化。

## 法律

禁止破解/逆向 VIC。本环境为 Linux CPU-only，不能合法安装官方 Windows 评估版。开源策略：独立实现公开算法；OpenCorr GPU 闭源库不用；无许可证仓库只读论文。

## 工作包细节

见 `round1/` 十份报告与 `ROUND1_BRIEF.md`。Round 2 必须消解许可证、吞吐协议、全局 DIC 边界等冲突。

## ADR 裁决（Round 2 · R2-F1 记录架构师，具约束力）

全文与理由见 `round2/R2-F1-sota-reconciliation.md`；与 Round 1 任何文件冲突处以该文件为准，推翻需 Round 3 书面 ADR。

| 编号 | 裁决 |
|------|------|
| RUL-01 | 许可证定案：独立重实现 + **Apache-2.0 开源内核** + open-core 专业模块闭源 + schema 文档 CC-BY-4.0；驳回 MPL 内核；禁止任何 OpenCorr 文件级复用与其 GPU 闭源二进制（追认 `round2/R2-G1-license-adr.md` ADR-LIC-001） |
| RUL-02 | **CPU float64 参考实现是计量规范**；GPU 是可选加速后端（parity 双档：通用 ≤1e-4 px，计量模式 ≤1e-6 px）；本环境 CI 只跑 CPU；"GPU-first、CPU 回退"表述作废 |
| RUL-03 | **R1-G2 §7 是唯一合法吞吐口径**；R1 各吞吐数字降格为协议绑定目标（2D：CPU32 核 ≥1e6 / GPU ≥5e6 POI/s；3D GPU ≥3e6 3D-POI/s）；同机四条件满足前禁止"比 VIC 快 X 倍"；2D 点与 3D 点永久分账 |
| RUL-04 | 显微镜/SEM 畸变：**书面 FTO 结论前零实现代码**（即使 US7133570B1 显示 Expired-Fee-Related）；仅交付法务检索清单；参数化模型 L1–L5 不受限 |
| RUL-05 | 全局/AL-DIC：**接口与数据模型一等公民随 v1 冻结**（`mode: LOCAL\|GLOBAL_FE\|ALDIC`、`GridKind::FeMesh`、统一 HDF5 schema）；实现分期——v1 仅 LOCAL，GLOBAL_FE 为 v1.x 官方 beta，ALDIC 为 v2；均为官方内核模块而非第三方插件 |
| RUL-06 | VIC UI/iris/vicpyx 认知强制挂"公开资料推断 + 置信度"标签，永不进"已对齐"清单；实测仅限用户自有合法 Windows 工作站 |
| RUL-07 | Round 2 必须落地 CPU 一阶 2D ICGN 最小内核 + `synth_speckle.py` 可重复测试（G2 §2.3 门槛，未达标 xfail 登记，禁止放宽门槛） |
| RUL-08 | 文档效力顺序：`LEGAL.md` → R2-F1 裁决 + ADR-LIC-001 → F2 Gate 表 → G2 协议 → O1/O2/O3 规格 → 其余；空间分辨率 L10%/L20% 双口径并报、对榜单用其官方口径 |

**超越定义已冻结**（R2-F1 §2）：超越成立 ⇔ A 组精度平权 6 项全过 + B 组显著优势 ≥4/6（吞吐/实时/TTFR/跨平台/GPG 内建/FEA 闭环）+ C 组独有能力全过（可复现性/UQ 默认化/开放 schema），全部锚定公开数据与协议，附可复算证据包。
