ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# HL3-2D / HL3-3D 基准协议（Round 1）

## 0. 目的、边界与判定原则

本协议把“算得准”“噪声低”“空间分辨率高”和“算得快”拆开测量，避免用单一示例或单一吞吐数字替代计量验证。所有结果必须保存原始配置、软件提交号、数据校验和、硬件、计时范围和失败点；改变精度、收敛阈值或过滤参数后，不能继续沿用旧基线。

边界：

- 只使用自生成数据、iDICs/SEM 公开 Challenge 数据和许可证允许的开源资料。
- 不下载、破解、逆向或传播 VIC 二进制和专有资料；合法持有的 VIC 许可若将来用于同机对测，应在独立工作站执行。
- VIC-3D 官方网页的“单颗 32 核 CPU、最高 1,000,000 点/秒”是缺少完整复现实验参数的公开营销上限，只能作为外部参考线，不能写成已经完成的同机对比。
- Challenge 数据不入 Git；本地/CI 缓存目录为 `data/challenges/`，记录来源 URL、下载日期和 SHA-256。

## 1. 基准阶段总览

| 阶段 | 数据 | 主要目的 | 频率 |
|---|---|---|---|
| B0 几何/数值单元测试 | 很小的解析场 | 坐标、warp、Jacobian、应变与三角化正确性 | 每次 PR |
| B1 合成刚体平移 | 高斯散斑 | 亚像素偏差、像素锁定、噪声传播 | 每次 PR 小样；nightly 全扫 |
| B2 合成旋转/单轴应变 | 高斯散斑 | 仿射 ICGN、客观刚体应变、应变准确度 | nightly |
| B3 iDICs 噪声底板/VSG | 静态、零载荷、高梯度帧 | 空间/时间噪声与平滑偏差折中 | nightly/实验验收 |
| B4 2D-DIC Challenge 1.0/2.0 | 官方公开集 | 与公开方法统一比较偏差、标准差、空间分辨率和 MEI | 每周/发布前 |
| B5 立体几何与已知平面 | 合成标定板、平面、刚体运动 | 重投影、极线、尺度和 3D 重建准确度 | PR 小样；nightly 全扫 |
| B6 Stereo-DIC Challenge | 官方公开集 | 真实镜头畸变、标定、复杂形状和大刚体运动 | 每周/发布前 |
| B7 CPU/GPU 性能与内存 | 固定合成矩阵 | 吞吐、延迟、内存和缩放 | nightly 固定机器；发布前 |

## 2. 统一坐标、数据与统计约定

### 2.1 坐标和真值

- 图像坐标：原点为左上像素中心，`x` 向右、`y` 向下，位移记为 `u, v`，单位为像素。
- 参考坐标为 `X=(x,y)`，变形坐标为 `x'=X+d(X)`；生成器必须在元数据中给出正向映射和逆采样映射。
- 2D 应变同时输出小应变、工程应变和 Green–Lagrange 应变，比较时必须明确种类。有限变形的主验收量为
  `E = 0.5 * (F^T F - I)`。
- 3D 使用右手坐标系，单位为 mm；保存相机内参、畸变参数、外参、世界坐标定义和单位。
- 排除边界的宽度至少为 `半个 subset + 最大位移 + 3×散斑 sigma`，且必须随结果报告，禁止事后挑选有利 ROI。

### 2.2 核心统计量

对有效点误差 `e_i = q_hat_i - q_true_i` 统一报告：

- 偏差 `bias = mean(e_i)`；
- 精密度/随机误差 `std = std(e_i, ddof=1)`；
- `RMSE = sqrt(mean(e_i^2))`；
- `median(|e|)`、`P95(|e|)`、最大绝对误差；
- 有效点率 `N_valid/N_requested`、不收敛率和误匹配率。

至少 30 个独立散斑/噪声种子时，另报告跨种子的均值和 95% bootstrap 置信区间。噪声底板同时给出空间标准差和时间标准差，不能把二者混为一个数。所有表格保留未四舍五入的机器可读 CSV/JSON。

### 2.3 初始工程门槛

这些是 HL3 的回归门槛，不是宣称适用于所有 DIC 实验的行业标准：

- 无噪声平移、内部 ROI：`|bias(u,v)| <= 0.01 px`、`std <= 0.01 px`、有效点率 `>= 99.9%`。
- 亚像素相位扫描：每个分量的周期性偏差峰峰值 `<= 0.02 px`。
- 刚体旋转的 Green–Lagrange 应变：内部 ROI 的 `P95(|E|) <= 100 µε`。
- 单轴小应变：平均轴向应变误差 `<= max(50 µε, 1%×|真值|)`；高应变另按 Green–Lagrange 真值判定。
- 已知平面的合成无噪声重建：平面正交距离 RMS `<= 0.01 mm`，尺度相对误差 `<= 0.05%`。

如果初版尚未达到门槛，应明确标成预期失败（`xfail`）并登记数值差距；不得放宽门槛来掩盖退化。Challenge 本身没有一个适用于所有参数的通用“及格线”，因此采用“固定配置不劣于已批准基线，并持续降低 MEI”的版本化门禁。

## 3. 合成高斯散斑与 ICGN 验证

### 3.1 生成原则

生产级生成器应在连续域定义随机高斯斑点，再对每个传感器像素面积积分。变形图像从连续纹理按真值反向采样，不能先生成低分辨率参考图再用与被测 ICGN 相同的插值器变形，否则会产生“逆犯罪”，低估插值偏差。

固定矩阵：

- 图像：`256²`（PR）、`512²` 和 `1024²`（nightly）；
- 高斯斑点标准差：`0.75, 1.25, 2.0, 3.0 px`；
- 中心密度：`0.02, 0.05, 0.08 /px²`，覆盖低、中、高三种纹理；
- 量化：浮点真值、8-bit、12-bit 和 16-bit；
- 对比度：满量程的 `20%, 50%, 80%`，另测线性增益/偏置；
- 生产数据至少 `8×` 过采样，并做 `8×` 对 `16×` 收敛检查：使用相同连续斑点中心和归一化尺度时，降采样后内部 ROI 的 RMS 差异应小于 `0.1` 个 8-bit gray count；未达标则继续提高过采样率。

本轮原型 `.agent_workspace/round1/scripts/synth_speckle.py` 仅覆盖高斯散斑和已知平移。它使用带边缘护栏的高分辨率随机脉冲、频域高斯卷积、傅里叶相移和像素块积分；因此平移不依赖被测 ICGN 的双线性/双三次插值。示例：

```bash
python3 .agent_workspace/round1/scripts/synth_speckle.py \
  --output /tmp/hl3-speckle --width 256 --height 256 \
  --tx 0.37 --ty -0.42 --noise-sigma 1.0 --seed 20260828
```

输出 `reference[_clean].npy`、`deformed[_clean].npy`、可直接查看的 8-bit PGM 和 `ground_truth.json`。后续 ICGN 测试读取 JSON 中的常量 `u,v`，按其中的 `valid_roi` 排除边界，比较每个 POI 的估计值和真值。原型不是 iDICs 官方 Boolean 模型的替代品。

### 3.2 亚像素插值偏差

1. 分数相位 `p=0.00,0.05,...,0.95 px`，分别生成 `(p,0)`、`(0,p)`、`(p,p)` 和 `(p,-p)`；再叠加整数平移 `0, ±5, ±20 px`。
2. 固定同一连续纹理，分别运行被测插值器：双线性、Keys 双三次、三次 B-spline、五次 B-spline（若实现）；记录边界模式和预滤波。
3. subset 取 `15,21,31,41,61 px`，step 取 `1,5, subset/2`；ICGN 使用相同初值、停止阈值、最大迭代数和浮点精度。
4. 对每个相位报告 bias/std/RMSE、迭代数和失败率；画 `bias(p)`，记录一像素周期偏差的峰峰值及一阶傅里叶幅值，识别 pixel locking。
5. 以独立种子重复；额外把散斑 sigma 与 Nyquist 邻近的 `0.75 px` 作为混叠压力项。

### 3.3 噪声 sigma 扫描

- 8-bit 等效独立高斯读出噪声：`sigma={0,0.25,0.5,1,2,4,8}` gray counts；参考帧和变形帧使用独立噪声。
- 每档至少 30 个纹理种子 × 5 个噪声种子；默认位移 `(0.37,-0.42) px`，另含零位移。
- 保存干净图，保证同一真值可复验；加噪后裁剪再量化，记录饱和像素比例。
- 主图为位移 bias/std 对输入 sigma；副图为收敛率、ZNSSD、迭代数和异常值率。可另设 Poisson 光子噪声与固定图样噪声扩展项，但不得和本 Gaussian sweep 合并统计。

## 4. 刚体平移、旋转和单轴应变真值

### 4.1 刚体平移

- 小位移：第 3.2 节完整相位扫描；
- 大位移：`±1, ±5, ±20, ±50 px`，检验金字塔/整数搜索，不把粗搜索时间排除在端到端性能之外；
- 时间序列：常速、三角波和含方向反转的轨迹，分别以首帧和增量帧为参考；
- 零位移对用于分离噪声底板；平移场的空间梯度和所有应变真值均为零。

### 4.2 刚体旋转

绕图像中心 `c=(cx,cy)` 生成 `θ={±0.1°,±1°,±5°,±10°}`：

```text
u = (cosθ-1)(x-cx) - sinθ(y-cy)
v =  sinθ(x-cx) + (cosθ-1)(y-cy)
```

小角用于亚像素仿射精度，大角用于金字塔和更新规则。报告位移误差随半径、旋转角误差，以及刚体运动下错误应变。Green–Lagrange 应变真值严格为零；仅用小应变张量会把有限旋转误报为应变，不能据此判算法失败。

### 4.3 单轴应变

采用明确的形变梯度 `F=diag(1+εx,1+εy)`。第一组令 `εy=0`，隔离轴向缩放；第二组令 `εy=-ν εx` 且 `ν=0.3`，模拟横向收缩。轴向工程应变取：

`εx={±50e-6,±100e-6,±500e-6,±1000e-6,±5000e-6,±10000e-6,±50000e-6,0.1,0.25,0.5}`。

其中最后三项为 10%、25%、50%。有限应变的真值为 `Exx=((1+εx)^2-1)/2`。大应变使用小增量序列并同时测试首帧参考，分别暴露增量漂移和大搜索范围问题。报告平均偏差、空间 std、VSG 后应变峰值衰减及边界损失。

## 5. 2D-DIC Challenge

### 5.1 官方来源与下载

官方索引（当前主入口）：

- iDICs DIC Challenge：<https://idics.org/challenge/>
- SEM 历史入口（当前可能重定向或失效，以 iDICs 为准）：<https://sem.org/dicchallenge>
- 2D Challenge 1.0 数据：<https://drive.google.com/drive/folders/1tNUKPJ7UJOm23JhERtkrIy5gSBiwV3Dj>
- 2D Challenge 2.0 数据：<https://drive.google.com/drive/folders/1ASWZZZjV1SPnjiFncb5ofOtfrrRfFhSw>
- 2.0 论文：<https://doi.org/10.1007/s11340-021-00806-6>
- 2.0 开放讨论文档：<https://doi.org/10.2172/1528822>

1.0 含 Sample1–17、描述表和 MATLAB 分析包；2.0 当前目录含 Star1–6 与公开 Results。它们总量相对可控，但仍应按需下载。可复现命令：

```bash
python3 -m pip install --user gdown
mkdir -p data/challenges/2d-1.0 data/challenges/2d-2.0
gdown --folder 'https://drive.google.com/drive/folders/1tNUKPJ7UJOm23JhERtkrIy5gSBiwV3Dj' \
  -O data/challenges/2d-1.0 --remaining-ok
gdown --folder 'https://drive.google.com/drive/folders/1ASWZZZjV1SPnjiFncb5ofOtfrrRfFhSw' \
  -O data/challenges/2d-2.0 --remaining-ok
```

下载不是本轮任务的一部分；正式缓存后生成本地 SHA-256 清单。Google Drive 文件 ID 或内容变化时，CI 必须拒绝静默替换并要求人工更新 manifest。

### 5.2 执行和指标

优先顺序：

1. Challenge 1.0 的刚体亚像素平移、旋转、噪声、对比度和实验含孔板，覆盖传统准确度与鲁棒性。
2. Challenge 2.0 的 Star1/2（恒定位移幅值）测位移，Star3/4（恒定应变幅值）测应变，Star5/6 用更长周期范围复核。
3. 严格使用官方中心行、真值和结果格式；例如 4000×500 Star 图的中心行为零基索引 `y=250`。噪声参考图不得平均成无噪声参考图。

统一报告：

- **bias**：中心行估计量相对官方真值的平均差；同时报告相位/周期区间内局部 bias。
- **std（measurement resolution）**：噪声“未变形”图中心行的 1σ；另保留全场空间 std。
- **空间分辨率**：随 Star 局部周期减小，用官方方法对中心行中点/峰值拟合；最终 Challenge 比较主报振幅相对真值损失 10% 处的周期 `L10%`，单位 px。2018 年讨论文档曾采用 20% 损失（幅值比 0.8）门槛，因此兼容输出另报 `L20%`，但不能把两者混报。
- **MEI**：位移 `MEI_u = sigma_u × L_u`；应变 `MEI_e = sigma_e × L_e²`。每种方法/参数按官方做法取三个最小 MEI 的平均值，越小越好。
- **完整性**：有效点率、边缘覆盖率和误匹配；不能通过丢弃困难点只改善误差。

除“完全遵照官方提交参数”的轨道外，另设 HL3 推荐参数轨道。两者分表，避免调参后的最好结果冒充盲测结果。

## 6. iDICs 噪声底板与 VSG 尺寸扫描

依据 iDICs Good Practices Guide：

- 第二版入口：<https://idics.org/guide/>
- 可公开访问的指南版本：<https://idics.org/guide/DICGoodPracticesGuide_PrintVersion-V5h-181024.pdf>

### 6.1 噪声底板

1. 同一固定试件采集/生成参考帧和至少 30 帧静态图；实际硬件测试须使用和正式试验相同的帧率、曝光、照明、相机温度、风扇及处理参数。
2. 再采集/生成覆盖正式实验运动范围的刚体运动序列。静态序列给出下限，刚体序列能暴露畸变、插值和标定误差。
3. 对每个 QOI（`u,v,w,E11,E22,E12`）计算：
   - 每帧 ROI 空间 std，再对时间平均；
   - 每个点跨帧时间 std，再对 ROI 平均；
   - 时间漂移斜率、均值偏差和最大空间结构残差。
4. 同时给 `1σ` 与保守 `3σ` noise floor；报告中明确后续信号低于哪一个门槛时视为不可分辨。

### 6.2 VSG 扫描

对参考帧、参考之后的零载荷帧、最大应变梯度帧执行：

- subset：`15,21,31,41,61 px`；
- step：`1,3,5,7, subset/2`；
- strain/filter window：奇数点 `3,5,7,9,11,15,21`；
- strain shape function：线性/二次（若支持），过滤核及边界规则必须记录。

局部多项式应变窗口的近似 VSG 为

`VSG_px = subset_px + (window_points - 1) × step_px`。

不同应变算法的真实支撑域可能不同，因此还应通过合成阶跃/正弦应变的 10%/20% 幅值损失测有效 VSG/空间分辨率。每组从最高梯度区域提取不跨裂纹的固定线：

- 零载荷帧给应变 bias/std/3σ；
- 最大载荷帧给峰值、相对真值的衰减和梯度位置偏差；
- 画“噪声—峰值衰减—VSG”Pareto 曲线。

选择规则：先找随 VSG 减小而峰值已收敛的平台，再在平台内选择满足噪声预算的最大 VSG；若最小 VSG 仍不收敛，只能把测得峰值报告为真峰值的下界，不能声称已捕获真实峰值。

## 7. 性能、内存和缩放

### 7.1 数据矩阵和计时边界

图像尺寸 `512²,1024²,2048²,4096²`；subset `21,31,41,61`；step 调整为约 `10k,100k,1M,4M` 个请求 POI。使用同一散斑、位移、初值和收敛门槛，准确度必须先通过第 2.3 节，否则速度结果无效。

每项分开计时：

1. **kernel-resident**：图像/系数已驻留 CPU 内存或 GPU 显存，仅相关和 ICGN；
2. **warm end-to-end**：灰度转换、金字塔/插值系数、粗搜索、ICGN、质量检查和应变，排除磁盘 I/O；
3. **cold end-to-end**：包含文件读取、分配和 CPU↔GPU 传输；
4. **sequence steady-state**：至少 100 帧，报告首帧延迟和后续吞吐。

`points/s = 成功完成且通过质量门槛的 POI数 / 墙钟秒`。失败点、被掩膜点和只做整数搜索的点不能进入分子。立体结果须明确一个“点”是否包含左时序相关、右立体匹配和三角化；2D 与 stereo 不共用一个无说明的 points/s 数字。

### 7.2 CPU/GPU、公平性与输出

- CPU：固定频率策略，记录型号、物理核/逻辑线程、RAM、NUMA、编译器和 flags；跑 `1,2,4,8,16,32` 线程并报告并行效率。
- GPU：记录型号、驱动、运行时、显存、精度；分报不含传输的 kernel-resident 与包含传输的端到端吞吐。
- 每项预热 5 次、正式至少 20 次；报告 median、P5/P95、每点迭代数。禁止只选最快一次。
- CPU 峰值内存用 peak RSS，GPU 用峰值已分配 VRAM；同时报告 bytes/POI。
- 缩放图：固定 POI 密度时随图像尺寸增长、固定图像时随 POI 数增长、固定问题时随线程/设备增长。另报告首帧初始化成本。
- nightly 只在带标签的固定裸机 runner 上设性能门禁：吞吐中位数不得比滚动 20 次绿色基线下降超过 10%，内存不得上升超过 10%；共享云机器结果只做观察。

### 7.3 与 VIC 公开数字的正确比较

VIC-3D 官方页：<https://www.correlatedsolutions.com/vic-3d>，原文宣称“up to 1,000,000 points per second using a single 32-core CPU”。网页未公开足以复现的图像尺寸、subset、搜索、精度、迭代、计时边界和硬件型号。

因此报告中只画一条标为“VIC 官方公开上限；非同机、非同配置、不可直接排序”的 1e6 pts/s 参考线。只有同时满足以下条件，才允许写“同机超过/未超过 VIC”：

- 在同一台 32 物理核机器上合法运行双方软件；
- 相同图像、ROI、POI、subset/step、形函数、收敛/失败判据、输出精度与计时边界；
- 双方达到相同准确度门槛；
- 发布完整配置、重复次数和置信区间。

在此之前，HL3 可陈述“在所列硬件和公开工作负载达到 X points/s”，不能陈述“比 VIC 快 Y 倍”。

## 8. 立体标定、极线与已知平面

### 8.1 标定重投影

用覆盖视场、深度和姿态范围的合成/实拍标定板，留出 20% 姿态作为测试集。每相机报告训练集和留出集的：

- 每角点重投影误差 RMS、median、P95、max（px）及二维矢量图；
- 误差随半径、板姿态和深度的分布；
- 内外参相对真值误差（合成集）及重复标定方差。

低训练重投影误差不保证 3D 准确，禁止只报优化器返回的单一 RMS。

### 8.2 极线误差

对留出的标定角点和独立散斑立体匹配点，以基础矩阵 `F` 计算对称点到极线距离：

```text
r = x2^T F x1
d_sym = sqrt(0.5 * r² * (1/(l2x²+l2y²) + 1/(l1x²+l1y²)))
```

其中 `l2=F x1`、`l1=F^T x2`。报告 RMS/median/P95/max（px）和随视场位置的热图；同时保留有符号残差以发现系统弯曲。校正图另报告垂直视差 `|yL-yR|`。

### 8.3 已知平面重建

合成一块有绝对尺寸的平面并设置不同深度、倾角和 stereo angle；实拍则使用经溯源的平面靶。三角化后：

1. 用 TLS 拟合平面，报告点到平面的正交距离 RMS/P95/peak-to-valley（平面度/随机误差）；
2. 与真值平面比较法向夹角、平面偏置和深度 bias（绝对准确度）；
3. 比较两组已知标记距离，给尺度 bias；
4. 以固定平面做 `±20 mm` 三轴刚体运动，报告每轴位移 bias/std、3D 向量模长误差和虚假应变；
5. 扫描基线、焦距、噪声和标定姿态数量，验证深度误差的几何缩放趋势。

平面拟合前不得逐帧自由刚体配准来消除本应被测的尺度、姿态或偏置；若为了单独评价形状做了配准，必须同时保留未配准绝对误差。

## 9. Stereo-DIC Challenge

官方来源：

- Stereo Challenge 1.0：<https://drive.google.com/drive/folders/1q0GnsopWaOlD6IuVOS-ZxeBIZwUFuQ-w>
- 1.0 论文（开放元数据/可获取全文）：<https://doi.org/10.1007/s11340-024-01077-7>
- Stereo Challenge 2.0 当前目录：<https://drive.google.com/drive/folders/1ONaGOqVXicS42vFbLh6UEFbnX488EhwV>

1.0 含实验/模拟 Sample1–6、不同镜头标定和 translation 数据；其中 Sample5 压缩包约 683 MB。2.0 目录含约 67 MB 的刚体平移、约 190 MB 预备拉伸集以及 **16.3 GB** 的 `Tensile-S6.zip`。不要在普通 CI 中整目录下载。建议先在浏览器查看目录，只选择 Sample1 的 35 mm 标定+Translate 和 2.0 的 67 MB 刚体集；若确有本地存储预算，再显式执行：

```bash
# 警告：以下 --folder 会递归拉取目录，先在网页核对体积；禁止放入普通 CI。
mkdir -p data/challenges/stereo-1.0 data/challenges/stereo-2.0
gdown --folder 'https://drive.google.com/drive/folders/1q0GnsopWaOlD6IuVOS-ZxeBIZwUFuQ-w' \
  -O data/challenges/stereo-1.0 --remaining-ok
gdown --folder 'https://drive.google.com/drive/folders/1ONaGOqVXicS42vFbLh6UEFbnX488EhwV' \
  -O data/challenges/stereo-2.0 --remaining-ok
```

正式跑 1.0 时优先复现论文的已知 `±20 mm` 面内/离面刚体运动，使用随数据提供的校正后 stage 真值和分析脚本。报告 `U,V,W` 的 bias/std/RMSE、绝对位移模长误差、残差场、覆盖率、边缘距离和形貌相对参考扫描的正交误差。论文给出的“全范围 3D 误差小于约 80 µm”是已发表结果背景，不是自动赋给 HL3 的成绩。

Stereo 2.0 拉伸集用于 VSG、噪声和高梯度/失效前应变；超大 S6 仅在 challenge runner 或人工发布验收运行。

## 10. CI 分层计划

### 10.1 PR 单元/小集成（CPU，目标数分钟）

- warp 正反向、坐标中心、边界、刚体旋转公式；
- ICGN 梯度/Jacobian/Hessian 与有限差分对照；
- 无噪声整数平移和 4 个分数平移（`64²/128²`，固定种子）；
- affine 旋转和 `±1000 µε` 单轴应变；
- 小型相机投影/畸变/反畸变、基础矩阵、三角化和已知平面；
- 统计量、有效点过滤、VSG 尺寸公式和 JSON/CSV schema。

PR 测试只依赖仓库自生成数据，不联网、不依赖 Challenge 缓存。随机测试必须打印失败 seed。

### 10.2 Nightly（固定 CPU；有标签时加 GPU）

- 第 3 节完整 speckle sigma、分数相位、插值器、subset 和噪声 sigma sweep；
- 30+ 种子的刚体平移/旋转/单轴应变；
- iDICs 风格静态/刚体 noise-floor 和 VSG Pareto 扫描；
- 合成立体标定留出集、极线误差、平面与 3D 刚体运动；
- CPU/GPU 准确度等价检查、性能/内存/尺寸缩放。

共享 runner 的性能只上传趋势，不阻断合并；固定 runner 才执行第 7.2 节 10% 门禁。

### 10.3 Challenge/发布验收

- 每周：缓存有校验和的 2D Challenge 1.0 精选集、2.0 Star1–6、Stereo 1.0 Sample1；
- 发布候选：2D 1.0 全集、Stereo 1.0 选定实验/模拟集；
- 人工或专用大盘 runner：Stereo 2.0 拉伸集和 16.3 GB S6；
- 结果产物：配置、数据 manifest、逐点结果、汇总 CSV、图、日志、硬件清单和软件 commit；
- 数据缺失时标为 `skipped: challenge-data-unavailable`，不得假装通过；校验和不符直接失败。

## 11. 每次发布必须返回的结果包

`benchmark-manifest.json` 至少包含：HL3 commit、dirty 状态、生成器/Challenge 数据版本与 SHA-256、OS、CPU/GPU/RAM、编译器和 flags、线程/精度、图像与 DIC 参数、计时边界、随机 seed、门槛版本。汇总按 B0–B7 列出 pass/fail/xfail/skip，随后给 bias、std、空间分辨率、MEI、有效点率、points/s 和峰值内存。任何最快结果都必须能由 manifest 中的一条命令重跑。

## 12. 主要公开依据

1. iDICs, *A Good Practices Guide for Digital Image Correlation*, Guide/Edition 2 入口：<https://idics.org/guide/>。
2. Reu et al., *DIC Challenge: Developing Images and Guidelines for Evaluating Accuracy and Resolution of 2D Analyses*, <https://doi.org/10.1007/s11340-017-0349-0>。
3. Reu et al., *DIC Challenge 2.0: Developing Images and Guidelines for Evaluating Accuracy and Resolution of 2D Analyses*, <https://doi.org/10.1007/s11340-021-00806-6>。
4. Ahmad et al., *Stereo-DIC Challenge 1.0 – Rigid Body Motion of a Complex Shape*, <https://doi.org/10.1007/s11340-024-01077-7>。
5. Correlated Solutions, VIC-3D 官方公开性能页：<https://www.correlatedsolutions.com/vic-3d>（仅公开声明对照，不代表已做同机实测）。

链接与目录内容核验日期：2026-08-28。
