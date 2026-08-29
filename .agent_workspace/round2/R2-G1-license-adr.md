ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast
# ADR-LIC-001：HL3 许可证、独立实现与显微镜 FTO 边界

- **状态**：已接受（Accepted），对 HL3 具有约束力
- **生效日期**：2026-08-28
- **适用范围**：HL3 源码、规范文档、发行包、依赖、测试资产与后续 GUI
- **替代关系**：消解 Round 1 中 Apache/BSD、MPL 复用及闭源边界的未决项；后续只能由新的书面 ADR 替代

本 ADR 是工程治理决定，不替代律师意见。专利 FTO、Qt 商业授权和正式产品发行仍须由合格法务书面确认。

## 1. 许可证决定

| 资产 | 约束性许可证决定 | SPDX 表达式 | 发行边界 |
|---|---|---|---|
| `hl3-core`、CPU/GPU 数值内核、CLI、Python 绑定、官方读写器、测试与原创示例代码 | Apache License 2.0 | `Apache-2.0` | 仓库根 `LICENSE` 是默认代码许可证；源文件和包元数据应写入 SPDX 标识 |
| `docs/schema-*.md` 等规范性 schema 文档 | Creative Commons Attribution 4.0 International | `CC-BY-4.0` | 文档必须明确署名和许可证；该例外优先于根目录 Apache-2.0，使第三方可独立实现兼容读写器 |
| 后续商业 GUI、采集与许可管理层 | 专有商业许可，独立组件/发行包 | `LicenseRef-HL3-Commercial` | 不受根目录 Apache-2.0 自动覆盖；发布前须提供 `LICENSES/LicenseRef-HL3-Commercial.txt`。若某 GUI 文件决定开源，必须逐文件另行明确为 `Apache-2.0` |

选择 Apache-2.0 作为内核唯一的对外许可证，因为其宽松再分发条件、明确专利许可与专利终止条款适合可商业采用的 open-core。不得把“参考 BSD/MIT 项目”写成内核的多重许可；除非文件自身另有明确且已审计的许可，HL3 原创代码均为 `Apache-2.0`。

执行规则：

1. 新增内核源文件应包含 `SPDX-License-Identifier: Apache-2.0`；规范文档应包含 `SPDX-License-Identifier: CC-BY-4.0`。
2. 包元数据必须声明 `Apache-2.0`。发行包须携带根 `LICENSE`，并保留所有适用的第三方版权、许可证、免责声明、修改说明及 `NOTICE`。
3. `LicenseRef-HL3-Commercial` 是合法的 SPDX 自定义许可证引用，不是 SPDX License List 中的标准许可证 ID；在商业条款文本落地前，不得对外分发 GUI 源码或二进制。
4. Apache-2.0 不自动授予第三方商标权，也不消除第三方专利、数据、模型权重或素材许可风险。

## 2. OpenCorr：只允许独立实现

OpenCorr 源码为 `MPL-2.0`，其文件级弱 copyleft 本可在满足条件时用于 Larger Work；HL3 采用更严格且更清晰的工程边界：

- **不得复制、改写、翻译、生成或 vendor 任何 OpenCorr 源文件、头文件、测试、示例、文档片段或资源文件。**
- 不建立 MPL 文件与 HL3 文件的派生关系，不把 OpenCorr 作为链接依赖或发布插件。不得仅通过改名、重排或机器翻译规避此规则。
- ICGN、ICLM、FFT 初值、立体匹配、标定、三角化、应变和 DVC/GPU 后端，必须依据已发表论文、公开标准和 HL3 自有规格独立实现；测试数据必须为自生成或具有明确许可的资产。
- 贡献记录必须列出所依据的论文/标准、作者和独立测试证据。代码评审发现与 OpenCorr 特有命名、文件结构或表达高度相似时，合并应被阻断并进行来源审计。
- 可以在研究文档中引用 OpenCorr 论文及公开、可复核的性能结果，但引用不产生复制代码或资产的权利。

这一决定避免内核混入 MPL 覆盖文件，同时保留对公开算法思想进行独立实现的空间。

## 3. OpenCorr GPU 二进制：禁止

`OpenCorrGPU.lib` 以及配套 `.dll`、头文件、GUI/shareware 组件和未提供可审计源码的 GPU 包均为禁用资产：

- 不下载、不提交、不缓存、不链接、不包装、不随安装包分发，也不在 CI、开发机或基准机上加载；
- 不进行反编译、符号提取、接口探测或行为逆向；
- 不用其输出生成 HL3 的 golden fixture；
- GPU 后端必须由 HL3 从公开论文独立实现，并以 Apache-2.0 的 CPU 参考实现和自有数值回归测试验证。

只有取得权利人明确书面授权且由新 ADR 批准后，才可改变此禁令。

## 4. 无许可证深度学习仓库：只引用论文

GitHub 可见不等于获得版权许可。对 U-DICNet、Stereo-DICNet2、无许可证 ICGN/CUDA 仓库以及其他未附明确许可证的深度学习项目，执行以下硬边界：

- 只引用已正式公开的论文及 DOI；仓库代码、提交历史、配置、权重、模型结构文件、数据、示例和测试输出均不得复制、修改、训练、转换、vendor 或分发。
- 若实现相关方法，只能从论文形成 HL3 自有规格，使用自生成或另有明确许可的数据独立训练，并保存来源、随机种子、数据许可和实现者记录。
- “在 README 中提供下载链接”“仅供研究”“作者公开权重”均不能替代可适用于 HL3 商业发行的明确授权。
- 作者后来补充许可证或提供书面授权时，仍须先完成代码、权重、数据和依赖的逐项审计，并通过新 ADR 才能复用。

## 5. 显微镜畸变 FTO 检索清单

显微镜/SEM 畸变校正保持 **零实现**：在法务给出书面 FTO 结论前，不编写实现、原型、伪代码、测试向量、插件或产品宣传，不根据任何专利权利要求设计、规避或验证功能。工程人员只可整理公开书目信息；权利要求解释、claim chart 和侵权比对应由专利律师在受控材料中完成。

### 5.1 种子、族谱与法律状态

1. 以 `US7133570B1` 为种子，核对优先权、INPADOC/简单族、申请历史、继续申请、部分继续申请、分案、再颁和复审记录。
2. 检索其前向/后向引证、发明人和历任/现任受让人的相关申请；按同族标题、摘要和分类号扩展检索，不仅按专利号检索。
3. 分别核对计划开发、制造、销售和使用地的有效权利，包括至少 US、EP、WO、CN、JP、KR；记录申请号、公开/授权号、最早优先权日、预期届满日、年费和诉讼/无效状态。
4. Round 1 记录的 `Expired - Fee Related` 只是一项数据库状态线索，不得据此推导“全球无风险”；必须检查恢复可能、仍在审查的继续申请及其他法域同族。

### 5.2 主题与检索式

数据库至少覆盖 USPTO Patent Center、Google Patents、Espacenet、WIPO PATENTSCOPE，并由当地法务补充 CNIPA、J-PlatPat、KIPRIS。查询日期、数据库、原始检索式和结果集必须留档。

建议组合检索：

- `("digital image correlation" OR DIC) AND (microscope OR microscopic OR microscopy) AND (distortion OR calibration OR correction)`
- `("stereo microscope" OR "stereoscopic microscope") AND ("distortion correction" OR calibration OR mapping)`
- `(telecentric OR non-telecentric OR "non-central camera") AND (stereo OR multi-camera) AND (correlation OR deformation OR strain)`
- `("depth-dependent" OR "field-dependent" OR "spatially varying") AND (magnification OR distortion) AND microscope`
- `(SEM OR "scanning electron microscope") AND ("scan distortion" OR drift OR raster) AND ("image correlation" OR displacement OR strain)`
- `数字图像相关 AND (显微 OR 显微镜 OR 电子显微) AND (畸变 OR 标定 OR 校正)`
- `(立体显微 OR 双目显微) AND (畸变校正 OR 标定 OR 映射)`；`扫描电镜 AND (扫描畸变 OR 漂移) AND 数字图像相关`

从种子专利和高相关结果提取 CPC/IPC 小类，再对同小类、相邻小类及引证网络反查。技术主题至少覆盖：

- 显微镜下空间变化或深度相关的放大率/畸变；
- 立体显微、多相机、远心/非远心成像的联合标定与坐标映射；
- 光路、折射介质、保护窗、倾斜成像造成的非中心投影校正；
- 标定靶、查找表、多项式/样条/分区模型及图像重映射；
- SEM 的扫描漂移、光栅非线性、充电/时变畸变与 DIC 的组合；
- 校正与相关、三角化、位移/应变计算或测量流程的组合。

### 5.3 FTO 出口条件

法务交付物必须包含逐法域的在审/有效权利清单、族谱、法律状态证据、律师完成的独立权利要求分析、建议的许可/无效/设计替代路线和书面放行范围。若结论只覆盖某一法域或某一实现范围，产品 Gate 必须保持同样限制。没有书面放行即继续冻结，不得用“专利已过期”“算法是常识”或“自行实现”替代 FTO。

## 6. 生产运行时依赖 allowlist

当前允许的生产运行时依赖仅限下表；版本仍须锁定，实际 wheel/conda 包、可选后端和传递依赖须进入 SBOM 并在每次发行前复核。

| 依赖 | 预期许可证 | 决定与条件 |
|---|---|---|
| NumPy | `BSD-3-Clause` | 允许。使用官方发行包；随包保留版权和许可文本，并审计所带 BLAS/LAPACK |
| SciPy | `BSD-3-Clause` | 允许。使用官方发行包；保留通知，并审计 OpenBLAS、LAPACK、Fortran runtime 等随包组件 |
| h5py | `BSD-3-Clause` | 允许。保留 h5py 通知；同时登记和履行 HDF5 库的 `HDF5` 许可证及压缩过滤器等可选组件的许可 |
| Qt 6 / PySide6（后续 GUI） | 商业 Qt 许可，或逐模块确认的 `LGPL-3.0-only` 路径 | **条件允许、当前不引入**。专有 GUI 优先取得 Qt 商业许可；若采用 LGPL 路径，必须只选 LGPL 可用模块、动态链接、允许用户替换库、提供相应源码/书面要约与通知，并由法务审核。GPL-only 模块不得进入专有发行包 |

控制要求：

1. 不 vendor 上述项目源码；通过锁定版本和哈希的包管理器安装。
2. 名称在 allowlist 中不代表其所有 extra、插件、加速库、数据包或传递依赖自动获准。新增生产依赖、替换 BLAS/HDF5/Qt 模块或静态链接前，必须更新 SBOM、许可证矩阵并取得审计批准。
3. 依赖许可只约束第三方组件，不改变 HL3 内核的 `Apache-2.0`、schema 文档的 `CC-BY-4.0` 或 GUI 的 `LicenseRef-HL3-Commercial`。

## 7. 禁止破解与来源审计

任何 HL3 工作均不得下载、安装、传播或使用破解版 VIC-2D、VIC-3D、VIC-EDU、VIC-Volume、MATLAB、Qt 或其他商业软件；不得使用密钥生成器、许可证绕过、伪造评估申请、反编译或逆向。只有合法取得且条款允许的评估/商业许可可以在隔离环境使用，且不得将专有二进制、手册文本、输出夹具或未公开行为带入 HL3。

每次发行必须通过以下 Gate：

- 根 `LICENSE` 与包元数据一致，schema 和商业 GUI 的例外边界清楚；
- SBOM 和第三方许可证/NOTICE 完整，无 MPL/GPL/无许可证/仅研究资产混入；
- 来源声明证明数值与 GPU 内核是独立实现；
- 扫描结果不含 OpenCorr 文件/GPU 二进制、VIC 或其他破解/逆向资产；
- 显微镜畸变模块仍被冻结，或已有与发行法域和功能范围完全匹配的书面 FTO 放行。

## 8. 最终裁决

HL3 采用 **Apache-2.0 开源内核 + CC-BY-4.0 开放 schema 文档 + 后续专有商业 GUI**。OpenCorr 只作论文级背景，不复制其 MPL 文件；OpenCorr GPU `.lib/.dll` 永久禁用，除非书面授权和新 ADR 明确推翻本决定。无许可证深度学习仓库只引用论文。显微镜畸变功能在完成律师主导的多法域 FTO 前保持零实现。生产运行时依赖暂限 NumPy、SciPy、h5py，Qt/PySide6 仅在完成商业或 LGPL 合规审查后引入。
