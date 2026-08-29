# 开源 / 学术 DIC 生态（GitHub + 文献）

调研日期：2026-08-28。许可证以仓库当时声明为准，落地前必须复核。

## 核心开源引擎

| 项目 | 语言 | 许可 | Stars（约） | 能力摘要 |
|------|------|------|-------------|----------|
| [dicengine/dice](https://github.com/dicengine/dice) | C++ | 见仓库 | 424 | Sandia 立体 DIC；MPI+线程；GUI+CLI；局部+正则全局 |
| [vincentjzy/OpenCorr](https://github.com/vincentjzy/OpenCorr) | C++ | MPL-2.0 | 289 | 2D / 立体 3D / DVC；ICGN；GPU ICGN；Jiang 2023 OL&E |
| [justinblaber/ncorr_2D_matlab](https://github.com/justinblaber/ncorr_2D_matlab) | MATLAB | — | 经典 2D | RG-DIC；许多工具箱的相关内核 |
| [PolymerGuy/muDIC](https://github.com/PolymerGuy/muDIC) | Python | — | 常用科研 | 有限元全局 DIC |
| [zachtong/pyALDIC](https://github.com/zachtong/pyALDIC) | Python | — | 混合局部+全局 | IC-GN + ADMM/FEM 正则 |
| [SolavLab/DuoDIC](https://github.com/SolavLab/DuoDIC) | MATLAB | Apache-2.0 | 立体 | Ncorr + MATLAB 标定 + 3D 应变 |
| MultiDIC | MATLAB | — | 多相机 | 3 相机以上 |
| YangMechanicsGroupUTAustin/2D_FE_Global_DIC | MATLAB | — | 全局 FE-DIC | 运动学协调 + 正则 |
| USTC-PMLAB/U_DICNet | — | — | 深度学习 | 高阶梯度变形估计 |
| LianpoWang/Stereo-DICNet2 | — | — | 立体 DL | 散斑立体匹配网络 |
| Geod-Geom/py2DIC | Python | — | 2D | 轻量 2D |
| sayyedalimrj/DICStudio | Python | — | 2D GUI | 受 Ncorr 启发 |
| rolandsurlis/Cyclops-2 | — | — | 硬件 | 双 Pi 相机低成本 3D-DIC |

## 算法清单（SOTA 积木，不是 VIC 源码）

1. **相关准则**：ZNCC、ZNSSD（光照鲁棒）。
2. **整数像素**：FFT-CC / 粗搜索。
3. **亚像素**：ICGN（一阶/二阶形函数）；正向加性 vs 逆合成。
4. **路径**：可靠性引导（RG-DIC）vs 路径无关（种子+并行）。
5. **立体**：张正友标定、立体校正、极线约束、三角化、畸变模型。
6. **应变**：位移梯度 → 工程/格林-拉格朗日/欧拉-阿尔曼西/主应变；PLS 平滑窗（VSG 尺寸效应）。
7. **全局 DIC**：FE 网格 + 正则；AL-DIC 局部-全局耦合。
8. **不确定度**：匹配质量、标定残差、空间分辨率 vs 噪声（iDICs GPG）。
9. **DL**：Stereo-DICNet 等，作种子/大变形/遮挡补强，不替代计量级 ICGN，除非通过 Challenge 证明。

## 评测与标准

- iDICs Good Practices Guide（Edition 2 含全局 DIC）。
- 2D-DIC Challenge / Stereo-DIC Challenge 图像集。
- 噪声底板、刚体平移/离面误差、虚拟应变片尺寸扫描。

## 商业对照（除 VIC）

- ZEISS GOM ARAMIS / Correlate：工业计量、点跟踪+DIC。
- MatchID：不确定度、性能分析、VFM、FE 验证叙事强。
- Dantec Istra4D、LaVision DaVis、EikoSim EikoTwin（全局 FE-DIC）。

HL3 的差异化不应只抄 VIC 菜单，而应吸收 MatchID 的 UQ、EikoSim 的 FE 闭环、OpenCorr/DICe 的可复现内核，再用现代 GPU/跨平台/Python-first 超过 VIC 的封闭桌面体验。
