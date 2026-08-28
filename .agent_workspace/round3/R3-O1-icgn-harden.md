ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R3-O1：CPU IC-GN 内核加固与边界用例扩充

> 子代理：R3-O1（opus-fast）｜轮次：Round 3 / 3
> 独占路径（与 `round3/DISPATCH.md` 一致）：`src/hl3/correlate/**`、`tests/test_icgn_*.py`、`round3/R3-O1-icgn-harden.md`
> **未触碰**：`src/hl3/stereo/**`、`src/hl3/io/**`、`src/hl3/capture/**`、`benchmarks/**`、`docs/**`、`README.md`、`.github/**`、`pyproject.toml`
> 环境：CPU-only（4 vCPU，无 GPU、无 CUDA），Python 3.12.3 + NumPy，纯 NumPy，未引入任何新依赖
> 法律边界：仅修改 R2-O1 的独立实现，未引入任何外部 DIC 代码

---

## 0. TL;DR — 实测数字

| 项 | 数值 |
|---|---|
| **测试数** | **21 → 127**（新增 **106**），`tests/test_icgn_synth.py` |
| **pytest 结果** | **`127 passed in 8.83s`**，**0 failed / 0 error / 0 skipped** |
| 全仓测试（CI 口径 `pytest -q tests src/tests`） | `193 passed in 10.93s` |
| **新用例中在 R2 内核上失败的** | **51 / 106**（其余 55 条锁定既有正确行为，防漂移） |
| **精度变化** | **无**。基线工况平均 \|误差\| `8.077597688e-04 px`，改前改后**逐位相同**，平均迭代数同为 4.18 |
| 吞吐代价 | 无初值路径 814 → **771 POI/s（−5.3%）**；FFT-CC 初值路径 666 → **620 POI/s（−7.0%）** |
| 代码量 | `icgn.py` 662 → 945 行；`test_icgn_synth.py` 380 → 1013 行 |

一句话：**这一轮没有动任何"算得对的路径"的数学，只处理"算不出来时说什么"**。基线数字逐位不变是刻意的验收条件——加固如果改动了正常路径的输出，R2-O1 的全部实测表就要作废重跑。

---

## 1. 交付物

| 文件 | 改动 |
|---|---|
| `src/hl3/correlate/icgn.py` | 加固，+283 行（校验、平坦判据、条件数门、空 AOI、初值失败上报、闭式仿射求逆） |
| `tests/test_icgn_synth.py` | 21 → 127 个用例 |
| `.agent_workspace/round3/R3-O1-icgn-harden.md` | 本报告 |

`src/hl3/correlate/__init__.py` **未改**（导出符号未增减，`Status` 的新成员随枚举一起导出）。

提交（分支 `cursor/r3-o1-icgn-harden-086f`，基线 `cursor/dic-sota-plan-259d`）：

1. `29361d6 harden(correlate): scale-aware contrast gate, conditioning gate, empty AOI`
2. `01ebcdc harden(correlate): judge subset flatness against image contrast, not level`
3. `eef94da test(correlate): 106 edge cases for zero contrast, empty AOI, integer shifts`

---

## 2. 修了什么

每一条都按同一个格式给：**症状 → 证据 → 处置 → 代价**。凡是「旧内核其实已经挡住了」的，明说，不冒领。

### 2.1 平坦判据：从绝对阈值改成相对图像对比度

**症状**。旧判据是 `f_norm < 1e-9`（子区零均值范数的绝对阈值）。这个量随灰度标度线性变化，所以它同时是"太松"和"太紧"的：重采样残差随灰阶抬升，暗弱但真实的纹理随灰阶下沉。

**证据**。21×21 子区、常数图像的 B 样条重采样残差实测：

| 常数灰阶 | `f_norm` |
|---:|---:|
| 1 | 4.66e−15 |
| 128 | 5.97e−13 |
| 12 800 | 3.82e−11 |
| 1e6 | **7.33e−09**（已越过旧阈值 1e−9） |

另一端，把同一对散斑图整体乘以增益 `a` 后单点求解：

| 增益 `a` | 旧内核 | 新内核 |
|---:|---|---|
| 1e−6 | CONVERGED `u=+0.37072064` | CONVERGED `u=+0.37072064` |
| 1e−12 | CONVERGED `u=+0.37072064` | CONVERGED `u=+0.37072064` |
| **1e−15** | **SINGULAR_HESSIAN `u=0`** | CONVERGED `u=+0.37072064` |
| **1e−30** | **SINGULAR_HESSIAN `u=0`** | CONVERGED `u=+0.37072064` |

**诚实的一半**：在**物理可能的灰阶范围内**（8/12/16 bit，含平场 + 远处亮点的构造），旧内核并没有真的放行平坦子区——它被 Cholesky 分解失败**顺手挡住了**。也就是说 2.1 修掉的是"判据写错了但被别的机制救了"，以及**真实存在的误拒**（表中 1e−15 以下）。我构造出旧内核真的 CONVERGED 的平坦用例，需要灰阶 1e6 且远处有 1.5e6 的亮点，超出任何真实传感器量程，因此**没有**把它写成测试，也不在报告里当作已发生的事故来讲。

**处置**。判据改为：子区 RMS 对比度 ≤ `max(min_contrast, 1e-9 × 图像对比度尺度)`，其中图像对比度尺度 = 整幅图的标准差，每幅图算一次。

- 为什么用**整幅图**的对比度而不是子区自己的灰度：欠曝死黑 / 过曝死白的斑块**自身几乎没有灰度**，拿它自己当尺子，B 样条预滤波（IIR 递归）从周围纹理漏进来的衰减尾巴就会被当成满量程纹理。实测：把 40×40 的斑块涂成 0 时，若用子区自身尺度，该点被判为可解并跑到 NOT_CONVERGED；改用整图尺度后正确判为 SINGULAR_HESSIAN。
- 为什么这个比值仍然是**增益/偏置不变**的：`g = a f + b` 下，子区对比度与整图标准差都乘 `a`、都不随 `b` 动，比值不变。这正是 ZNSSD 的设计不变量，判据不能比它更弱。
- 整幅图对比度为 0（真·常数图）时直接短路判 flat，不让比值退化。
- 新参数 `ICGNParams.min_contrast`（灰阶，默认 **0**）是绝对下限旋钮：默认 0 = 纯相对，保持完全的增益不变；使用者要拒绝"技术上有纹理但太弱不值得算"的子区时把它调上去（实测 `min_contrast=100` 会把基线散斑判为 SINGULAR_HESSIAN）。

**代价**。每幅图一次 `np.std`，可忽略；`integer_search_fftcc` 因此多了一个 `contrast_scale` 形参（求解器逐点循环时把算好的值传下去，避免每点重算全图标准差）。

### 2.2 条件数门：秩亏子区不再被对角加载"救活"

**症状**。只在一个方向有纹理的子区（条纹、斜坡、试件边缘的一维织构）对 `v` 是无解的——经典的孔径问题。旧代码只有 `hessian_reg = 1e-9` 的对角加载，它让 Cholesky 成功，于是求解器**给出一个由正则化项而非数据决定的 `v`，并且报 ZNCC = 1.0**。

**证据**。周期 7 px 的纯竖条纹，真值 `u = 0.4`、`v` 不可定：

| | 状态 | `u` | `v` | ZNCC |
|---|---|---:|---:|---:|
| 旧内核 | **CONVERGED** | +0.40033 | +2.03e−10 | **1.000000** |
| 新内核 | SINGULAR_HESSIAN | — | — | −1 |

该子区尺度化 Hessian 的 6 个特征值实测为 `[−1.00e−6, 2.44e−23, 5.30e−7, 1.69e+03, 6.24e+09, 6.26e+09]`——三个数值零（其中一个因舍入为负），是严格秩亏，不是"病态"。

**处置**。按 R1-O1 §2.6 的失败表落实 `cond(H) > 1e10 → SINGULAR_HESSIAN`。条件数在**尺度化** Hessian `S H Sᵀ`（`S = diag(1, r, r, 1, r, r)`）上判：原始 `H_raw` 的位移列与位移梯度列相差 `r` 倍，`cond(H_raw)` 量的是参数单位而不是子区本身；`S` 与收敛判据用的是同一个尺度化，物理含义是"子区边缘处的位移像素"。

**门限安全裕度**（实测，192×192 合成散斑）：

| subset 半径 | 尺度化 cond 中位数 | 最大 |
|---:|---:|---:|
| 3 | 1.63e+02 | 1.11e+04 |
| 5 | 7.05e+02 | 2.91e+03 |
| 10 | 6.77e+03 | 1.37e+04 |
| 20 | 7.90e+04 | 1.05e+05 |

真实散斑最坏 1.05e5，门限 1e10 还有 **5 个数量级**裕度，因此不会误杀。测试里另配了一个"同幅值二维正弦"的对照组（`u=0.4, v=0.25` 全部恢复，误差 < 2e−3 px），专门盯防这个门限反过来杀好点。

**代价**：每 POI 一次 6×6 `eigvalsh`，计入 §5 的 5.3%。新参数 `ICGNParams.max_hessian_cond`（默认 `1e10`）。

### 2.3 初值求不出来 ≠ 初值是零

**症状**。`search_radius > 0` 时若某点的 FFT-CC 搜索窗越出图像（或图块平坦），旧代码静默退化为零初值继续算。位移小的时候它"碰巧对"，位移大的时候它会**落到错误的散斑上并自信地收敛**——而位移大正是当初要开搜索半径的原因。

**证据**。128×128、真值 `(0.4, 0.3)`、`subset_radius=10, search_radius=12`、点 `(13, 64)`（搜索窗越界，子区本身没越界）：旧内核 CONVERGED `u=+0.4009`；新内核 `NO_INITIAL_GUESS`，`iterations=0`，`zncc=−1`。

**处置**。`integer_search_fftcc` 的返回值 `zncc = −1` 现在**唯一地**表示"没有初值"（此前"全图无效候选"时它会对一张全 −1 的相关图取 argmax，返回位于角上的伪峰）；求解器据此把该点标记为 `Status.NO_INITIAL_GUESS` 并跳过。

**这条是有代价的行为变更**，要说清楚：以前能出结果的边界点现在不出结果。代价边界已被测试钉住——`make_grid` 的默认 margin 本就包含 `search_radius`，所以**默认网格永远不会触发**它（`test_the_default_grid_margin_never_triggers_a_failed_search`）；只有使用者自己把点放得比自己要的搜索半径还靠边时才会遇到。我认为"少一圈点"优于"多一圈可能指向错误散斑的自信答案"，这与 R2-O1 写 `test_large_displacement_needs_fftcc_seed` 时的取向一致。

### 2.4 空 AOI

**症状**。`points=[]`（整帧被掩膜掉、或点集被过滤空）旧代码抛 `ValueError`；`np.empty((0,2))` 侥幸能过，但会白建四个 B 样条插值器。

**处置**。四种写法（`np.empty((0,2))`、`np.zeros((0,2))`、`[]`、`np.array([])`）统一返回**形状与 dtype 正确的空结果**：`p (0,6)`、`iterations` 为 `int32`、`covariance` 在开启时为 `(0,6,6)`、`status_counts() == {}`、`masked("u")` 为空数组。零点时提前返回，不构建插值器。

### 2.5 非有限像素在边界一次性拒绝

**症状**。一个 NaN 像素旧代码不报错：`np.floor(nan).astype(int64)` 是未定义行为（附带一条 `RuntimeWarning: invalid value encountered in cast`），折叠出某个合法索引，最终该点报 `DIVERGED`——一个与真实原因无关的状态码。

**为什么必须在边界拒绝而不是逐点降级**：B 样条预滤波是**两个轴上的 IIR 递归**，一个 NaN 会沿整行再沿整列扩散到**每一个系数**。它不是局部污染，没有"只让那个点失败"的选项。

**处置**。`BSplineInterpolator` / `reference_gradients` / `integer_search_fftcc` / `icgn_first_order` 四个公开入口统一走 `_as_image()`：必须二维、非空、全有限，错误信息里带上出错的形状。采样坐标也校验有限（`sample()`）。

**留给后续**：规格 §5.8（T8）要求的"NaN 裂纹带 + 掩膜"是**功能**不是加固——需要显式的 mask 参数与 `Status.MASKED` 路径，本轮只把枚举位留好（§2.7），没有实现。**当前实现不支持用 NaN 表示掩膜区**，这一点已写进模块 docstring，避免下游误用。

### 2.6 参数与输入校验

`ICGNParams` 现在拒绝：`conv_tol ≤ 0` 或非有限、`zncc_min ∉ [−1,1]`、`max_disp ≤ 0` 或非有限、`hessian_reg < 0`、`image_noise_sigma < 0`、`min_contrast < 0`、`max_hessian_cond ≤ 1`（原有的 `subset_radius/step/max_iter/search_radius` 校验保留）。此外：点集必须是 `(n,2)` 且有限；`initial_guess` 必须有限且形状匹配（错误信息里写出期望的 `(n,2)/(n,6)`）；`warp_matrix` 要求 6 元有限向量、`warp_params` 要求 3×3；`make_grid` 拒绝负 margin 并在图像太小时给出带尺寸的消息；`integer_search_fftcc` 拒绝 `radius < 1`、`search_radius < 0`、非有限点。

`ICGNResult.masked()` 现在拒绝它无法置 NaN 的字段（旧代码 `masked("covariance")` 抛 `IndexError`）；新增 `status_counts()`（规格 §1.5 要求的失败原因分布）与 `n_points`。

### 2.7 `Status` 补全，以及一个需要裁决的编号冲突

补上规格 §4.3 列出但 Python 侧缺失的两个成员：`NO_INITIAL_GUESS = 7`（本轮已启用，见 §2.3）、`MASKED = 8`（占位，等 mask 功能）。

⚠️ **需要 R3-F3 / R3-O3 裁决**：规格 §4.3 的 C++ 声明顺序是 `… SINGULAR_HESSIAN, NO_INITIAL_GUESS, DIVERGED, MASKED`，隐含 `DIVERGED = 7`；而 R2-O1 已经发布并落地的 Python 编号是 `DIVERGED = 6`。两者不可能同时成立。我**保持 Python 现有编号不变**（不破坏已发布的数值），把冲突写在 `Status` 的 docstring 里，建议 C++ 侧用显式初始化对齐。这个编号一旦进 HDF5 就冻结了，属于 schema 相关决定，不该由我单方面改。目前 `docs/schema-hdf5.md` 未记录 status 数值映射——**建议 R3-O3 补上**。

### 2.8 `compose_inverse` 用闭式仿射求逆

2×2 仿射块闭式求逆 + 平移，替代 `np.linalg.inv` 的 3×3 求逆；奇异判据从绝对的 `|det| < 1e-12` 改为相对于块幅值的 `|det| ≤ 1e-12 · ‖A‖²`，于是"大但可逆"的增量不再被误拒（测试：`dp = (50, 0.4, −0.3, −70, 0.2, 0.5)` 正常通过）。与 3×3 矩阵路线的一致性用 20 组随机 `(p, dp)` 对拍，实测最大差 `0.0`。

---

## 3. 测试：21 → 127

### 3.1 分组计数

| 组 | 用例数 | 其中在 R2 内核上失败 |
|---|---:|---:|
| 既有（R2-O1） | 21 | — |
| **零对比度 / 退化纹理** | 23 | 7 |
| **空 AOI** | 9 | 7 |
| **整数 / 整数+亚像素平移** | 13 | 0 |
| 其余状态码（LOW_ZNCC / NOT_CONVERGED / DIVERGED / masked） | 9 | 5 |
| 输入校验 | 40 | 27 |
| 插值器与形函数代数 | 12 | 5 |
| **合计** | **127**（新增 106） | **51** |

「在 R2 内核上失败」= 把 `icgn.py` 换回基线提交 `7e347c9` 的版本后重跑（脚本见 §9），实测 `51 failed, 76 passed`。（提交 `eef94da` 的说明里写的是 50，那是补最后一条用例之前的测量；以本表的 51 为准。）其中约一半是真行为差异（平坦/秩亏/初值/空 AOI），另一半是本轮新增的校验与 API（`status_counts`、`masked` 字段校验、`Status` 补全）——两类都算真守卫，但性质不同，不混为一谈。

### 3.2 零对比度（23 条）

判据可能错在**两个相反方向**，所以两头都要打：

- 常数图对，灰阶 `0 / 1 / 128 / 255 / 1e6` 各一条：状态必须是 `SINGULAR_HESSIAN`、`zncc == −1`、`iterations == 0`、`p` 全零。
- 死黑（0）与过曝（255）斑块涂进真实散斑：斑块中心 `SINGULAR_HESSIAN` 且 `masked("u")` 为 NaN，**同一次调用里**斑块外两点照常收敛到 0.37 ± 5e−3。
- 有纹理的参考图 + 常数目标图。
- 反方向：整体增益 `1e−30 / 1e−15 / 1e−6 / 1e6`，要求状态数组**完全相等**且位移差 `< 1e−12 px`（实测 ≤ 4.33e−15 px）。
- `min_contrast` 旋钮：调到 100 灰阶时基线散斑被判 flat。
- 一维织构（条纹周期 7 与 13）判 `SINGULAR_HESSIAN`；同幅值二维正弦作为对照必须照常求解。
- FFT-CC：平坦图对（3 个灰阶）与搜索窗越界各自返回 `(0, 0, −1)`；搜索失败上报 `NO_INITIAL_GUESS`；默认 margin 不触发该状态；失败点的协方差保持 NaN 而邻点有限。

### 3.3 空 AOI（9 条）

四种空点集写法 × 全套形状/dtype 契约；开启协方差时的 `(0,6,6)`；**非空但全部越界**的 AOI（`status_counts() == {OUT_OF_BOUNDS: 3}`，`masked("u")` 全 NaN，`iterations` 全 0）；`make_grid` 拒绝过大 margin 与负 margin；混合 AOI 的 `status_counts()` 精确等于 `{CONVERGED: 2, OUT_OF_BOUNDS: 1, SINGULAR_HESSIAN: 1}`。

### 3.4 整数与整数+亚像素（13 条）

整像素平移是**唯一完全没有插值误差**的工况，求解器无处可藏，所以断言收得很紧：

| 工况 | 断言 | 实测 |
|---|---|---|
| 无初值，`(1,0) (0,−1) (2,3) (3,−2)` | 全收敛，`max\|误差\| < 1e−4 px`，梯度项 `< 1e−5` | ≤ 1.78e−6 px |
| 带 FFT-CC 初值，`(3.25,−2.4) (4.5,3.75) (−5.1,2.6)` | 全收敛，`max\|误差\| < 5e−3 px`；整数峰落在真值 ±0.5 内且 ZNCC > 0.9 | ≤ 2.79e−3 px；峰 ZNCC 0.958–0.974 |
| 4 px 整数偏移 + 相位 `0 / .25 / .5 / .75` | `\|bias\| < 3e−3 px` | ≤ 7.91e−4 px |
| 无初值收敛半径 | 3 px 命中率 = 100%，5 px < 50% | 3 px 100%、4 px 88%、5 px 32% |
| 单行 `initial_guess` 广播到整网格（7.35/−5.6 px） | 全收敛，`max\|误差\| < 0.01 px` | 5.26e−3 px |

第三行是这组的重点：**S 曲线属于相位，不属于整数部分**——4 px 偏移上的相位扫描偏差量级（≤ 7.9e−4 px）与 R2-O1 §4.1 纯亚像素扫描（平均 5.56e−4 px）一致，说明整数初值链没有往亚像素解里注入额外偏差。第四行把收敛半径**当事实记录**，这样初值链退化时表现为覆盖率下降而不是静默的精度损失。

### 3.5 其余（61 条）

此前**完全没有测试**的状态码：`LOW_ZNCC`（阈值设 1.0，验证规格 §2.6 要求的"标记但保留解"——解仍为 0.37 ± 5e−3、协方差仍填充、`masked` 仍置 NaN）、`NOT_CONVERGED`（`max_iter=1`）、`DIVERGED`（`max_disp=0.05`）、`masked("p")` 整行置 NaN。校验面 40 条，其中 `test_public_entry_points_validate_their_images` 是 4 入口 × 4 种坏图（nan / inf / 一维 / 空）的 16 条矩阵。插值器补了标量采样与 `x/y` 形状广播、非有限坐标拒绝、单行图像的梯度（缺失轴恒为 0）。

### 3.6 测试运行时间

生成散斑（8× 过采样傅里叶合成）是测试的主要开销，所以新增了 `shared_pair()`——`lru_cache` + **只读**数组（`setflags(write=False)`），要涂改的用例必须显式 `.copy()`，避免共享数组被就地污染。结果：**127 个用例 8.83 s**（R2 时 21 个用例 4.73 s），单次提交都跑得起。最慢的 5 个：0.66 / 0.54 / 0.50 / 0.48 / 0.47 s。

---

## 4. 精度回归核对（必须为零变化）

同一基线工况（192×192，真值 `u=+0.37 / v=−0.42`，subset 21×21，step 8，margin 40，196 POI）：

| 指标 | R2-O1 报告值 | 本轮改前实测 | 本轮改后实测 |
|---|---|---|---|
| 平均 \|误差\| | 8.078e−04 px | **8.077597688e−04 px** | **8.077597688e−04 px** |
| 平均迭代数 | 4.18 | 4.18 | 4.18 |
| 收敛点数 | 196/196 | 196/196 | 196/196 |

**逐位相同**。这不是巧合而是验收条件：新增的都是**门**（不改变通过者的算术），闭式仿射求逆虽然改了运算次序，但与 `np.linalg.inv` 路线在 20 组随机对拍中差为 0。因此 R2-O1 §4.1–§4.4 的全部实测表在本轮之后**继续有效，无需重跑**。

---

## 5. 性能代价（诚实版）

同一进程内新旧内核交替、各取 7 次最好成绩：

| 路径 | 旧 | 新 | 变化 |
|---|---:|---:|---|
| 无初值（196 POI，step 8） | 814 POI/s | **771 POI/s** | **−5.3%** |
| FFT-CC 初值（25 POI，step 16，`search_radius=12`） | 666 POI/s | **620 POI/s** | −7.0% |

代价来自三处：每 POI 一次 6×6 `eigvalsh`（条件数门）、每次采样一次 `isfinite`（坐标校验）、每幅图一次 `np.std`。我选择不为这 5% 做特例开关：**参考实现的第一属性是可审计**，而这三项恰恰是"算不出来时说真话"的成本。真正的性能路线仍是 R2-O1 §6.4 说的 POI 维度批量向量化，与本轮正交。

---

## 6. 已知缺口（交给后续轮次）

1. **mask / NaN 裂纹带未实现**：`Status.MASKED` 只占位。规格 §5.8（T8）的不连续场与遮挡测试做不了。需要显式 mask 参数（不能用 NaN 像素表达，理由见 §2.5）。
2. **T6 蒙特卡洛仍未做**：R2-O1 §6.1 留的坑本轮没有动。协方差目前仍只验证"有限、量级合理、失败点为 NaN"，**不能宣称 UQ 已被校核**。这是派工单范围外，但它是 R1-O1 §6.2 认定的核心差异化，Round 3 结束时它仍然是空的，评审时不应按"已完成"计分。
3. **只测了平移**：旋转（T3）、均匀应变（T4）、应变梯度（T5）仍未测。本轮新增的 13 条整数/亚像素用例也全是平移。
4. **`Status` 编号与规格 §4.3 冲突**待裁决（§2.7），且 `docs/schema-hdf5.md` 未记录 status 数值映射。
5. **条件数门限 1e10 是规格给的，不是本环境标定的**。实测裕度 5 个数量级（§2.2），但那是在合成散斑上；真实试件的边缘、低纹理区会更接近门限，需要真实数据复核。
6. **插值对照列仍缺**：`KEYS_BICUBIC` / `QUINTIC_BSPLINE` / `BILINEAR` 未实现，规格 §5.1 的对照表依旧只有一行。

---

## 7. 协作记录：工作树在运行中途被切走

R2-O1 §1 预言的事故本轮**如期发生**：我在 `/workspace` 做完内核改动、正在跑基准时，另一个子代理把共享工作树从 `cursor/dic-sota-plan-259d` 切到了 `cursor/r3-o2-stereo-harden-1747`，并在其中暂存了 stereo、`benchmarks/metrology/metrics.json`、`round3/R3-G2-metrics-run.md` 等他人文件。

处置（全程未 rebase、未 force-push、未改写他人提交、未提交任何他人文件）：

1. 把我的改动复制出来，`git checkout -- src/hl3/correlate/icgn.py` 把共享工作树恢复到它当时的 HEAD 状态，只留下别人自己的改动；
2. `git worktree add /tmp/r3o1 -b cursor/r3-o1-icgn-harden-086f cursor/dic-sota-plan-259d`，本轮**全部工作在独立工作树内完成**；
3. 三次提交都用显式路径 `git add`，从未用过 `git add .` 或 `git add <dir>`。

**给 Round 4（若有）的建议照抄 R2-O1 并加强**：并行子代理必须各自 `git worktree`。共享 checkout 下 `git add <目录>` 会捕获别人未提交的工作，这是结构性缺陷；而且如本轮所示，**连"不 git add"都不够安全**——工作树可能在你写文件的过程中被切到别人的分支上。

---

## 8. 与 R1-O1 规格的一致性变化

| 规格条目 | R2 状态 | 本轮 |
|---|---|---|
| §2.6 `Δf < eps` / `Δg < eps` → SINGULAR_HESSIAN | 绝对阈值 | ✅ 改为相对图像对比度，增益/偏置不变 |
| §2.6 `cond(H) > 1e10` → SINGULAR_HESSIAN | ❌ 未实现 | ✅ 已实现（尺度化 Hessian） |
| §2.6 失败状态码全集（9 个） | 缺 2 个 | ✅ 补齐；`NO_INITIAL_GUESS` 已启用，`MASKED` 占位 |
| §1.5 每点失败原因诊断 | 仅逐点 status | ✅ 增加 `status_counts()` 分布 |
| §2.11 不外推、不零填充 | `masked()` | ✅ 保持，并拒绝无法置 NaN 的字段 |
| §5.8 T8 不连续场 / 遮挡 | ❌ | ❌ 仍未做（需要 mask 功能） |
| 其余（ZNSSD/IC-GN/B 样条/FFT-CC/协方差） | 见 R2-O1 §5 | 数学未改动，数字逐位不变 |

---

## 9. 复现

```bash
cd /workspace
python3 -m pytest tests/test_icgn_synth.py -q
# 127 passed in 8.83s

# CI 口径全仓
python3 -m pytest -q tests src/tests
# 193 passed in 10.93s
```

精度与吞吐（不属于测试，是测量脚本）：

```python
import sys; sys.path[:0] = ["src", "tests"]
import time
import numpy as np
from test_icgn_synth import speckle_pair
from hl3.correlate import ICGNParams, icgn_first_order, make_grid

ref, tgt = speckle_pair((0.37, -0.42), size=192)
params = ICGNParams(subset_radius=10, step=8)
pts = make_grid(ref.shape, params, margin=40)

best = float("inf")
for _ in range(7):
    start = time.perf_counter()
    res = icgn_first_order(ref, tgt, pts, params)
    best = min(best, time.perf_counter() - start)

err = np.concatenate((res.u - 0.37, res.v + 0.42))
print("mean |error| =", np.mean(np.abs(err)), "px")   # 8.077597688e-04
print("throughput   =", len(pts) / best, "POI/s")     # 763 ~ 780，见 §5
```

对比 R2 内核（验证 51 条新用例确实是守卫）：

```bash
# 7e347c9 = 本分支的基线提交，correlate 内容与 R2-O1 交付的一致
cp src/hl3/correlate/icgn.py /tmp/new_icgn.py
git show 7e347c9:src/hl3/correlate/icgn.py > src/hl3/correlate/icgn.py
python3 -m pytest tests/test_icgn_synth.py -q   # 51 failed, 76 passed
cp /tmp/new_icgn.py src/hl3/correlate/icgn.py
```
