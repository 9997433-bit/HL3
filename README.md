<!-- SPDX-License-Identifier: Apache-2.0 -->

# HL3

**An open, auditable digital image correlation kernel — 2D and stereo, CPU reference first, with uncertainty and a published file format as first-class citizens.**

HL3 是一套**开放、可审计**的数字图像相关（DIC）测量内核，目标覆盖 **HL3-2D**（单相机平面 DIC）与 **HL3-3D**（立体 / 多目 DIC）两条产品线，二者共用同一个 `hl3-core` 地基。

> **当前状态：S1–S4 预 alpha + Challenge 证据起步。** 这是可审计的 CPU/NumPy 测量内核 + 离线 2D 无头链，**不是** VIC 可替换产品。已从 iDICs 官方 Drive 跑通 2D Challenge Sample 15 线切割（独立 Python 计分）；Stereo 1.0 仅缓存了 Translate.zip，**没有** 3D 成绩。详见 [`.agent_workspace/challenge/IR5_CLOSE.md`](.agent_workspace/challenge/IR5_CLOSE.md)。

---

## 为什么再做一个 DIC

商用 DIC 软件在功能上已经成熟，但有三处结构性缺口，恰好是本项目的立足点：

| 缺口 | HL3 的做法 |
|------|-----------|
| **结果无法独立复核**：相关器与文件格式封闭，第三方既不能验证数字，也不能无损搬走数据 | 文件格式是**带版本号的公开规范** + 纯 h5py 参考读取器 + 结构验证器。见 [`docs/schema-hdf5.md`](docs/schema-hdf5.md)。`hl3 run` 目前仍写 `.npz`；完整 `.hl3` 写出尚未接到测量链 |
| **不确定度往往不可复算**：商业软件公开有逐点匹配/三角化 `Sigma`（且明确不含 bias） | 不确定度是**与位移场同生命周期的字段**（`u_std` / `v_std` / `w_std` / `cov_uvw`）。目前落地的是匹配项协方差，以及位移方差 → 应变标准差的传播；**重叠 subset 下预测偏紧，不得当验收置信区间** |
| **平台与脚本是二等公民**：分析端以 Windows 为主 | Python 优先、Linux/无头/CI 一等公民。VIC 已有官方 `vicpyx` 与社区扩展索引，因此「有 Python」本身不再是差异点 |

五条设计铁律（详见 [`.agent_workspace/round1/R1-O3-shared-kernel.md`](.agent_workspace/round1/R1-O3-shared-kernel.md)）：

1. **维度中立** —— 2D 是「相机数 = 1」的特例，不分叉出两套代码。
2. **Python 优先** —— 命令总线在前，界面在后。
3. **格式公开** —— 规范、参考实现、一致性套件三件套齐备才算数。
4. **确定性可复现** —— 同输入同配置逐位相同，与线程数、调度、后端无关。
5. **不确定度是一等公民** —— 不是插件，不是后处理。

## 当前能跑什么

```bash
git clone https://github.com/9997433-bit/HL3.git && cd HL3
python3 -m pip install -e '.[test,hdf5]'
python3 -m pytest -q tests src/tests        # 719 passed on this Challenge-round revision
```

运行时依赖只有 **NumPy**：`h5py` 仅在真正读写 `.hl3` 文件时需要（缺失时相关测试自动跳过而不是失败），`blake3` 缺失时哈希如实降级为 `blake2b-256`。不装包也可以直接用源码树：`PYTHONPATH=src python3 -m pytest -q tests src/tests`。

| 模块 | 已实现的内容 | 状态 |
|------|------|------|
| [`src/hl3/correlate/icgn.py`](src/hl3/correlate/icgn.py) | 一阶 + 二阶 IC-GN：ZNSSD、ZNCC、B 样条、FFT-CC、秩亏 Hessian、状态码、可选协方差 | CPU 规范实现；2D pipeline 只接线一阶 |
| [`src/hl3/strain/`](src/hl3/strain/) | PLS、工程/GL/EA/Hencky、VSG、`compute_strain` | 合成平移下应变≈0；实拍噪声门未闭合 |
| [`src/hl3/pipeline/dic2d.py`](src/hl3/pipeline/dic2d.py) | 序列相关、参考更新、应变移交；应变 pitch 取自 POI 点阵 | 2D 离线链可用 |
| [`src/hl3/pipeline/dic3d.py`](src/hl3/pipeline/dic3d.py) / [`src/hl3/stereo/`](src/hl3/stereo/) | 立体匹配、针孔三角化、合成 DLT 标定、U/V/W | **无畸变、无 Zhang、无曲面 3D 应变、无 3D CLI** |
| [`src/hl3/uq/`](src/hl3/uq/) | 位移方差 → 应变标准差 | 重叠 subset 下预测约偏紧 1.8× |
| [`src/hl3/io/hdf5_schema.py`](src/hl3/io/hdf5_schema.py) | `.hl3` 常量、读写器、校验器 | schema `1.0.0-draft.2`，未冻 1.0 |
| [`src/hl3/cli/`](src/hl3/cli/) | `python -m hl3 doctor\|run\|validate` | `run` 写 `.npz`/`.npy`，不写 `.hl3` |
| [`src/hl3/viz/`](src/hl3/viz/) | 无头 PNG/PPM（可选 matplotlib） | 不是交互查看器 |
| [`src/hl3/fea/`](src/hl3/fea/) | 内存三角网格 DIC↔节点投影 | 无 VTK/Abaqus 文件 |
| [`src/hl3/gui/`](src/hl3/gui/) | `PolygonAOI` JSON；viewer 仅依赖探测 | **未接 pipeline，不是桌面 GUI** |
| [`src/hl3/capture/mock.py`](src/hl3/capture/mock.py) | 确定性合成平移采集 | CI 用，无真实相机 |
| [`tests/test_env_guards.py`](tests/test_env_guards.py) / [`tests/test_legal_scan.py`](tests/test_legal_scan.py) | CPU-only CI 护栏与 L-2 关键词扫描 | 可用 |

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) 在 `ubuntu-latest` 上跑同一条命令，并显式置空 `CUDA_VISIBLE_DEVICES`。

三条可直接复现的入口：

```bash
PYTHONPATH=src python3 -m pytest -q tests src/tests
PYTHONPATH=src python3 -m hl3 doctor --no-selftest
PYTHONPATH=src python3 -m hl3 run --synthetic --frames 2 --size 48x48 --subset 17 --strain off --out /tmp/hl3.npz
PYTHONPATH=src python3 -m hl3 challenge download --list
```

一个最小的相关器例子（`MockCapture` 的第 1 帧相对第 0 帧整体平移 `u = +2 px`、`v = +1 px`）：

```python
from hl3.capture.mock import MockCapture
from hl3.correlate import ICGNParams, icgn_first_order

ref, tgt = (f.image for f in MockCapture(frame_count=2, shape=(128, 128), seed=7))
result = icgn_first_order(
    ref, tgt, params=ICGNParams(subset_radius=15, step=16, search_radius=4)
)
ok = result.valid                     # 36/36 收敛
print(result.u[ok].mean(), result.v[ok].mean())   # 2.0  1.0
```

这个例子是整像素位移，只用来说明 API 形状；真正的亚像素精度数字来自 `tests/test_icgn_synth.py` 里 8 倍过采样、傅里叶相移生成的合成散斑（生成器与求解器不共用插值器），见下表。

## 已实测的数字

全部来自**自生成的合成数据**，运行环境为 4 vCPU、无 GPU 的 Linux 云主机（Python 3.12.3 / NumPy 2.4.4）：

| 量 | 实测值 | 出处 |
|------|--------|------|
| IC-GN 平移精度：平均 \|误差\| | **8.08 × 10⁻⁴ px**（192×192 合成散斑，真值 `u=+0.37 / v=−0.42 px`，subset 21×21，无噪声，196 POI 全收敛；RMSE 1.10 × 10⁻³ px） | [`round2/R2-O1-icgn-impl.md`](.agent_workspace/round2/R2-O1-icgn-impl.md) §0；回归断言 `test_subpixel_translation_recovered`（门限 5 × 10⁻³ px） |
| IC-GN 相位 bias（0.0–0.9 px 扫描） | \|bias\| < 0.01 px | `test_subpixel_phase_sweep` |
| 立体：无噪声闭环重建误差 | 3.3 × 10⁻⁵ nm（数值底板） | [`round2/R2-O2-stereo-impl.md`](.agent_workspace/round2/R2-O2-stereo-impl.md) §0 |
| 立体：0.02 px 匹配噪声下的三维误差 | RMS **4.901 µm**、离面 RMS 4.717 µm（254 mm 基线 / 648 mm 工作距 / 2448×2048 会聚双目） | 同上；本轮复跑 `calibrate.main()` 复现 |
| 立体：0.02 px 检测噪声、25 个靶标位姿的标定项 | 三维 RMS 0.31 µm | 同上 |
| 立体：一阶协方差预测 / Monte-Carlo 实测标准差 | 0.994–0.998 | 同上；回归断言 `test_predicted_covariance_matches_monte_carlo_spread` |
| 插值器相位 bias 峰峰值 | 双线性 0.00466 px（正弦）/ 0.00176 px（散斑）**通过** 0.02 px 暂定门；Keys bicubic（`a=−0.5`，无预滤波）0.0386 / 0.0289 px **未通过** | [`round2/R2-G2-bench-run.md`](.agent_workspace/round2/R2-G2-bench-run.md) §3 |
| HDF5 往返 | 位移与应变对解析解逐位一致，自检文件 50.6 KiB | `python -m hl3.io.hdf5_schema selftest` |

**吞吐指标（POI/s、帧率、加速比）一律未经测量。** 本仓库的开发环境是 4 vCPU、无 GPU 的云主机，任何性能数字必须按 [`.agent_workspace/round1/R1-G2-benchmark-protocol.md`](.agent_workspace/round1/R1-G2-benchmark-protocol.md) 的公平对比协议给出完整硬件清单后才允许公布。上表也全部是合成数据，**没有**任何公开挑战集或实拍数据的成绩。

## 尚未实现

| 方向 | 现状 |
|------|------|
| 标定 | 只有基于已知三维靶点的**线性 DLT 反解**。Zhang 平面标定、棋盘/ChArUco 角点检测、LM 束调整、靶标非理想性、bootstrap 协方差 `Σ_cal` 全部未做 |
| 镜头畸变 | 完全没有。Brown–Conrady / rational / thin-prism 随真正的标定模块一起来；显微立体的非参数畸变场在拿到书面专利 clearance 意见前不进任何分支 |
| 3D 应变 | 立体链只给形貌与 `U/V/W`，**没有曲面 3D 应变** |
| 不确定度 | 匹配项与应变传播已有；重叠 POI 空间相关未建模；标定项 `Σ_cal` 未打通；不得把当前 CI 当验收区间 |
| 相关器产品接线 | 二阶形函数内核已有，2D pipeline / 立体 matcher 拒绝 `shape_order=2`；无 RG-DIC、无 partial subset、无全局 FE-DIC、无 DVC |
| IO | `hl3 run` 不写完整 `.hl3`；无 CSV/STL/MATLAB 导出；schema 未冻 1.0；无外部独立读取器 |
| 产品层 | 无真实采集、无实时、无交互查看器、无报告模板、无 FFT/ODS、无多相机拼接。`hl3.gui` 只是 AOI 侧车 + 依赖探针 |

功能差距的逐项对照（36+ 行，对 VIC-2D 8 / VIC-3D 11 / MatchID / OpenCorr / GOM / Eiko / DICe）见 [`.agent_workspace/s1s4/IR4_USER_SUMMARY.md`](.agent_workspace/s1s4/IR4_USER_SUMMARY.md) 与 [`IR4_F3_actual_gap_matrix.md`](.agent_workspace/s1s4/IR4_F3_actual_gap_matrix.md)。

## 文档

| 文件 | 内容 |
|------|------|
| [`docs/schema-hdf5.md`](docs/schema-hdf5.md) | `.hl3` / `.hl3z` 文件格式规范（CC-BY-4.0），含参考实现符号映射与冻结条件 |
| [`.agent_workspace/MASTER_PLAN.md`](.agent_workspace/MASTER_PLAN.md) · [`PROGRESS.md`](.agent_workspace/PROGRESS.md) | 总体计划与各轮进度 |
| [`.agent_workspace/LEGAL.md`](.agent_workspace/LEGAL.md) | 法律与环境红线（完整版） |
| [`.agent_workspace/round2/R2-G1-license-adr.md`](.agent_workspace/round2/R2-G1-license-adr.md) | ADR-LIC-001：许可证与独立实现边界 |
| [`.agent_workspace/round2/R2-F3-prd-surpass.md`](.agent_workspace/round2/R2-F3-prd-surpass.md) · [`R2-F1-sota-reconciliation.md`](.agent_workspace/round2/R2-F1-sota-reconciliation.md) | 统一 PRD 与具约束力的 SOTA 裁决（RUL-01..08） |
| [`.agent_workspace/round1/`](.agent_workspace/round1/) · [`round2/`](.agent_workspace/round2/) · [`round3/`](.agent_workspace/round3/) | 各轮子代理的规格、审计与实现报告 |
| [`.agent_workspace/s1s4/IR4_USER_SUMMARY.md`](.agent_workspace/s1s4/IR4_USER_SUMMARY.md) | S1–S4 代码审查 + 竞品功能对照（用户向） |
| [`.agent_workspace/research/`](.agent_workspace/research/) | 竞品公开特性基线与开源 DIC 生态调研 |

## 许可证

由 **ADR-LIC-001** 约束：

| 资产 | 许可证 |
|------|--------|
| 内核、CLI、Python 绑定、读写器、测试与原创示例（仓库默认） | `Apache-2.0`（见 [`LICENSE`](LICENSE)，包元数据同样声明 `Apache-2.0`） |
| `docs/schema-*.md` 等规范性 schema 文档 | `CC-BY-4.0` —— 刻意与代码分开授权，任何人都可以独立实现兼容读写器 |
| 后续商业 GUI / 采集 / 许可管理层 | `LicenseRef-HL3-Commercial`，独立组件，不受根 Apache-2.0 自动覆盖 |

## 法律声明 / Legal notice

**本项目与 Correlated Solutions, Inc. 无任何关联，不是 VIC-2D / VIC-3D 的衍生物、移植或替代品。VIC 及相关名称为其各自所有者的商标，此处仅用于说明性的公开对标。**

本仓库全程遵守以下边界（完整版见 [`.agent_workspace/LEGAL.md`](.agent_workspace/LEGAL.md)）：

- **不下载、不传播、不安装任何破解或未授权的商业 DIC 软件**，包括 VIC-2D / VIC-3D / VIC-EDU / VIC-Volume。
- **不反编译、不逆向、不生成密钥、不绕过许可证。** 官方评估版是 Windows 安装包加 PC 专属密钥流程，本项目的 Linux 开发环境无法合法完成该闭环，因此**没有**任何一行代码或文档来自对商业二进制的观察。
- **不把专有手册或二进制中的未公开实现细节写进本仓库。** 所有算法（ZNCC/ZNSSD、IC-GN、立体标定、三角化、应变张量、平滑）均依据**已发表文献与公开标准独立实现**，贡献记录须列出所依据的论文与独立测试证据。
- **不 vendor、不改写、不翻译 OpenCorr 等 MPL/copyleft 项目的任何源文件**；公开算法思想可以独立实现，代码资产不可复制。可以引用其论文与公开可复核的结果。
- 与商业产品的功能对比一律基于**公开产品页、公开宣传材料与已发表文献**，不基于任何私自获取的软件。

这条边界不只是承诺：[`tests/test_env_guards.py`](tests/test_env_guards.py) 会在测试里断言 CI 不运行于 Windows、不存在 `HL3_VIC_HOME` / `VIC_2D_HOME` / `VIC_3D_HOME` 等变量，并要求 CPU-only 车道显式声明，越界即测试失败。

如果你持有商业 DIC 软件的**合法**许可证，在你自己的机器上做界面走查是你的权利；但相关观察不会、也不得被并入本仓库。

_English summary: HL3 is an independent, clean-room open-source DIC kernel. It is not affiliated with, derived from, or reverse-engineered from any commercial DIC product. No pirated software was downloaded, installed, decompiled, or inspected at any point; every algorithm is implemented from published literature and public standards. All figures quoted above come from self-generated synthetic data on a 4 vCPU CPU-only host; throughput has not been measured and no benchmark-suite results are claimed._
