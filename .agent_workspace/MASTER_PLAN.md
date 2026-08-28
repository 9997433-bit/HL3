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
