ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR1-F4 · 应变张量与 `@vsg_px` 的 HDF5 落盘说明

- **子代理**：IR1-F4（fable，Impl-R1 / S1）
- **独占路径**：`.agent_workspace/s1s4/IR1-F4-strain-schema.md`（仅本文件）
- **依据**：`docs/schema-hdf5.md`（`hl3-schema 1.0.0-draft.2`，下称「规范」）与其机器可读镜像 `src/hl3/io/hdf5_schema.py`（下称「参考实现」）
- **纪律**：本任务**零实现** —— 不写 `src/**`、不写测试；显微镜（§6.1 `stereo_microscope` 畸变模型）**零实现**，本文只在 §11 声明其与应变 schema 的（不）相关性。`git add` 仅本文件，不用 `git add .`。

---

## 0. TL;DR

应变结果落在 **`/analyses/<ana_id>/strain/<strain_id>`**（规范 §9.3）。每个 strain 组带 4 个必填属性（`@tensor`、`@method`、`@window_pts`、`@vsg_px`）与 3 个必填数据集（`exx`、`eyy`、`exy`，形状 `(F, P) f32`）；`@vsg_px` 是**整个格式里少数被抬到必填级别的派生量**，定义为 `(window_pts - 1) * step_px + subset_px`，参考实现 `vsg_size_px()` 与规范散文逐字对应。应变值**恒以无量纲比值存储**，`/project/units@strain_display` 只管显示；有效性判据不在 strain 组内，而是复用 `fields/flags` 位域。给 IR1-O2（`src/hl3/strain/**`）的落盘检查单见 §10；规范与验证器目前的空隙（不在本任务修）见 §12。

---

## 1. 应变落在哪：路径与多套应变

```
/analyses/<ana_id>/strain/<strain_id>/
```

- `<strain_id>` 遵循 §2.1 实体 ID 规则：`[a-z0-9][a-z0-9_-]{0,63}`，同层唯一。
- 一个分析下**可以**挂多套应变场（不同平滑窗、不同张量定义各占一个 id），`default` 为默认视图。参考实现常量 `DEFAULT_STRAIN_ID = "default"`，路径助手 `strain_path(ana_id, strain_id="default")`。
- 多套应变的动机是把「空间分辨率 vs 噪声」的权衡显式化：同一位移场用 `window_pts=5` 和 `window_pts=15` 各算一套，两套的 `@vsg_px` 不同，读者一眼可见谁更平滑。
- strain 组本身**可以**整体缺省（分析只存位移不算应变是合法文件）；但一旦存在某个 `<strain_id>`，其必填属性与数据集全部生效。

维度中立原则（P4）下，2D 与 3D 分析共用这一路径；3D 只**增加**可选数据集（曲率、表面法向），不改变 `exx/eyy/exy` 的语义。

## 2. strain 组的属性

| 属性 | 类型 | 级别 | 合法取值 / 定义 |
|------|------|------|------------------|
| `@tensor` | `str` | **必须** | `"engineering"` \| `"green_lagrange"` \| `"euler_almansi"` \| `"hencky"` \| `"logarithmic"` |
| `@method` | `str` | **必须** | `"local_plane_fit"` \| `"savitzky_golay"` \| `"fe_gradient"` \| `"spline_global"` |
| `@window_pts` | `i32` | **必须** | 平滑窗内测点数，**奇数** |
| `@vsg_px` | `f64` | **必须** | 等效虚拟应变片尺寸 = `(window_pts−1)·step_px + subset_px`，见 §4 |
| `@vsg_mm` | `f64` | 有标定时必须 | `@vsg_px` 经标定尺度换算到物理长度 |

两条枚举都受 §11.2 读取器义务第 4 条约束：**未知 `@tensor` / `@method` 必须报错，不得猜测**。参考实现的 `read_analysis()` 对未知张量抛 `ValueError`，`validate_file()` 对两者都报违规（见 §9）。

`ezz_assumed` 数据集（见 §3）另带一个**数据集级**属性 `@assumption : str`（必须，如 `"incompressible_plastic"`）—— 注意它挂在数据集上，不在组上。

## 3. strain 组的数据集

除 `surface_normal` 为 `(F, P, 3)` 外，全部是 `(F, P) f32`；`F` 与 `frames/index` 长度一致，`P` 与 `grid/point_id` 长度一致 —— 应变列与位移列逐点对齐，SoA 列式（P3）。

| 数据集 | 形状 | 级别 | 说明 |
|--------|------|------|------|
| `exx` `eyy` `exy` | `(F,P) f32` | **必须** | 张量分量，定义由 `@tensor` 决定 |
| `e1` `e2` `theta_p` | `(F,P) f32` | 应当 | 主应变与主方向；`theta_p` 的单位由 `/project/units@angle`（`"deg"` \| `"rad"`）决定，**不得**自带单位假设 |
| `gamma_max` `von_mises` | `(F,P) f32` | 可选 | 派生标量 |
| `ezz_assumed` | `(F,P) f32` | 可选 | 平面外应变的**假设值**，必须带 `@assumption` |
| `curvature_k1` `curvature_k2` | `(F,P) f32` | 3D 可选 | 主曲率 |
| `surface_normal` | `(F,P,3) f32` | 3D 可选 | 当前表面法向 |

参考实现常量：`DS_EXX/DS_EYY/DS_EXY`、`DS_E1/DS_E2/DS_THETA_P`、`DS_GAMMA_MAX/DS_VON_MISES`；必填集合 `STRAIN_REQUIRED = ("exx", "eyy", "exy")`。

## 4. `@vsg_px`：定义、计算链与为什么必填

### 4.1 定义

```
vsg_px = (window_pts − 1) · step_px + subset_px
```

三个输入的落盘位置都在**同一分析**内，可交叉复核：

| 输入 | 落盘位置 | 级别 |
|------|----------|------|
| `window_pts` | `strain/<id>@window_pts` | 必须（奇数） |
| `step_px` | `grid/@step_px` | `@kind="regular"` 时必须 |
| `subset_px` | `grid/@subset_px` | 局部 DIC 必须（奇数） |

参考实现 `vsg_size_px(window_pts, step_px, subset_px)`（`hdf5_schema.py` §13 映射表「§9.3 `@vsg_px`」行）执行同一公式，并拒绝偶数 `window_pts`/`subset_px` 与非正 `step_px`。合成算例 `SyntheticSpec` 的默认值 `window_pts=5, step_px=7, subset_px=29` 给出 `vsg_px = (5−1)·7 + 29 = 57.0`，与 `selftest` 输出的 `vsg=57.0 px` 一致。

直觉：应变点的值实际上「看到」了平滑窗最外侧测点的子区边缘 —— 窗跨 `(window_pts−1)·step_px`，两端各再伸出半个子区，共加一个 `subset_px`。它就是该应变值的**空间支持域直径**，等效于实验力学里的虚拟应变片（VSG）尺寸。

### 4.2 `@vsg_mm`

有标定时必须写 `@vsg_mm`，即 `@vsg_px` 乘以像素→物理尺度。尺度来源按标定方式不同：`@method="scale_only"` 时用 `/calibrations/<cal_id>@scale_mm_per_px`；完整标定时由坐标系链（§4 `scale` 数据集或标定内外参）导出。未标定的 2D 分析（`fields/u@space="px"`）**不写** `@vsg_mm` —— 与 §9.2「不得假借 1 px = 1 mm」同一条红线。

### 4.3 为什么抬到必填

规范原文（§9.3）：「空间分辨率与噪声的权衡是 DIC 结果最容易被误读之处；把它做成必填字段，报告里就无法省略。」换言之：`exx` 的数值离开 `@vsg_px` 没有解释力 —— 同一位移场换个平滑窗，峰值应变可以差数倍。这也是 `validate_file()` 把缺 `@vsg_px` 列为结构违规（而非 strict 级警告）的原因。

## 5. 单位与显示

- 应变分量**恒以无量纲比值存储**（0.001 就存 0.001）。`/project/units@strain_display`（`"1"` \| `"percent"` \| `"microstrain"`）**只影响显示**，任何写入器不得按显示单位缩放数据。参考实现的合成算例即是明证：`units@strain_display = "microstrain"`，但 `exx` 存的是 `1e-3·f` 的原始比值。
- `theta_p` 单位跟随 `/project/units@angle`。
- 缺失值按 §2.2 用 `NaN` 填充，并在数据集属性 `@fill_value` 中声明。

## 6. 有效性：strain 组没有自己的 flags

有效性判据**不在** strain 组内 —— 复用 `fields/flags (F,P u32)` 位域（§9.5）：

```
有效 := (flags & (MASKED | OUTLIER_FILTERED | INTERPOLATED_FILL)) == 0
        && (flags & CONVERGED)
```

参考实现提供 `valid_mask(flags)`；附录 D 的 20 行独立读取示例演示了「先取 flags 求 good 掩膜，再对 `strain/default/exx` 做掩膜均值」的标准姿势。写入器一侧的推论：无效点的应变值**应当**写 `NaN` 而不是 0 —— 0 是合法应变，会污染下游统计。

## 7. 不确定度挂钩：`uncertainty/strain_std/<name>`

应变的标准差落在分析级 `uncertainty/` 组的子组里（§9.4）：

```
/analyses/<ana_id>/uncertainty/strain_std/<name>   (F,P f32)  可选
```

`<name>` 与 strain 组下的数据集**同名**（`exx`、`e1`、`von_mises` …）。参考实现常量 `SG_STRAIN_STD = "strain_std"`。注意规范这里只锚定了「名字与 strain/ 下变量同名」，**没有**给出多套应变（多个 `<strain_id>`）时 `strain_std` 归属哪一套的判别 —— 见 §12 空隙 G-3。

## 8. 分块与压缩（附录 A）

| 项 | 规范默认 | 参考实现行为 |
|----|----------|--------------|
| 分块 | `strain/*` 同 `fields/*`：`(min(F,16), min(P,4096))` | `default_chunks(shape, kind="field")`，逐维收缩 |
| 压缩 | zstd-3 + shuffle（**默认值非硬性**，A.1） | 有 `hdf5plugin` 时 `Zstd(clevel=3)` 标 `"zstd:3"`；否则降级 `gzip:4+shuffle` |
| 属性 | 应当写 `@chunk` 与 `@compression`（如实） | `_write_dataset()` 写入两者 |
| 极小数据集 | 可以不分块不压缩（A.1 第 4 条） | 元素数 < 64 时直接连续存储，不写 `@chunk`/`@compression` |

具体例子：合成算例 `F=3, P=20`（60 元素）的 `exx` 落盘为**未分块未压缩**的连续数据集 —— 这是 A.1 第 4 条的直接体现，不是缺陷。一切降级都写进文件（`@compression` 必须如实），不写进口头约定。

## 9. 参考实现映射（读 / 写 / 验三条链）

| 环节 | 符号 | 行为 |
|------|------|------|
| 常量 | `SG_STRAIN`、`DEFAULT_STRAIN_ID`、`DS_EXX…DS_VON_MISES`、`STRAIN_REQUIRED_ATTRS`、`STRAIN_REQUIRED`、`STRAIN_TENSORS`、`STRAIN_METHODS` | 零依赖可导入（§13.1 分层：无 h5py 也能查枚举） |
| 写 | `write_synthetic_hl3()` | 建 `strain/default`，写 4 个必填属性（`tensor="engineering"`、`method="local_plane_fit"`、`window_pts`、`vsg_px=spec.vsg_px`），经 `_write_dataset` 写 `exx/eyy/exy` |
| 读 | `read_analysis(path, strain_id="default")` | 校验 `@tensor ∈ STRAIN_TENSORS`（未知即抛错，§11.2 条 4），全部数据集与属性进 `AnalysisData.strain / .strain_attrs`；`AnalysisData.vsg_px` 便捷属性 |
| 验 | `validate_file()` | 对**每个** `<strain_id>`：查 4 个必填属性、`@tensor`/`@method` 枚举、`exx/eyy/exy` 存在性 |
| 回归 | `python3 -m hl3.io.hdf5_schema selftest` | 写→读→与解析解逐位比对（含 `exx` 与 `vsg_px==spec.vsg_px` 断言）→ validate + strict |

合成算例的应变有闭式解（`exx = ε·f`、`eyy = −ν·ε·f`、`exy = 0`，§13.2），所以这条 IO 链的回归不依赖相关器，也不依赖 IR1-O2 的应变模块 —— 两者可以并行收敛。

## 10. 给 IR1-O2（`src/hl3/strain/**`）的落盘检查单

实现应变计算模块时，落盘侧逐条对照：

1. 输出 `exx/eyy/exy` 为 `(F, P) float32`，与 `fields/u` 同形状、与 `grid/point_id` 同点序；
2. 组属性齐 4 件：`@tensor`（从 `STRAIN_TENSORS` 取）、`@method`（从 `STRAIN_METHODS` 取）、`@window_pts`（i32，奇数）、`@vsg_px`（f64，用 `vsg_size_px()` 算，别手写公式）；
3. 有标定才写 `@vsg_mm`；未标定连属性都不要出现；
4. 无效点（按 `fields/flags` 判）写 `NaN`，不写 0；平滑窗内有效点不足时同样写 `NaN` 并考虑置 `fields` 层相应诊断；
5. `theta_p` 按 `/project/units@angle` 的单位写，勿硬编码弧度或度;
6. 写 `ezz_assumed` 就必须带数据集属性 `@assumption`；
7. 多套平滑窗各占一个 `<strain_id>`，`default` 留给推荐参数那套；
8. 数据集经与 `_write_dataset` 等价的路径写（`kind="field"` 分块 + 如实 `@compression`）；
9. 落盘后跑 `validate_file(path, strict=True)` 应零违规；`read_analysis()` 读回的 `strain_attrs["vsg_px"]` 与输入参数重算值逐位相等；
10. 邻域算子（`local_plane_fit` 等）**应当**消费并回写 `grid/neighbors`（CSR），保证「窗内测点数」与 `@window_pts` 的口径一致可审计。

## 11. 显微镜：明确不在本任务与本 schema 路径上

SOP 红线「显微镜零实现」在 schema 侧的对应事实：整份规范唯一的显微镜触点是 §6.1 畸变模型枚举里的 `stereo_microscope`（参数由 `@model_params` JSON 自描述，实现相关）。它属于 `/calibrations/**`，与 §9.3 的应变布局**正交** —— 应变组不感知畸变模型，只感知 `grid` 与标定尺度换算后的 `@vsg_mm`。本轮：不实现、不设计、不扩展 `stereo_microscope` 的任何参数化；本文也不为其新增规范文字。无 VIC 逆向内容 —— 本文全部依据是仓库内 CC-BY-4.0 规范与 Apache-2.0 参考实现。

## 12. 发现但不修的空隙（记账，供后续轮次裁决）

| # | 空隙 | 细节 | 建议归属 |
|---|------|------|----------|
| G-1 | 非 regular 网格的 `@vsg_px` 无定义 | 公式依赖 `step_px`，但 `@step_px` 只在 `grid/@kind="regular"` 时必填；`scattered`/`fe_mesh`/`marker_set` 网格下 `@vsg_px` 仍是必填却无计算口径（等效平均点距？外接圆？） | schema 负责人（规范文字），draft.3 |
| G-2 | 验证器不查 `@vsg_mm` 条件必填 | `STRAIN_REQUIRED_ATTRS` 只含 4 项；「有标定时必须 `@vsg_mm`」这条 MUST 目前无人执行。同理不查 `@window_pts` 奇数、不查 strain 数据集形状与 `fields/u` 一致、不查 `@vsg_px` 与 grid 属性重算值吻合（strict 级适合做后两条） | `validate_file()` 增强，Impl-R2 |
| G-3 | `strain_std` 与多 `<strain_id>` 的归属 | `uncertainty/strain_std/<name>` 按名字对齐 strain 数据集，但一个分析多套应变时无从判断 std 属于哪套；单套时无歧义 | schema 负责人，draft.3 |
| G-4 | `hencky` 与 `logarithmic` 双枚举 | 物理上是同一张量（Hencky = 对数应变），枚举却是两个值；读取器按 §11.2 只能原样区分。要么在规范里写明互为别名，要么废弃其一（废弃需升主版本，代价高，别名是便宜解） | schema 负责人，draft.3 |
| G-5 | zstd 标签的 shuffle 口径 | 附录 A 表写 `zstd-3 + shuffle`，参考实现 zstd 路径实际不加 shuffle 且如实标 `"zstd:3"` —— 符合 A.1「如实写明」，但与默认值表格有出入 | 无害；A.1 已豁免，记录备查 |

以上任何一条都**不在**本文件独占路径内动手 —— 本文只记账。

---

## 13. 复核方式

本文的每一条规范性陈述可对照 `docs/schema-hdf5.md` §2.1/§2.2/§9.3–§9.5/§11.2/§13/附录 A/附录 D；每一条实现行为陈述可对照 `src/hl3/io/hdf5_schema.py` 的 `STRAIN_*` 常量、`vsg_size_px()`、`write_synthetic_hl3()`、`read_analysis()`、`validate_file()`，或直接运行：

```bash
PYTHONPATH=src python3 -m hl3.io.hdf5_schema selftest
# 预期输出含：vsg=57.0 px、空间单位=px、往返一致 u/v/exx
```
