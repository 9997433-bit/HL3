ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
# R1-G1：GitHub 开源 DIC 深度探针与许可证结论

## 结论先行

1. **HL3 最稳妥的产品路线不是直接拼装某一个现有工程，而是“论文级独立实现 + 许可宽松项目作测试参照”**。Ncorr C++（BSD-3-Clause）、DICe 自有代码（BSD-3-Clause 文本）、pyALDIC（BSD-3-Clause）、DuoDIC/MultiDIC（Apache-2.0）都可提供有价值的算法、工作流和测试参考；但它们分别存在年代、依赖、MATLAB、第三方组件或架构不匹配问题。
2. **OpenCorr 的 CPU 源码可用，但不是“拿来闭源即可”**：MPL-2.0 是文件级弱 copyleft，分发时被覆盖文件及其修改仍须按 MPL 提供源码。其 CUDA 加速仅提供 `OpenCorrGPU.lib/.dll` 和头文件，GUI 又明确是 shareware；两者都不应并入 HL3，除非另获书面授权。
3. **无许可证不等于可自由使用**。U-DICNet、Stereo-DICNet2 没有仓库许可证；其代码、权重和外链数据默认保留全部权利。py2DIC 只允许非商业/研究用途，也不符合 OSI 开源定义。对这些项目只能读论文、独立实现并引用。
4. **MATLAB 不是一种开源许可证**。DuoDIC、MultiDIC、Ncorr MATLAB 和 2D_FE_Global_DIC 的源码许可证分别允许一定程度的复制，但运行仍依赖商业 MATLAB/Toolbox；MathWorks 组件和 MEX 二进制不能因为项目源码是 Apache/BSD 就随意再分发。HL3 应把相关数学与流程重写为 C++20/Python API。
5. **GPU 路线应自主实现**。现有可见选择不是闭源二进制（OpenCorr GPU），就是无许可证研究代码（U-DICNet、Stereo-DICNet2），或 GPL 项目。HL3 可从公开论文复现 ICGN/ICLM、FFT 初值、立体匹配和 DVC CUDA 内核，并建立自己的数值回归测试。

## 调查口径

- 快照时间：**2026-08-28 UTC**。Stars 会变化。
- “最后更新”采用 GitHub REST 的 **`pushed_at`（最后代码 push）**，而不是会被 issue、star 等活动改变的 `updatedAt`。
- 逐库读取了 GitHub 元数据、README、许可证和递归源码树；用 Web 检索交叉核对论文、DOI、GUI/GPU 分发方式。
- `3D` 指表面/立体 DIC；`DVC` 指体数据相关，二者不混用。
- `Tests` 只把可执行单元/回归/集成测试算作正式测试；文件名为 `test.py` 的推理脚本或示例数据会明确标成“脚本/样例”。
- 本轮未克隆或复制任何第三方代码进 HL3，也未接触任何破解商业软件。

## 必查仓库能力总表

| Repo / URL | Stars | License SPDX | Language | Last push | 2D | 3D | DVC | GUI | GPU | Stereo | Tests |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| [dicengine/dice](https://github.com/dicengine/dice) | 424 | `NOASSERTION`；正文实质为 BSD-3-Clause | C++ | 2024-03-11 | 是 | 是 | 否 | 是，基础 2D/立体 | 否；MPI + 线程 CPU | 是 | **强**：CMake component/example/performance/regression/nightly |
| [vincentjzy/OpenCorr](https://github.com/vincentjzy/OpenCorr) | 289 | `MPL-2.0` | C++ | 2026-08-27 | 是 | 是 | 是 | 有，但 GUI 是独立 shareware | 是，但仓库只给 Windows 二进制库 | 是 | **中**：17 个 `test_*` 示例，无正式测试框架/CI |
| [justinblaber/ncorr_2D_matlab](https://github.com/justinblaber/ncorr_2D_matlab) | 189 | `BSD-3-Clause` | MATLAB + C++/MEX | 2020-05-08 | 是 | 否 | 否 | 是 | 否 | 否 | 无正式测试 |
| [justinblaber/ncorr_2D_cpp](https://github.com/justinblaber/ncorr_2D_cpp) | 59 | `BSD-3-Clause` | C++ | 2019-12-13 | 是 | 否 | 否 | 否 | 否 | 否 | **弱**：单个 `ncorr_test.cpp` + 图像样例 |
| [PolymerGuy/muDIC](https://github.com/PolymerGuy/muDIC) | 196 | `MIT` | Python | 2022-02-08 | 是，FE/全局式 | 否 | 否 | 仅轻量网格 GUI/可视化 | 否 | 否 | **中强**：nose tests、CircleCI、codecov |
| [zachtong/pyALDIC](https://github.com/zachtong/pyALDIC) | 24 | `BSD-3-Clause` | Python | 2026-08-26 | 是，局部 IC-GN + 全局 AL/ADMM | 否 | 否 | 是，PySide6 | 否 | 否 | **强**：大量 unit/integration/regression/GUI/fuzz/perf 测试和 CI |
| [SolavLab/DuoDIC](https://github.com/SolavLab/DuoDIC) | 86 | `Apache-2.0` | MATLAB | 2025-10-21 | 是，内置 Ncorr | 是 | 否 | MATLAB 交互流程 + Ncorr GUI | 否 | 双目 | 无正式自动测试；有刚体/拉伸验证样例 |
| [MultiDIC/MultiDIC](https://github.com/MultiDIC/MultiDIC) | 248 | `Apache-2.0` | MATLAB | 2025-10-23 | 是，内置 Ncorr | 是，多视图表面拼接 | 否 | MATLAB 交互流程 + Ncorr GUI | 否 | 多相机/多双目对 | 无正式自动测试；有样例数据 |
| [YangMechanicsGroupUTAustin/2D_FE_Global_DIC](https://github.com/YangMechanicsGroupUTAustin/2D_FE_Global_DIC) | 31 | `BSD-2-Clause` | MATLAB + MEX | 2025-11-12 | 是，全局 FE | 否 | 否 | 否 | 否 | 否 | 无正式测试；有 Sample 12/手册 |
| [USTC-PMLAB/U_DICNet](https://github.com/USTC-PMLAB/U_DICNet) | 12 | **无许可证** | Python/PyTorch | 2023-02-24 | 是 | 否 | 否 | 否 | 是，要求 CUDA/cuDNN | 否 | 无；只有训练、推理和 test dataset 参数 |
| [Geod-Geom/py2DIC](https://github.com/Geod-Geom/py2DIC) | 73 | **无 SPDX；自定义“仅研究/非商业”** | Python | 2026-05-24 | 是，模板匹配 | 否 | 否 | 是 | 否 | 否 | 无正式测试；`LabTest` 是实验数据 |
| [sayyedalimrj/DICStudio](https://github.com/sayyedalimrj/DICStudio) | 1 | GitHub `NOASSERTION`；许可证正文为 `BSD-3-Clause` | Python 3.8 + Ncorr `.pyd` | 2025-12-01 | 是 | 否 | 否 | 是，Qt/Windows | 否 | 否 | 无正式测试；只有示例和预编译依赖 |
| [rolandsurlis/Cyclops-2](https://github.com/rolandsurlis/Cyclops-2) | 1 | `MIT` | Python + CAD | 2026-06-05 | 否 | **仅立体采集硬件**，不是求解器 | 否 | 只有相机 preview 脚本 | 否 | 双目采集 | 无 |
| [LianpoWang/Stereo-DICNet2](https://github.com/LianpoWang/Stereo-DICNet2) | 14 | **无许可证** | Python/PyTorch | 2025-12-04 | 像素匹配子任务 | 是 | 否 | 否 | 是，CUDA | 是 | **弱**：一个 sanity/实测推理脚本，不是单元测试 |
| [Computer-Aided-Validation-Laboratory/stereobenchmarks](https://github.com/Computer-Aided-Validation-Laboratory/stereobenchmarks) | 0 | `MIT` | 数据集 | 2025-04-04 | 有 2D deformation 数据 | 有 3D deformation 数据 | 否 | 否 | 否 | 有 calibration/双目标定数据 | 本身就是约 740 MB benchmark 数据；无执行器 |

## 源码结构与工程成熟度证据

- **DICe**：`src/api`, `base`, `core`, `fft`, `global`, `mesh`, `opencv`, `ioutils` 分层清楚；`tests/component`, `examples`, `performance`, `regression` 很完整。它是本轮最好的传统 DIC 回归测试结构参考，但依赖 Trilinos，构建和嵌入成本高。
- **OpenCorr**：CPU 源码模块覆盖 `oc_fftcc`, `oc_icgn`, `oc_iclm`, `oc_nr`, `oc_sift`, `oc_epipolar_search`, `oc_stereovision`, `oc_calibration`, `oc_strain`；示例同时覆盖 2D、立体和 DVC。短板是没有可见的自动断言体系，GPU 实现源码也不在仓库。
- **Ncorr MATLAB/C++**：MATLAB 版将 GUI 与 C++/MEX 算法结合；C++ 版拆成 `Image2D/ROI2D/Disp2D/Strain2D`。两者都易读，但维护停滞且现代 CI、跨平台打包和并行后端不足。
- **muDIC**：`IO/elements/mesh/solver/post/vlab` 模块化，`vlab` 提供散斑、形变、噪声、降采样；纯 Python 适合生成 oracle 和教学，不适合作为 HL3 高吞吐内核。
- **pyALDIC**：`core/gui/io/mesh/solver/strain/utils` 分层和测试密度突出，覆盖自适应四叉树、裂纹/孔洞掩膜、FFT 初值、IC-GN、ADMM、导出和 GUI 状态。它是 Python API 与产品测试设计的优质参考。
- **DuoDIC/MultiDIC**：流程分别围绕标定、Ncorr 2D 相关、3D 重建、后处理；MultiDIC 进一步进行多表面配准/去重叠/拼接。二者把 Ncorr 和多个第三方 MATLAB 库直接放入 `lib_ext`，若复制代码必须逐项保留各自许可证。
- **2D_FE_Global_DIC**：包含 Q4/T3 网格、整数搜索、全局 ICGN、位移/应变平滑等函数和 `ba_interp2` MEX。代码适合核对方程流程，不适合直接成为现代跨平台内核。
- **U-DICNet**：只有 dataset、training、inference、模型和 vendored `pandas/_libs` 等研究仓库布局；README 末尾还留有 merge-conflict 标记，工程治理弱。
- **py2DIC**：主要实现集中在 `sources/GUI.py` 及模板匹配流程，数据量远大于代码；适合作为 OpenCV 模板匹配基线，不宜作为核心。
- **DICStudio**：`src` 侧重 preprocessing、automation、plot、point inspector 和 fracture workflow，数值核心依赖 Windows/Python 3.8 的预编译 `ncorr.pyd`，并捆绑 FFTW/LAPACK/OpenCV 等 DLL。
- **Cyclops-2**：仓库实质是 CAD 文件加 `captureTimelapse.py`、`cvPreview.py`；它解决同步双目采集原型，不解决标定、相关、三角化或应变。
- **Stereo-DICNet2**：`UniDIC/dataset/loss/utils/main.py/test.py` 是论文复现型目录，训练数据放在外部百度网盘，缺少许可、固定环境、CI 和定量回归。
- **stereobenchmarks**：包含 `2D_deformation`, `3D_deformation`, `calibration/{faceon,symmetric}`；README 只有一句话，优点是许可证清楚，缺点是数据说明、生成参数和验收脚本缺失。

## 每个必查项目：HL3 可复用、应重写、应引用

| Repo | HL3 可合法复用 | 应独立重写/隔离 | 应引用 |
|---|---|---|---|
| DICe | DICe 自有 BSD-3-Clause 代码、接口思想和测试组织；保留版权、条件和免责声明 | **排除/替换 Triangle**：仓库 NOTICE 明示 Triangle 不得未经许可用于商业产品；现代化依赖、GPU、数据模型和 GUI 应重写 | Turner, *DICe Reference Manual*, SAND2015-10606 O (2015)；[DOE Code](https://www.osti.gov/doecode/biblio/3620) |
| OpenCorr | 可作为独立 MPL 插件或动态库；原 MPL 文件及修改保持 MPL 并提供对应源码 | 闭源核心若不接受文件级披露，应按论文重写；**不得把 GPU `.lib/.dll` 或 shareware GUI 当 MPL 源码复用** | Jiang, *OpenCorr*, OLE 165, 107566 (2023), [DOI](https://doi.org/10.1016/j.optlaseng.2023.107566)；GPU/立体/DVC 用到时再引对应论文 |
| Ncorr MATLAB | BSD-3-Clause 允许复制/修改；可取 ROI、传播、应变和 GUI 工作流思想 | MATLAB GUI、MEX 编译链和老式状态模型应重写；HL3 不应依赖 MATLAB Runtime | Blaber, Adair, Antoniou, *Ncorr*, Exp. Mech. 55 (2015), [DOI](https://doi.org/10.1007/s11340-015-0009-1) |
| Ncorr C++ | BSD-3-Clause，最适合用作传统 2D 数值参考或经审计后的独立组件 | 现代 C++20 API、SIMD/任务并行、GPU、异常/错误模型和大规模测试应重写 | 同一 Ncorr 论文 |
| muDIC | MIT；`vlab` 的散斑/形变/噪声/降采样和测试数据生成很适合作为验证工具 | 纯 Python FE/求解器不宜直接承担生产性能；核心重写为共享 C++/GPU | Olufsen et al., *μDIC*, SoftwareX (2019), [DOI](https://doi.org/10.1016/j.softx.2019.100391) |
| pyALDIC | BSD-3-Clause；可复用测试思路、Python 原型、自适应网格/掩膜逻辑，保留署名 | 为 HL3 重写高性能 IC-GN/ADMM/FEM 内核和统一数据布局；核查与原 MATLAB AL-DIC 的派生边界 | Tong & Yang, *pyALDIC*, [arXiv DOI](https://doi.org/10.48550/arXiv.2607.22755)；软件 [Zenodo DOI](https://doi.org/10.5281/zenodo.19521071) |
| DuoDIC | Apache-2.0 主项目可复用，保留 LICENSE/NOTICE/修改说明；内置 Ncorr 部分继续遵守 BSD | MATLAB 相机标定、四步脚本和可视化重写成 C++/Python；不要照搬 MathWorks Toolbox 实现或捆绑 MATLAB | Solav et al., *DuoDIC*, JOSS, [DOI](https://doi.org/10.21105/joss.04279)；同时引用 Ncorr |
| MultiDIC | Apache-2.0 主项目的多视图标定、表面拼接流程可参考/复用；逐项保留 `lib_ext` 许可证 | 多相机图优化、鲁棒配准、重叠融合、现代可视化和非 MATLAB 数据模型应重写 | Solav et al., *MultiDIC*, IEEE Access 6 (2018), [DOI](https://doi.org/10.1109/ACCESS.2018.2843725)；同时引用 Ncorr |
| 2D_FE_Global_DIC | BSD-2-Clause MATLAB 源码可复用，保留通知；样例可作人工核对 | 不分发仓库中的预编译 MEX；重写 Q4/T3 装配、稀疏求解、正则化和并行实现 | 软件 [10.22002/D1.1981](https://doi.org/10.22002/D1.1981)；Yang & Bhattacharya AL-DIC [10.1007/s11340-018-00457-0](https://doi.org/10.1007/s11340-018-00457-0) |
| U-DICNet | **代码、权重、仓库数据均不可复用**，除非作者补许可证/书面授权 | 只依据论文独立训练网络；自行生成数据、权重和评测；不要复制其 FlowNet 派生代码 | Lan et al., *Deep learning for complex displacement field measurement* (2022), [DOI](https://doi.org/10.1007/s11431-022-2122-y) |
| py2DIC | 对商业 HL3 **不可复用**；只能在许可范围内作外部研究对比，或向作者取得商业授权 | OpenCV 模板匹配、平滑和 GUI 全部 clean-room 重写 | Belloni et al., *py2DIC*, Sensors 19, 3832 (2019), [DOI](https://doi.org/10.3390/s19183832) |
| DICStudio | 仓库 Python 源码按 BSD-3-Clause 可复用并保留署名；Ncorr 派生部分同时保留 Ncorr 署名 | 不复制其预编译 `.pyd`/DLL 包；Qt6、跨平台采集、自动化和断裂后处理应自主实现并测试 | 仓库 README 的论文项仍是占位符；可引用 2025 ACI poster 的 [Zenodo DOI](https://doi.org/10.5281/zenodo.17466555)，数值核心另引 Ncorr |
| Cyclops-2 | MIT 覆盖的采集脚本/CAD 可复用，保留 MIT 通知；适合低成本硬件参考 | HL3 应实现 GenICam/厂商 SDK、硬件触发、时间戳、丢帧检测和标定闭环 | *Cyclops²: CAD files and software scripts for stereo DIC*, [Zenodo DOI](https://doi.org/10.5281/zenodo.20543913) |
| Stereo-DICNet2 | **无许可证：代码、模型和百度网盘数据均不可复用** | 按论文独立实现 FCC/轻量 RAFT、自己训练并验证；不要把“可下载”误作授权 | Feng & Wang, *Stereo-DICNet2*, Exp. Mech. (2025), [DOI](https://doi.org/10.1007/s11340-025-01241-7) |
| stereobenchmarks | MIT；可作为外部测试资产，附许可证、锁定 commit 和 checksum | 不建议把约 740 MB 数据塞进主源码仓库；补写读取器、真值规范、容差和 CI 小切片 | 暂无论文/DOI；引用仓库 URL、作者机构、commit 和访问日期 |

## GitHub 定向搜索结果

### 1. ICGN DIC

GitHub 仓库名搜索 `ICGN` 噪声很大，真正相关项目常只在 README/源码中出现。结合 Web 与仓库核验后，值得关注的是：

| Repo | Stars | SPDX | 价值 | HL3 处理 |
|---|---:|---|---|---|
| [OpenCorr](https://github.com/vincentjzy/OpenCorr) | 289 | MPL-2.0 | 1/2 阶 2D ICGN、1 阶 3D ICGN、FFT/SIFT 初值、CPU 并行 | CPU 可隔离复用；闭源内核与 CUDA 重写 |
| [gventer/SUN-DIC](https://github.com/gventer/SUN-DIC) | 20 | MIT | Python GUI/API，IC-GN + IC-LM、仿射/二次 shape、AKAZE 初值 | 可审计后复用测试/原型；性能内核重写 |
| [DennisPureza/DICLab2D-v1.1](https://github.com/DennisPureza/DICLab2D-v1.1) | 0 | MIT | Julia，IC-GN/BS-GN、高阶 shape；已有 SoftwareX 论文 [10.1016/j.softx.2026.102532](https://doi.org/10.1016/j.softx.2026.102532) | 新且未成熟，作公式/测试交叉验证 |
| [TWANG006/TW](https://github.com/TWANG006/TW) | 10 | BSD-3-Clause | 混合 CPU/GPU 实时动态 DIC | 许可友好，但先做来源、构建和数值审计 |
| [NiuKeke/ICGN_CUDA](https://github.com/NiuKeke/ICGN_CUDA) / [CUDA_ICGN_DIC](https://github.com/madhavs004/CUDA_ICGN_DIC) | 0 / 0 | 无 / 无 | CUDA/ICGN 研究尝试 | 不复用，只作为存在性线索 |

### 2. Digital Volume Correlation

| Repo | Stars | SPDX | 价值 | HL3 处理 |
|---|---:|---|---|---|
| [OpenCorr](https://github.com/vincentjzy/OpenCorr) | 289 | MPL-2.0 | 3D FFTCC、ICGN、SIFT、strain，CPU；GPU 为二进制 | CPU 隔离或重写；GPU 重写 |
| [FranckLab/ALDVC](https://github.com/FranckLab/ALDVC) | 37 | MIT | MATLAB 混合 local/global 自适应拉格朗日 DVC | 方程和样例价值高；C++/GPU 重写 |
| [SCUT-CCNL/3DSIFT-PiDVC](https://github.com/SCUT-CCNL/3DSIFT-PiDVC) | 15 | GPL-3.0 | 3D SIFT + path-independent DVC + OpenMP | 闭源 HL3 不并入；按论文重写 |
| [hereon-mbs/VolRAFT](https://github.com/hereon-mbs/VolRAFT) | 11 | MIT | 微 CT 体光流/学习式 DVC | 可复用研究管线；模型和数据另审计 |
| [TomographicImaging/iDVC](https://github.com/TomographicImaging/iDVC) | 8 | Apache-2.0 | Python DVC 用户界面 | GUI/体数据交互参考，不等于完整高性能内核 |
| [brunsst/MBS-3D-OptFlow](https://github.com/brunsst/MBS-3D-OptFlow) | 3 | MIT | CUDA 变分 3D 光流、VTK/mesh 后处理 | 许可友好，适合 DVC 原型；需独立数值验证 |

另有 `spokeydokeys/DigitalVolumeCorrelation`（GPL-2.0）、`TomographicImaging/DigitalVolumeCorrelation`（GPL-3.0）、`carterbox/SURF3D`（GPL-3.0）。若 HL3 保持专有发行，不应把这些 GPL 实现链接或复制进产品。

### 3. Speckle pattern generator

| Repo | Stars | SPDX | 能力 | HL3 处理 |
|---|---:|---|---|---|
| [muDIC](https://github.com/PolymerGuy/muDIC) | 196 | MIT | 散斑、形变、噪声、降采样、虚拟实验 | 可直接用于测试工具，生产生成器可重写 |
| [ladisk/speckle_pattern](https://github.com/ladisk/speckle_pattern) | 28 | MIT | 可打印随机散斑，PyPI 包 | **首选可复用基线**，保留 MIT 通知 |
| [Computer-Aided-Validation-Laboratory/pyvale](https://github.com/Computer-Aided-Validation-Laboratory/pyvale) | 19 | MIT | Blender/光栅/光线追踪、FE 场映射、双目虚拟相机 | 首选高保真合成与不确定度工具 |
| [GW-Wang-thu/Generator-of-Stereo-Speckle-images-with-displacement-labels](https://github.com/GW-Wang-thu/Generator-of-Stereo-Speckle-images-with-displacement-labels) | 10 | MIT | 非线性 3D 位移、光流、视差真值 | 可用于深度/立体网络数据生成，先固定环境 |
| [AleksanderMarek/speckle](https://github.com/AleksanderMarek/speckle) | 7 | MIT | Blender 多相机、优化 serpentine pattern | 可复用场景/标定生成思路 |
| [Computer-Aided-Validation-Laboratory/specklegen-lg](https://github.com/Computer-Aided-Validation-Laboratory/specklegen-lg) | 0 | MIT | 新的 Python speckle generator | 太新，先做稳定性审计 |
| [saturosfz/glare](https://github.com/saturosfz/glare) | 0 | GPL-3.0 | Qt/C++ 生成、形变、质量评价与推荐 | 不并入闭源 HL3；论文/指标可用于独立实现 |

## 许可证兼容性规则

| 类型 | 能否进入预期可商业/可闭源 HL3 | 必做事项 |
|---|---|---|
| MIT / BSD-2 / BSD-3 | 通常可以 | 保留版权、许可和免责声明；BSD-3 不得借作者名义背书 |
| Apache-2.0 | 通常可以，且有明确专利许可 | 附 LICENSE；若有 NOTICE 则传递；标明修改；逐项审计 vendored 依赖 |
| MPL-2.0 | 可以和专有代码组成 Larger Work，但不是无条件闭源 | MPL 覆盖文件及其修改继续 MPL；分发时提供对应源码和许可告知；建议做清晰组件边界 |
| LGPL | 动态链接通常可行，但须允许用户替换/重链接 LGPL 部件并满足源码义务 | 不把 LGPL 源直接融入专有核心；交法务做发行包审计 |
| GPL / AGPL | 与预期闭源产品高风险/通常不兼容 | 不复制、不静态/动态链接进产品；AGPL 还涉及网络交互源码义务；仅外部研究比较或独立重写 |
| 无许可证 | 不可以 | GitHub 可见不产生复制、修改或再分发权；取得书面许可或只按论文 clean-room 实现 |
| “仅研究/非商业” | 不可进入商业 HL3，也不是 OSI 开源 | 取得商业授权，或完全独立实现 |
| MATLAB 项目 | 取决于项目源码许可证；“MATLAB”本身不授予源码权利 | 不复制 MathWorks Toolbox 源/二进制；确认 MATLAB Runtime 再分发条款；优先用公开方程重写 |

补充边界：

- **代码许可证不自动覆盖模型权重、外链训练集、论文插图或第三方样例数据**。每类资产单独记录来源、许可、hash 和取得日期。
- **论文允许学习思想，不允许复制论文或无许可代码的表达性实现**。采用 clean-room 规格、独立代码审查和可追溯测试；引用不是版权许可的替代品。
- **许可证兼容不等于无专利风险**。正式产品发行前仍需对关键 GPU/立体/学习式算法做专利清查。
- 未经明确授权，不下载、反编译或绕过 VIC-2D/VIC-3D/VIC-Volume 等商业软件许可。

## Reuse vs reimplement 最终建议

| HL3 子系统 | Reuse / 参考首选 | Reimplement | 禁止或隔离 | 决策 |
|---|---|---|---|---|
| 2D subset 内核 | Ncorr C++ BSD 作 oracle；DICe/OpenCorr 作交叉验证 | C++20 ZNSSD + FFT/feature 初值 + IC-GN/IC-LM + SIMD/CUDA | OpenCorr MPL 文件若不愿披露则隔离；无许可 CUDA 不用 | **重写核心** |
| 2D global/AL 内核 | 2D_FE_Global_DIC BSD、pyALDIC BSD、muDIC MIT | 统一 FE 装配、正则化、裂纹屏障、自适应网格 | MATLAB/MEX 二进制不带入 | **论文级重写，复用测试思想** |
| Stereo 3D | DuoDIC/MultiDIC Apache 流程；OpenCorr 算法参照 | 标定、时间同步、极线约束、匹配、三角化、bundle adjustment、3D strain | MathWorks Toolbox 实现、OpenCorr GUI 不带入 | **重写生产实现** |
| DVC | ALDVC MIT、MBS-3D-OptFlow MIT、VolRAFT MIT | 分块体数据、3D ICGN/光流、CUDA、out-of-core | GPL DVC、OpenCorr GPU 二进制隔离 | **作为后续独立模块** |
| GPU | 公开论文、MIT/BSD 项目测试输出 | 自有 CUDA/Vulkan 后端、确定性和 CPU/GPU 一致性测试 | OpenCorr `.lib/.dll`、U-DICNet/Stereo-DICNet2 代码/权重 | **全部自主实现** |
| GUI/API | pyALDIC 的状态/测试设计；DICStudio 的工作流概念 | Qt6 + pybind11、跨平台 session、可追溯参数和异步任务 | shareware GUI、旧 Python 3.8 `.pyd`/DLL | **重写 GUI，可借鉴 BSD 测试结构** |
| Speckle/synthetic | ladisk、muDIC、pyvale、GW-Wang-thu（均 MIT） | 为 CI 写轻量确定性 C++ generator；保留高保真 Python/Blender 工具 | GPL Glare 不进入产品 | **测试侧可复用，产品侧薄重写** |
| Benchmark | stereobenchmarks MIT；DICe/pyALDIC 测试方法 | HL3 自有 manifest、真值 schema、容差、checksum、CI 小样本 | 未明确许可的挑战数据不直接再分发 | **外部资产锁版本，不 vendor 大数据** |
| Camera acquisition | Cyclops-2 MIT 作双目原型参考 | GenICam HAL、硬触发/PTP、曝光同步、buffer/丢帧监控 | 厂商 SDK 按各自 EULA 插件化 | **重写工业采集层** |

最终落点：**直接复用优先放在测试生成、样例读取、非核心工具和许可清晰的独立插件；数值核心、GPU、工业采集、GUI 与统一数据模型全部由 HL3 独立实现。** 这样既能吸收开源生态的验证价值，又能避免 MPL 文件披露、GPL 传染、非商业限制、无许可证研究代码和 MATLAB Runtime 绑定。
