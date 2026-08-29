<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# HL3 数据格式规范（HDF5 容器）

**规范版本**：`hl3-schema 1.0.0-draft.2`
**容器**：HDF5 1.10+（`.hl3`）／Zarr v3（`.hl3z`，见附录 C）
**授权**：本规范文档以 CC-BY-4.0 发布（ADR-LIC-001），独立于内核代码的 Apache-2.0 许可证。任何人可自由实现读写器。
**状态**：草案。冻结条件见第 12 节。
**参考实现**：`src/hl3/io/hdf5_schema.py`（见第 13 节）

> 起草：Round 1 子代理 R1-O3；Round 2 由 R2-O3 修订至 `-draft.2`（修订记录见第 14 节，均为澄清与补充，无语义反转）。本规范为原创设计，基于 HDF5、OpenCV 相机模型约定、VTK/Exodus 数据模型与 iDICs 公开良好实践，**不含任何来自专有软件的逆向内容**。

---

## 1. 目的与设计原则

HL3-2D（单相机平面 DIC）与 HL3-3D（立体/多目 DIC）共用同一个文件格式。本规范的目标是让第三方**不依赖 HL3 软件**也能完整读取、验证与复现测量结果。

设计原则：

| 原则 | 含义 |
|------|------|
| **P1 自描述** | 单位、坐标系约定、算法配置、软件版本全部随数据存储，不依赖外部文档 |
| **P2 可溯源** | 输入哈希、配置哈希、随机种子、设备与线程数可查；结果可逐位复算 |
| **P3 列式** | 场数据按变量分列存储（SoA），支持按需读取与切片 |
| **P4 维度中立** | 2D 与 3D 使用同一路径树；3D 仅**增加**数据集，不改变已有数据集语义 |
| **P5 前向兼容** | 次版本号只增不改；读取器必须保留未知内容（见第 11 节） |
| **P6 双容器同构** | HDF5 与 Zarr 使用同一逻辑路径树，可无损互转 |

规范性关键词 **必须**（MUST）、**应当**（SHOULD）、**可以**（MAY）按 RFC 2119 解释。

---

## 2. 通用约定

### 2.1 命名

- 路径分量：小写蛇形 `snake_case`，ASCII，长度 ≤ 64。
- 实体 ID（`<cam_id>`、`<ana_id>` 等）：`[a-z0-9][a-z0-9_-]{0,63}`，同层唯一。
- 属性名以 `@` 在本文中标示，实际为 HDF5 attribute。

### 2.2 数据类型

| 本文记法 | HDF5 类型 |
|----------|-----------|
| `f32` / `f64` | `H5T_IEEE_F32LE` / `H5T_IEEE_F64LE` |
| `i32` / `i64` | `H5T_STD_I32LE` / `H5T_STD_I64LE` |
| `u8` / `u16` / `u32` / `u64` | 对应 `H5T_STD_U*LE` |
| `str` | `H5T_C_S1` + `H5T_VARIABLE`，UTF-8 编码 |
| `vlen-str` | 变长字符串一维数组 |
| `json` | 标量 `str`，内容为**规范化 JSON**（键排序、无多余空白、UTF-8） |

**字节序必须为小端**。所有浮点为 IEEE 754。缺失值用 `NaN`（浮点）或哨兵值 `-1`（索引类整数），并在数据集属性 `@fill_value` 中声明。

### 2.3 数组维度记法

`name(A, B, C dtype)` 表示形状 `(A, B, C)`、类型 `dtype` 的数据集。约定符号：

| 符号 | 含义 |
|------|------|
| `N` | 序列帧数 |
| `F` | 某分析实际求解的帧数（`F ≤ N`） |
| `P` | 测点数 |
| `C` | 单元数 |
| `M` | 模拟量样本数 |
| `Np` | 形函数参数个数（Rigid=2, Affine=6, Quadratic=12，二维情形） |
| `H`, `W` | 图像高、宽 |

**所有多维数组为 C 序（行主序）**，即最后一维变化最快。

### 2.4 时间戳

`@*_utc` 属性为 ISO 8601 UTC 字符串（`2026-08-28T14:29:00.123456Z`）。数据集里的 `timestamp_s` / `time_s` 为 `f64` 秒，属于**采集时钟域**（单调，原点任意），与 UTC 的对应关系由 `@epoch_utc` 给出。

### 2.5 哈希

所有 `*_hash` 与 `hashes` 使用 **BLAKE3-256**。属性形式为 64 位十六进制小写字符串；数据集形式为 `(n, 32) u8`。`@hash_algo` 必须写明（预留将来替换）。

`@hash_algo` 的合法取值：

| 取值 | 何时使用 |
|------|----------|
| `blake3-256` | 规范算法。写入器**应当**优先使用 |
| `blake2b-256` | 环境中没有 BLAKE3 实现时的降级值。BLAKE3 不在任何语言的标准库里，硬性要求它会让「零依赖参考读取器」这一目标落空 |

降级**必须**如实写进 `@hash_algo`，**不得**用 BLAKE3 的名义写 blake2b 摘要。跨文件比对哈希前，读取器必须先比对 `@hash_algo`；算法不同则哈希不可比，应报告为「无法校验」而不是「不匹配」。

---

## 3. 根组

```
/
  @hl3_schema_version : str   必须  语义化版本；冻结前为 "1.0.0-draft.N"，冻结后为 "1.0.0"
  @hl3_writer         : str   必须  "hl3-kernel 0.4.2 (git:9f1c2ab)"
  @uuid               : str   必须  RFC 4122 UUID；应当为 v4，确定性写入器可以用 v5（见 §14 A-3）
  @created_utc        : str   必须
  @modified_utc       : str   必须
  @hash_algo          : str   必须  "blake3-256" | "blake2b-256"，见 §2.5
  @metrology_certified: u8    可选  1 = 全程计量模式产出
  @generator_platform : str   应当  "linux-x86_64 / gcc-14"
```

顶层组：`project`、`cameras`、`calibrations`、`sequences`、`analog`、`aois`、`analyses`、`derived`、`provenance`、`thumbnails`。除 `project` 外均**可以**缺省（空工程合法）。

---

## 4. `/project`

```
/project
  @name        : str   必须
  @description : str   可选
  @operator    : str   可选
  @tags        : vlen-str 可选
  @constants   : json  可选   材料/试验常量，供公式引用：{"E":210000.0,"nu":0.3}

/project/units
  @length          : str  必须  显示单位，如 "mm"（存储恒为 SI 基本单位）
  @time            : str  必须  "s"
  @force           : str  可选  "kN"
  @angle           : str  必须  "deg" | "rad"
  @strain_display  : str  必须  "1" | "percent" | "microstrain"
  @temperature     : str  可选  "degC" | "K"

/project/coordinate_systems/<cs_id>
  @kind      : str  必须  "image" | "sensor" | "camera" | "rig" | "world" | "specimen" | "plot" | "user"
  @parent    : str  必须  父坐标系 id；根坐标系写 ""
  @camera    : str  可选  kind ∈ {image, sensor, camera} 时指向 /cameras/<cam_id>
  transform    (4,4 f64)  必须  齐次矩阵，作用于列向量：p_parent = T · p_self
  scale        (标量 f64) 可选  各向同性尺度（默认 1.0；2D 像素→物理用）
  covariance   (6,6 f64)  可选  位姿协方差，顺序 [tx,ty,tz,rx,ry,rz]，旋转为轴角小量
```

### 4.1 强制坐标约定（不可协商）

违反以下约定的文件不合规 —— 这些约定是跨软件结果可比的前提。

| 坐标系 | 约定 |
|--------|------|
| `image` | 像素坐标 `(u, v)`；`u` 向右，`v` 向下；**原点 (0,0) 位于左上角像素的中心**。另有 `@pixel_origin = "corner"` 时原点位于该像素左上角，读取器必须尊重此属性 |
| `sensor` | 归一化相机坐标 `(x, y)`，已去畸变，`x = X/Z`，`y = Y/Z` |
| `camera` | 右手系；**+Z 沿光轴指向场景，+X 向右，+Y 向下**（OpenCV 约定） |
| `world` | 右手系；默认由标定确立 |
| `specimen` | 右手系；由用户对齐操作确立，`transform` 必须记录该对齐 |

`plot` 坐标系**仅影响显示**，读取器可忽略。

坐标系构成有向树（或图）。求任意两系间变换时沿路径复合；**不得**在无路径时假设单位阵，必须报错。

---

## 5. `/cameras/<cam_id>`

```
/cameras/<cam_id>
  @label              : str  必须
  @vendor @model @serial : str 可选
  @role               : str  必须  "primary" | "secondary" | "auxiliary" | "thermal" | "reference"
  @width_px           : i32  必须
  @height_px          : i32  必须
  @pixel_pitch_um     : f64  可选  0 = 未知
  @pixel_aspect       : f64  必须  sy/sx，默认 1.0
  @bit_depth          : i32  必须  8 | 10 | 12 | 14 | 16
  @shutter            : str  必须  "global" | "rolling"
  @rolling_readout_us : f64  必须  shutter="global" 时为 0
  @coord_system       : str  必须  指向 /project/coordinate_systems/<cs_id>
  lens/               可选组
    @focal_mm @f_number @working_distance_mm : f64
    @telecentric : u8
```

相机描述"设备是什么"，标定描述"某次测到什么"。同一相机可被多个标定引用。

---

## 6. `/calibrations/<cal_id>`

```
/calibrations/<cal_id>
  @method         : str  必须  "planar_target_zhang" | "bundle_adjust" | "self_calib" | "imported" | "scale_only"
  @epoch_utc      : str  必须
  @rms_reproj_px  : f64  必须
  @n_views        : i32  必须
  @score          : f64  可选  [0,1] 质量评分
  @scale_mm_per_px: f64  可选  仅 method="scale_only"（2D 退化标定）使用

  cameras/<cam_id>/
    K        (3,3 f64) 必须   [[fx, s, cx],[0, fy, cy],[0,0,1]]，像素单位，遵循 §4.1 image 约定
    dist     (nd  f64) 必须   长度由 @model 决定
      @model : str 必须  见 §6.1
    R        (3,3 f64) 必须   rig ← camera 旋转
    t        (3   f64) 必须   rig ← camera 平移，单位 m

  covariance   (Np_all, Np_all f64) 应当  全部标定参数的协方差
  param_names  (Np_all vlen-str)    covariance 存在时必须  行列语义
  residuals    (V, Q, 2 f32)        应当  每视图每靶点的重投影残差（像素）
  target/
    @kind    : str 必须  "checkerboard" | "circle_grid" | "aruco" | "charuco" | "custom"
    @rows @cols : i32 可选
    @pitch_mm   : f64 可选
    points   (Q,3 f64) 必须  靶标点标称坐标（靶标系，米）
    ids      (Q i64)   可选
```

### 6.1 畸变模型标识

| `@model` | 参数顺序（`dist` 数组）|
|----------|----------------------|
| `none` | 空 |
| `brown_conrady_k3p2` | `k1, k2, p1, p2, k3` |
| `brown_conrady_k6p2s4` | `k1, k2, p1, p2, k3, k4, k5, k6, s1, s2, s3, s4` |
| `division_k1` | `k1` |
| `opencv_fisheye` | `k1, k2, k3, k4` |
| `telecentric` | `k1, k2`（正交投影下的径向项）|
| `stereo_microscope` | 由 `@model_params` JSON 描述，实现相关 |
| `generic_poly2d` | `@poly_order` + 系数展平 |

未知 `@model` 时读取器**必须**报错而非静默按针孔处理。

**协方差是"应当"而非"可选"**：不确定度传播依赖它。仅给 RMS 标量的文件可读，但不能用于 `uncertainty/@method = "propagated"`。

---

## 7. `/sequences/<seq_id>`

```
/sequences/<seq_id>
  @label        : str  必须
  @frame_count  : i64  必须  = N
  @fps_nominal  : f64  可选
  @epoch_utc    : str  应当  timestamp_s 原点对应的 UTC 时刻

  frames/
    index        (N i64) 必须  采集端原始帧号，可不连续、必须严格递增
    timestamp_s  (N f64) 必须  单调递增
    trigger_id   (N i64) 可选  -1 = 无
    roi_offset   (N,2 i32) 可选  传感器 ROI 左上角 (x,y)，用于高速相机 ROI 漂移补偿

  images/<cam_id>/
    @storage     : str  必须  "embedded" | "external" | "none"
    @format      : str  必须  "tiff" | "png" | "raw16" | "cine" | "mraw" | ...
    @compression : str  storage="embedded" 时必须
    -- storage="embedded":
    data         (N,H,W u8|u16) 或 (N,H,W,3 u8|u16)  必须
    -- storage="external":
    paths        (N vlen-str) 必须  相对于文件所在目录（应当）或绝对路径
    hashes       (N,32 u8)    应当  BLAKE3-256，用于完整性校验
```

`@storage = "none"` 表示只保留结果、丢弃图像（发布数据集常见）。此时分析结果仍完全可读，但不可重算。

**参考帧不在此定义**。参考帧策略属于分析（§9），同一序列可挂多个不同参考策略的分析。

---

## 8. `/analog/<chan_id>` 与 `/aois/<aoi_id>`

### 8.1 模拟量通道

```
/analog/<chan_id>
  @label           : str  必须  如 "load"
  @unit            : str  必须  SI 或可解析单位串，如 "N"
  @sample_rate_hz  : f64  必须
  @gain @offset    : f64  可选  已应用于 value 则写 1.0/0.0
  @sync            : str  必须  "hardware_trigger" | "timestamp_match" | "manual_offset" | "none"
  @clock_offset_s  : f64  必须  通道时钟 → 序列时钟的偏移
  @sequence        : str  必须  绑定的序列 id
  time_s     (M f64) 必须
  value      (M f64) 必须  已换算为 @unit
  frame_map  (N i64) 应当  每帧对应的样本下标，-1 = 无对应
```

`frame_map` **预计算并持久化**：同步策略是需要被审计的决定，不能是读取时的隐式插值。

### 8.2 AOI

```
/aois/<aoi_id>
  @label            : str  必须
  @sequence         : str  必须
  @reference_camera : str  必须
  @mode             : str  必须  "static" | "tracked_rigid" | "tracked_deformable" | "per_frame"
  polygons/<k>/
    @role     : str  必须  "outer" | "hole"
    vertices  (V,2 f64) 必须  image 坐标，逆时针为正向
  seeds/
    xy         (S,2 f64) 必须
    camera     (S vlen-str) 可选  多相机时种子所属相机
    auto       (S u8)    可选  1 = 自动检测
    confidence (S f32)   可选
    initial_p  (S,Np f32) 可选  手动初值
  mask         (H,W u8) 可选  0 = 排除
  valid_frames (N u8)   可选  0 = 该帧禁用该 AOI
```

`@mode = "per_frame"` 时，`polygons` 下改为 `<k>/vertices_per_frame (N,V,2 f64)`，且 `V` 必须逐帧一致。

---

## 9. `/analyses/<ana_id>` —— 核心

```
/analyses/<ana_id>
  @label            : str  必须
  @type             : str  必须  "2d" | "stereo" | "multiview"
  @created_utc      : str  必须
  @kernel_version   : str  必须
  @git_sha          : str  应当
  @config_hash      : str  必须  规范化 config JSON 的 BLAKE3
  @input_hash       : str  必须  (图像哈希 + 标定 + AOI) 的 BLAKE3
  @parent_analysis  : str  可选  由哪个分析派生（重算/改参）
  @sequence @aoi    : str  必须
  @calibration      : str  type="2d" 时可选，否则必须
  @reference_policy : json 必须  {"kind":"fixed","frame":0} |
                                  {"kind":"incremental"} |
                                  {"kind":"multi","breakpoints":[0,150,400]}
  config              (标量 json) 必须  完整求解配置，规范化 JSON
```

### 9.1 `grid/`

```
  grid/
    @kind            : str  必须  "regular" | "scattered" | "fe_mesh" | "marker_set"
    @subset_px       : i32  局部 DIC 必须（奇数）
    @step_px         : i32  kind="regular" 必须
    @window          : str  必须  "square" | "circular" | "adaptive"
    @shape_function  : str  必须  "rigid" | "affine" | "quadratic" | 插件 id
    @n_shape_params  : i32  必须  = Np
    point_id   (P u64)   必须  跨帧/跨分析稳定的点标识
    ref_xy     (P,D f64) 必须  D ∈ {2,3}；2D/立体表面 DIC 为 2，DVC 为 3
    valid      (P u8)    必须
    cells/                可选（kind ∈ {regular, fe_mesh} 应当提供，供 VTK/Exodus 导出）
      offsets  (C+1 i64) 必须  CSR 偏移
      nodes    (* i64)   必须  单元 → 点索引
      types    (C u8)    必须  VTK 单元类型码
    neighbors/            应当（应变算子/平滑用）
      offsets  (P+1 i64) 必须
      idx      (* i32)   必须
```

`ref_xy` 最后一维**允许为 2 或 3**，为将来的体相关（DVC）预留，避免破坏性变更。

### 9.2 `frames/` 与 `fields/`

```
  frames/index (F i64) 必须  求解的帧在 /sequences/<seq>/frames 中的下标

  fields/
    u        (F,P f32) 必须
    v        (F,P f32) 必须
    w        (F,P f32) type ∈ {stereo, multiview} 必须
    X Y Z    (F,P f32) 3D 应当   当前形貌（world 系，米）
    X0 Y0 Z0 (P   f32) 3D 应当   参考形貌
    disparity(F,P,2 f32) stereo 可选  诊断用
    p_shape  (F,P,Np f32) 应当
    zncc     (F,P f32) 必须  归一化互相关，[-1,1]
    sigma    (F,P f32) 应当  匹配残差（ZNSSD 等）
    iters    (F,P u16) 可选
    flags    (F,P u32) 必须  位域见 §9.5
```

**单位规则（不可协商）**：`u v w` 的单位由 `@space` 属性声明，取值 `"px"` 或 `"m"`。未标定的 2D 分析必须写 `"px"`，**不得**假借"1 px = 1 mm"。`X Y Z` 恒为米。

### 9.3 `strain/<strain_id>`

一个分析下**可以**有多套应变场（不同平滑窗/张量），`default` 为默认视图。

```
  strain/<strain_id>
    @tensor      : str  必须  "engineering" | "green_lagrange" | "euler_almansi" | "hencky" | "logarithmic"
    @method      : str  必须  "local_plane_fit" | "savitzky_golay" | "fe_gradient" | "spline_global"
    @window_pts  : i32  必须  平滑窗内测点数（奇数）
    @vsg_px      : f64  必须  等效虚拟应变片尺寸 = (window_pts-1)*step_px + subset_px
    @vsg_mm      : f64  有标定时必须
    exx eyy exy            (F,P f32) 必须
    e1 e2 theta_p          (F,P f32) 应当   主应变与主方向（theta_p 单位见 /project/units@angle）
    gamma_max von_mises    (F,P f32) 可选
    ezz_assumed            (F,P f32) 可选   @assumption : str 必须（如 "incompressible_plastic"）
    curvature_k1 k2        (F,P f32) 3D 可选
    surface_normal         (F,P,3 f32) 3D 可选
```

`@vsg_px` **必须**存在。空间分辨率与噪声的权衡是 DIC 结果最容易被误读之处；把它做成必填字段，报告里就无法省略。

### 9.4 `uncertainty/` 与 `diagnostics/`

```
  uncertainty/
    @method                : str 必须  "propagated" | "bootstrap" | "repeat_static" | "synthetic_calibrated"
    @sigma_u_px_floor      : f64 应当  实测噪声底板
    @sigma_v_px_floor      : f64 应当
    @image_noise_sigma_dn  : f64 应当  图像噪声估计（DN）
    @calib_contrib_frac    : f64 3D 应当  标定不确定度占总方差比例
    @bootstrap_draws       : i32 method="bootstrap" 必须
    u_std v_std            (F,P f32) 必须
    w_std                  (F,P f32) 3D 必须
    cov_uvw                (F,P,6 f32) 可选  上三角 [Cuu,Cuv,Cuw,Cvv,Cvw,Cww]
    strain_std/<name>      (F,P f32) 可选  名字与 strain/ 下变量同名

  diagnostics/
    @solve_wall_s   : f64 必须
    @threads        : i32 必须
    @device         : str 必须  "cpu" | "cuda:0" | "vulkan:0" | ...
    @rng_seed       : u64 必须
    @deterministic  : u8  必须  1 = 该结果承诺可逐位复现
    @gpu_fast_math  : u8  可选  1 = 启用了破坏一致性的快速数学
    per_frame_time_s (F f64) 可选
    convergence_hist (F,32 i64) 可选  迭代次数直方图
```

### 9.5 `flags` 位域（跨版本稳定，不得复用已分配位）

| bit | 掩码 | 名称 | 含义 |
|-----|------|------|------|
| 0 | `0x00000001` | `CONVERGED` | 达到收敛判据 |
| 1 | `0x00000002` | `MASKED` | 被 AOI/掩膜排除 |
| 2 | `0x00000004` | `SEEDED` | 种子点或由种子直接传播 |
| 3 | `0x00000008` | `EXTRAPOLATED` | 初值来自外推 |
| 4 | `0x00000010` | `EDGE_CLAMPED` | 子区触及图像/AOI 边界 |
| 5 | `0x00000020` | `LOW_CONTRAST` | 子区梯度能量低于阈值 |
| 6 | `0x00000040` | `EPIPOLAR_REJECT` | 立体极线残差超限 |
| 7 | `0x00000080` | `TRIANGULATION_ILL` | 三角化条件数差 |
| 8 | `0x00000100` | `OUTLIER_FILTERED` | 后处理判为离群 |
| 9 | `0x00000200` | `INTERPOLATED_FILL` | 值来自空洞填补而非求解 |
| 10 | `0x00000400` | `GPU_PATH` | 由 GPU 后端求解 |
| 11 | `0x00000800` | `ROLLING_CORRECTED` | 已做卷帘快门补偿 |
| 12–23 | — | 保留 | 由本规范未来版本分配 |
| 24–31 | — | 插件私有 | 插件可用，语义写入 `config` |

有效数据的判定标准：`(flags & (MASKED|OUTLIER_FILTERED|INTERPOLATED_FILL)) == 0 && (flags & CONVERGED)`。读取器**应当**提供此判定的便捷函数，避免各实现口径不一。

---

## 10. `/derived`、`/provenance`、`/thumbnails`

```
/derived/<var_id>
  @name        : str  必须  公式中引用的标识符
  @expr        : str  必须  表达式源码
  @expr_hash   : str  必须
  @unit        : str  必须
  @domain      : str  必须  "point" | "frame" | "global"
  @analysis    : str  必须  所属分析
  depends_on   (vlen-str) 必须  依赖的变量名（用于失效传播与拓扑序）
  value        (F,P f32 | F f32 | 标量 f32) 可选  缓存；无缓存时读取器可重算

/provenance
  log      (vlen-str, 可扩展一维) 必须  只追加的 JSONL，每行至少含
           {"ts":"...","actor":"gui|cli|python|plugin","event":"...","detail":{...}}
  inputs/hashes (vlen-str) 应当  "path\tblake3" 形式

/thumbnails/<seq_id>
  data (N,h,w u8) 可选  快速预览用
```

`provenance/log` **只追加**。任何降级行为（GPU 回落 CPU、插件加载失败、外链哈希不匹配）都必须在此留痕，不得静默。

---

## 11. 兼容性与版本

### 11.1 语义化版本规则

| 变更类型 | 版本位 |
|----------|--------|
| 增加可选 group / dataset / attribute | 次版本号 +1 |
| 增加 `flags` 位、枚举取值、畸变模型 | 次版本号 +1 |
| 修改已有数据集的形状/语义/单位 | 主版本号 +1 |
| 删除数据集，或把"可选"变"必须" | 主版本号 +1 |
| 纠正文字、澄清措辞 | 修订号 +1 |

### 11.2 读取器义务

1. 主版本号高于自身支持的，**必须**拒绝并给出明确错误。
2. 次版本号高于自身支持的，**必须**能读取已知部分，并警告存在未知内容。
3. 改写文件时，**必须原样保留**所有未识别的 group、dataset 与 attribute。此条是生态不碎片化的关键。
4. 遇到未知 `@model` / `@tensor` / `@method` 枚举值，**必须**报错而非猜测。

### 11.3 写入器义务

1. `@hl3_writer` 必须包含软件名、版本与构建标识。
2. `@config_hash` / `@input_hash` 必须在结果写入时计算，不得留空。
3. 任何非默认的数值行为（快速数学、非确定性归约、有损图像压缩）必须体现在 `diagnostics` 属性与 `provenance` 中。

---

## 12. 一致性验证

规范要求参考实现提供：

```bash
hl3 validate file.hl3            # 结构 + 必填字段 + 交叉引用完整性
hl3 validate file.hl3 --strict   # 追加：SHOULD 级检查、哈希校验、单位可解析性
hl3 diff a.hl3 b.hl3             # 逐字段对比，用于回归
hl3 repack file.hl3 --layout point_major   # 重排分块以适配时程分析
```

**实现现状（截至当前提交，勿与上表混淆）**：`hl3` 命令行、`diff`、`repack` 与 `spec/conformance/` 样例集**均未实现**。今天真正存在的只有 Python 层的等价入口

```bash
python -m hl3.io.hdf5_schema selftest   # 写入合成算例 → 读回 → 与解析解逐位比对 → validate + strict
```

即 `validate_file(path, strict=...)`（对应上表第 1、2 行）与 `write_synthetic_hl3()` / `read_analysis()`。下表的用例分类是**目标集合**；`tests/test_hdf5_schema.py` 目前以 23 个测试覆盖其中的「2D 完整」一条、若干「非法」项（缺根属性、保留位、主版本过高、结构违规）与写入器确定性，其余类别尚无样例文件。

`spec/conformance/` 提供样例集，每个用例含 `input.hl3` + `expected.json` + `README`：

| 类别 | 用例 |
|------|------|
| 最小合法 | 空工程；仅相机；仅序列 |
| 2D 完整 | 单相机 + 未标定（px 单位）+ 应变 + UQ |
| 3D 完整 | 双相机 + 标定协方差 + 形貌 + UQ |
| 边界 | 全 NaN 帧；单点网格；单帧序列；多连通 AOI |
| 非法 | 缺 `@hl3_schema_version`；`flags` 用保留位；`u` 与 `v` 形状不一致；坐标系成环；主版本号过高 |
| 前向兼容 | 含未知 group 的文件，读-改-写后未知内容必须原样保留 |

### 12.1 冻结条件

`1.0.0` 在以下条件全部满足后冻结：

1. 参考实现通过全部一致性用例。
2. 至少一个**外部**独立读取器（非本项目）通过一致性用例。
3. iDICs Challenge 公开数据集完整跑通并存为 `.hl3`，结果与文献值一致。
4. 至少一个 3D 实测数据集完成完整不确定度链路验证。

冻结前版本号一律 `1.0.0-draft.N`，**不承诺兼容**。

---

## 13. 参考实现映射

本规范是散文，`src/hl3/io/hdf5_schema.py` 是它的**机器可读镜像**。散文与常量任何一处改动都必须同步改另一处，`tests/test_hdf5_schema.py` 做交叉断言。

| 规范条款 | 参考实现符号 |
|----------|--------------|
| §3 根属性 | `A_SCHEMA_VERSION` … `A_HASH_ALGO`、`ROOT_REQUIRED_ATTRS` |
| §3 顶层组 | `G_PROJECT` … `G_THUMBNAILS`、`TOP_LEVEL_GROUPS` |
| §4–§10 子组/数据集名 | `SG_*`（组）、`DS_*`（数据集）常量 |
| §4.1 / §5 / §6.1 / §9 枚举 | `COORD_SYSTEM_KINDS`、`CAMERA_ROLES`、`DISTORTION_MODELS`、`ANALYSIS_TYPES`、`STRAIN_TENSORS`、`UQ_METHODS` … |
| §6.1 `dist` 长度 | `DISTORTION_PARAM_COUNT` |
| §9.1 `Np` | `SHAPE_PARAM_COUNT`、`shape_param_count()` |
| §9.2 `@space` | `A_SPACE`、`SPACE_VALUES` |
| §9.3 `@vsg_px` | `vsg_size_px(window_pts, step_px, subset_px)` |
| §9.5 flags 位域 | `FieldFlags`、`ASSIGNED_FLAG_MASK`、`RESERVED_FLAG_MASK`、`PLUGIN_FLAG_MASK` |
| §9.5 有效性判据 | `valid_mask(flags)`、`describe_flags(value)` |
| §11.2 条 1 主版本拒绝 | `SUPPORTED_MAJOR`，`read_analysis` 与 `validate_file` 均执行 |
| §12 `hl3 validate` | `validate_file(path, strict=False)` |
| §2.5 哈希 | `content_hash()`、`config_hash()` |
| 附录 A 分块 | `default_chunks(shape, kind)` |
| 附录 B 规范化 JSON | `canonical_json(obj)` |
| §12 一致性样例生成 | `SyntheticSpec`、`write_synthetic_hl3()` |
| 附录 D 最小读取 | `read_analysis()` → `AnalysisData` |

### 13.1 依赖分层

常量、位域、路径助手、规范化 JSON 与哈希**只依赖标准库**：没有 h5py、甚至没有 numpy，`import hl3.io.hdf5_schema` 也必须成功。只有三个真正碰文件的入口需要 h5py，缺失时抛 `Hdf5Unavailable`，并由 `skip_reason()` 给出人话原因供 CI 跳过。

理由与 P1 一致：**schema 的定义本身不应该有安装门槛**。要求第三方先装齐二进制依赖才能查到「flags 的 bit 6 是什么」，等于把公开格式又关回去一半。

### 13.2 合成一致性算例

`write_synthetic_hl3()` 生成 §12 表中「2D 完整（单相机 + 未标定 px 单位 + 应变 + UQ）」用例。位移场为均匀单轴拉伸叠加刚体平移：

```
u(x, y, f) = tx·f + ε·f·(x − x₀)
v(x, y, f) = ty·f − ν·ε·f·(y − y₀)
```

于是 `exx = ε·f`、`eyy = −ν·ε·f`、`exy = 0` 逐点精确成立。**位移与应变都有闭式解**，所以往返读写可以逐位断言，不需要任何外部数据集，也不需要相关器参与 —— 这条 IO 回归链与 R2-O1 的 ICGN 内核完全解耦。

该文件位移单位写 `"px"`：合成算例没有标定，就不假借 1 px = 1 mm（§9.2）。

---

## 附录 A：默认分块与压缩

| 数据集 | 分块 | 压缩 | 理由 |
|--------|------|------|------|
| `fields/*` `(F,P)` | `(min(F,16), min(P,4096))` | zstd-3 + shuffle | 兼顾整帧渲染与单点时程 |
| `fields/p_shape` `(F,P,Np)` | `(min(F,8), min(P,2048), Np)` | zstd-3 + shuffle | 体积大、访问少 |
| `strain/*` `(F,P)` | 同 `fields/*` | zstd-3 + shuffle | |
| `uncertainty/cov_uvw` | `(min(F,8), min(P,2048), 6)` | zstd-3 + shuffle | |
| `images/data` | `(1,H,W)` | zstd-1 | 逐帧解码；有损编码走外链 |
| `analog/*` | `(min(M,65536),)` | zstd-3 | 长一维 |
| `provenance/log` | `(1024,)` | zstd-9 | 文本高压缩比 |

写入器**应当**在每个数据集上写 `@chunk`（实际分块）与 `@compression`（如 `"zstd:3+shuffle"`）。
根组**可以**写 `@layout_hint = "frame_major" | "point_major"` 供工具决定是否重排。

### A.1 压缩器降级（规范性）

zstd 在 HDF5 里是**注册过滤器（filter id 32015）而非内置过滤器**：没装 `hdf5plugin`（或等效的 HDF5 插件目录）的读取器打不开 zstd 压缩的数据集。因此：

1. 上表的 zstd 是**默认值而非硬性要求**。写入器**可以**降级到 HDF5 内置的 gzip 或不压缩。
2. 无论用哪种，`@compression` **必须**如实写明实际编码（`"zstd:3+shuffle"` / `"gzip:4+shuffle"` / `"none"`）。读取器靠这个属性判断自己能不能解，而不是靠猜。
3. 面向公开分发的一致性样例（`spec/conformance/`）**应当**只用内置过滤器，保证任何一个原装 h5py 都能读 —— 「第三方不依赖 HL3 软件也能读」如果还要求先装对插件，就不成立了。
4. 元素数很少的数据集**可以**不分块、不压缩：HDF5 的分块与过滤器元数据开销会超过收益。

同理，`@hash_algo` 的降级规则见 §2.5。**一切降级都写进文件，不写进口头约定。**

## 附录 B：`config` JSON 规范化

`@config_hash` 的可复现性依赖规范化规则：

1. 对象键按 Unicode 码点升序排序。
2. 无多余空白（`separators=(',', ':')`）。
3. 浮点用 17 位有效数字 `repr`（`%.17g`），保证往返无损。
4. UTF-8，不转义非 ASCII。
5. 不含 `null` 值的键（省略而非写 `null`）。
6. 数组顺序有意义，不排序。

哈希对象为规范化后的 UTF-8 字节序列。

## 附录 C：Zarr v3 映射（`.hl3z`）

同一逻辑路径树，差异仅三处：

| 方面 | HDF5 | Zarr v3 |
|------|------|---------|
| group / dataset | HDF5 group / dataset | Zarr group / array |
| attribute | HDF5 attribute | `zarr.json` 的 `attributes` |
| 变长字符串 | `H5T_VARIABLE` | `string` dtype，或 JSON 侧车 `<name>.strings.json` |
| 小分块 | 无需特殊处理 | **必须**用 sharding codec 聚合，避免对象存储小文件风暴 |
| 压缩器 | `zstd:L+shuffle` | `blosc(cname=zstd, clevel=L, shuffle=SHUFFLE)` |

`hl3 convert a.hl3 a.hl3z` 与反向转换**必须**无损：往返后 `hl3 diff` 无差异。

## 附录 D：最小读取示例（纯 h5py，无需 HL3 软件）

```python
import h5py, numpy as np

with h5py.File("bending.hl3", "r") as f:
    assert f.attrs["hl3_schema_version"].startswith("1.")
    ana = f["/analyses/ana_01"]

    u     = ana["fields/u"][:]          # (F, P) float32
    v     = ana["fields/v"][:]
    flags = ana["fields/flags"][:]      # (F, P) uint32
    xy    = ana["grid/ref_xy"][:]       # (P, 2) float64

    MASKED, OUTLIER, FILL, CONVERGED = 0x2, 0x100, 0x200, 0x1
    good = ((flags & (MASKED | OUTLIER | FILL)) == 0) & ((flags & CONVERGED) != 0)

    exx = ana["strain/default/exx"][:]
    print("VSG =", ana["strain/default"].attrs["vsg_px"], "px")
    print("位移单位 =", ana["fields/u"].attrs["space"])   # "px" 或 "m"
    print("有效点均值 exx =", np.nanmean(np.where(good, exx, np.nan), axis=1))
```

约 20 行读出全部关键结果，且单位与有效性判据都从文件本身取得 —— 这就是 P1 与 P2 的实际含义。

`hl3.io.hdf5_schema` 把这段示例里的魔数换成了具名常量，但**不取代它**：附录 D 必须永远可以脱离 HL3 代码库单独粘贴运行，这是「格式公开」的最后一道保险。

---

## 14. 修订记录

`1.0.0-draft` → `1.0.0-draft.2`（Round 2 / R2-O3）。以下修订**全部是澄清与补充，没有一条反转 R1 的语义决定**；`flags` 位分配、路径树、必填/应当级别、坐标与单位约定一律未动。

| # | 条款 | 修订 | 起因 |
|---|------|------|------|
| A-1 | §3 `@hl3_schema_version` | 原文写「必须 `"1.0.0"`」，与文首「版本 `1.0.0-draft`」及 §12.1「冻结前一律 `1.0.0-draft.N`」自相矛盾。改为：冻结前 `"1.0.0-draft.N"`，冻结后 `"1.0.0"` | 内部不一致；照原文写文件会让 §12.1 立即失效 |
| A-2 | §2.5、§3 `@hash_algo` | 增列 `blake2b-256` 为合法降级值，并规定算法不同的哈希「不可比」而非「不匹配」 | BLAKE3 不在任何语言标准库内；硬性要求会让零依赖参考读取器无法实现 |
| A-3 | §3 `@uuid` | 由「必须 UUIDv4」放宽为「RFC 4122 UUID，应当 v4，确定性写入器可用 v5」 | 逐位可复现（铁律 L4）与随机 v4 直接冲突：同输入两次运行会得到不同 `@uuid`。一致性样例必须可逐位比对 |
| A-4 | 附录 A.1（新增） | zstd 由硬性默认改为「默认值，可降级为 gzip 或不压缩，但 `@compression` 必须如实写明」；一致性样例应当只用内置过滤器 | zstd 是 HDF5 注册过滤器不是内置过滤器，原装 h5py 打不开；不修正则 §12 样例集事实上不可读 |
| A-5 | §13（新增） | 规范条款 ↔ 参考实现符号的映射表、依赖分层说明、合成算例定义 | R1 承诺了「参考实现 + 一致性套件」，Round 2 把它落到具体符号上，避免散文与代码各自漂移 |
| A-6 | 文首、附录 D | 补 `SPDX-License-Identifier: CC-BY-4.0`；声明参考实现不取代附录 D 的独立可运行示例 | ADR-LIC-001 执行规则 1 |
| A-7 | §12（Round 3 / R3-O3） | 在 `hl3 validate` 等命令块后补「实现现状」段：命令行、`diff`、`repack` 与 `spec/conformance/` 样例集尚未实现，今天可用的只有 `validate_file()` 与 `python -m hl3.io.hdf5_schema selftest`；样例分类是目标集合，并注明现有 23 个测试实际覆盖到哪几类 | 散文用现在时描述未落地的 CLI，读者会误以为可用；本条只加实现现状说明，**未改动任何规范性要求**，版本号仍为 `1.0.0-draft.2` |

**仍然悬空、交给 Round 3 的条款**（本轮未擅自定稿）：

1. §6 标定组、§7 内嵌图像、§8.1 模拟量通道、`/derived`、`/thumbnails` 只有散文与常量，尚无参考写入器覆盖 —— 一致性样例目前只覆盖 2D 完整用例一条。
2. 附录 C 的 Zarr v3 映射尚无实现，`hl3 convert` 的无损往返未验证。
3. §12.1 的四条冻结条件一条都未满足（尤其是「至少一个外部独立读取器」与 iDICs Challenge 跑通），因此**不得**去掉 `-draft` 后缀。
