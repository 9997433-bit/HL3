# IR4 收口（父调度器）

用户要求：S4 完成后，把本阶段全部代码系统检查一遍，结合一开始的对标软件与全网资料，判断算法能否对标甚至超越，并一一对比功能差距。

## 调度

10 个子代理（4 fable + 3 opus-fast + 3 gpt-sol）产出 IR4_F1–F4、IR4_O1–O3、IR4_G1–G2 与 `IR4_USER_SUMMARY.md`。本文件只记录收口动作，不替代用户总结。

## 本轮代码收口（审查发现问题后的最小修复）

1. **BUG-1**：`dic2d.strain_step_px` 从 POI 点阵读真实 pitch，不再把 `config.step` 当应变网格间距。各向异性点阵在应变开启时直接 raise。
2. **BUG-2**：`Dic2DConfig` 对 `shape_order != 1` 显式拒绝，与 `stereo.match` 对齐；CLI `--shape-order 2` 因此 exit 2。
3. **GUI 入口**：`hl3.gui.viewer` 先处理 `--help`，并补 `__main__` 守卫。
4. **L-2 流程**：新增 `legal/scan-allowlist.txt` 与 `tests/test_legal_scan.py`；二阶 IC-GN 注释去掉会误触发正则的断裂力学用词。
5. **S4 产品面**：CLI `run` / `doctor`、无头 viz、FEA 投影、AOI JSON、console script 合入主工作分支。

未在本轮实施（明确推迟）：pipeline→`.hl3` 写出、Zhang/畸变标定、3D 曲面应变、UQ 空间相关、Challenge 数据、S5 GPU、S6 采集实时。

## 判定（不可宣传为已对标 / 已超越）

- 超越公式 A/B/C：**三个条件全部不满足**。见 `IR4_F4_exceed_rescore.md`。
- 36 项功能矩阵（S4 实测列）：DONE 6 / PARTIAL 11 / MISSING 15 / LEGAL-BLOCKED 1 / WONT-V1 3。见 `IR4_F3_actual_gap_matrix.md`。
- 算法：2D IC-GN / PLS / 张量族与文献一致，合成精度具备实验室原型级竞争力；**没有** VIC/MatchID/OpenCorr 同机同图证据，3D 无真实标定。
- 2026 年 VIC 公开面刷新：VIC-3D 11.2/11.4、VIC-2D 8、社区扩展索引、`vicpyx`、免许可只读 Viewer。UQ 不得再写成「别人只有相关系数」。见 `IR4_O1_web_refresh.md`。

完整用户向总结：`IR4_USER_SUMMARY.md`。
