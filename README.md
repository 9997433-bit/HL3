<!-- SPDX-License-Identifier: Apache-2.0 -->

# HL3

**An open, auditable digital image correlation kernel — 2D and stereo, CPU reference first, with uncertainty and a published file format as first-class citizens.**

HL3 是一套**开放、可审计**的数字图像相关（DIC）测量内核，目标覆盖 **HL3-2D**（单相机平面 DIC）与 **HL3-3D**（立体 / 多目 DIC）两条产品线，二者共用同一个 `hl3-core` 地基。

> **当前状态：Round 2 / 3，预 alpha。** 这是一个规划与骨架阶段的仓库，不是可用于生产测量的软件。已有可运行代码的部分只有 CPU 参考内核、立体三角化原型、合成采集与 HDF5 容器读写，且全部以「先正确、后快」为原则实现。

---

## 为什么再做一个 DIC

商用 DIC 软件在功能上已经成熟，但有三处结构性缺口，恰好是本项目的立足点：

| 缺口 | HL3 的做法 |
|------|-----------|
| **结果无法独立复核**：相关器与文件格式封闭，第三方既不能验证数字，也不能无损搬走数据 | 文件格式是**带版本号的公开规范** + 纯 h5py 参考读取器 + 一致性测试套件。见 [`docs/schema-hdf5.md`](docs/schema-hdf5.md) |
| **不确定度是事后报告**：多数实现只给一个相关系数 | 不确定度是**与位移场同生命周期的字段**（`u_std` / `v_std` / `w_std` / `cov_uvw`），并按图像噪声、匹配病态、标定误差三来源分解 |
| **平台与脚本是二等公民**：Windows-only、Python 接口后加 | Python 优先、跨平台；GUI 只是命令总线的一个客户端，每个动作先有可序列化命令、再有按钮 |

五条设计铁律（详见 [`.agent_workspace/round1/R1-O3-shared-kernel.md`](.agent_workspace/round1/R1-O3-shared-kernel.md)）：

1. **维度中立** —— 2D 是「相机数 = 1」的特例，不分叉出两套代码。
2. **Python 优先** —— 命令总线在前，界面在后。
3. **格式公开** —— 规范、参考实现、一致性套件三件套齐备才算数。
4. **确定性可复现** —— 同输入同配置逐位相同，与线程数、调度、后端无关。
5. **不确定度是一等公民** —— 不是插件，不是后处理。

## 当前能跑什么

```bash
git clone https://github.com/9997433-bit/HL3.git && cd HL3
python -m pip install -e '.[test,hdf5]'
python -m pytest -q tests src/tests
```

| 模块 | 内容 | 状态 |
|------|------|------|
| `src/hl3/correlate/icgn.py` | CPU 一阶（仿射）IC-GN 相关器，ZNSSD 判据、B 样条插值 | 参考实现，是所有加速后端必须复现的规范 |
| `src/hl3/stereo/` | 针孔投影、由投影矩阵解析求基础矩阵、四档三角化 | 原型 |
| `src/hl3/io/hdf5_schema.py` | `.hl3` 容器的组名/属性/位域常量 + 参考读写器 + 结构验证器 | schema 草案已冻结为 `1.0.0-draft.2` |
| `src/hl3/capture/mock.py` | 确定性无硬件采集，供 CPU-only CI 使用 | 可用 |

HDF5 容器的自检（未装 h5py 时会打印跳过原因并正常退出）：

```bash
python -m hl3.io.hdf5_schema selftest
```

## 尚未实现

标定求解、应变算子、不确定度传播、全局 FE-DIC、GPU 后端、Zarr 容器、命令总线、GUI、采集硬件对接。吞吐指标一律**未经测量**：本仓库的开发环境是 4 vCPU、无 GPU 的 Linux 云主机，任何性能数字必须按 [`.agent_workspace/round1/R1-G2-benchmark-protocol.md`](.agent_workspace/round1/R1-G2-benchmark-protocol.md) 的公平对比协议给出硬件清单后才允许公布。

## 文档

| 文件 | 内容 |
|------|------|
| [`docs/schema-hdf5.md`](docs/schema-hdf5.md) | `.hl3` / `.hl3z` 文件格式规范（CC-BY-4.0） |
| [`.agent_workspace/MASTER_PLAN.md`](.agent_workspace/MASTER_PLAN.md) | 总体计划 |
| [`.agent_workspace/round1/`](.agent_workspace/round1/) · [`round2/`](.agent_workspace/round2/) | 各轮子代理的规格、审计与实现报告 |
| [`.agent_workspace/round2/R2-G1-license-adr.md`](.agent_workspace/round2/R2-G1-license-adr.md) | ADR-LIC-001：许可证与独立实现边界 |

## 许可证

由 **ADR-LIC-001** 约束：

| 资产 | 许可证 |
|------|--------|
| 内核、CLI、Python 绑定、读写器、测试与原创示例（仓库默认） | `Apache-2.0`（见 [`LICENSE`](LICENSE)） |
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

如果你持有商业 DIC 软件的**合法**许可证，在你自己的机器上做界面走查是你的权利；但相关观察不会、也不得被并入本仓库。

_English summary: HL3 is an independent, clean-room open-source DIC kernel. It is not affiliated with, derived from, or reverse-engineered from any commercial DIC product. No pirated software was downloaded, installed, decompiled, or inspected at any point; every algorithm is implemented from published literature and public standards._
