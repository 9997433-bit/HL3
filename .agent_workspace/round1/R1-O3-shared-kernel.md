ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R1-O3 共享内核 / 数据模型 / API 设计

> 子代理：R1-O3（opus-fast）· Round 1 · 主攻「HL3-2D 与 HL3-3D 共用的地基」
> 约束遵守：本文全部基于公开文献、开源实现与通用工程实践设计，**未做任何 VIC 逆向工程**，不含任何专有实现细节。

---

## 0. 设计立场（先定调，再定接口）

HL3-2D 与 HL3-3D 不是两个产品，而是**同一内核的两种配置**。2D 是「相机数 = 1、标定退化为像素-物理比例尺、位移场为 (u,v)」的特例；3D 是「相机数 ≥ 2、完整 SE(3) 标定、位移场为 (u,v,w) 且带形貌 (X,Y,Z)」。任何在 2D 侧写死的假设都会在 3D 侧变成技术债，因此本设计强制以下五条铁律：

| # | 铁律 | 为什么 |
|---|------|--------|
| L1 | **维度中立**：内核数据结构不区分 2D/3D，靠 `dim` 与 `camera_count` 参数化 | 避免两套代码分叉，避免 2D/3D 结果不一致 |
| L2 | **Python 优先**：GUI 只是命令总线的一个客户端；每个 GUI 动作先有可序列化命令，再有按钮 | 对标产品的 Python 扩展是后加的；我们反过来 |
| L3 | **格式公开**：文件 schema 是带版本号的公开规范 + 参考读取器 + 一致性测试套件 | 闭源相关器无法计量溯源，这是最大的可攻击点 |
| L4 | **确定性可复现**：同一输入 + 同一配置 → 逐位相同结果，与线程数、调度、后端无关 | 计量级软件的底线；也是 CI 回归的前提 |
| L5 | **不确定度是一等公民**：不是插件、不是后处理，是与位移场同生命周期的字段 | iDICs GPG 与 MatchID 的叙事方向，也是"超过"的量化抓手 |

命名空间：C++ `hl3::`，Python `hl3`，文件扩展名 `.hl3`（HDF5 容器）/ `.hl3z`（Zarr 目录或对象存储前缀）。

---

## 1. 数据模型

### 1.1 实体关系总览

```
Project ─┬─ CoordinateSystemGraph   (坐标系有向图，边 = SE(3)+scale)
         ├─ UnitPolicy              (单位策略与显示偏好)
         ├─ Camera[]                (物理/逻辑相机)
         ├─ Calibration[]           (相机组标定，含协方差与残差)
         ├─ Sequence[]  ────┬─ Frame[]           (帧索引/时标/触发)
         │                  └─ ImageStream[cam]  (内嵌或外链图像)
         ├─ AnalogChannel[]         (模拟量时序 + 帧对齐映射)
         ├─ AOI[]                   (感兴趣域几何 + 种子 + 掩膜)
         ├─ Analysis[] ─────┬─ SubsetGrid        (测点几何与拓扑)
         │                  ├─ DisplacementField (逐帧位移/形函数参数/诊断)
         │                  ├─ StrainField[]     (可多套平滑配置并存)
         │                  ├─ UncertaintyField  (与上述字段同形)
         │                  └─ Diagnostics       (性能/收敛/环境指纹)
         ├─ DerivedVariable[]       (用户自定义公式，可缓存)
         └─ Provenance              (只追加的溯源日志)
```

关键结构决策：**列式 SoA（Structure-of-Arrays）**，不是 `struct Point { double x,y,u,v,exx; }` 的 AoS。理由：SIMD 友好、HDF5/Zarr 直接映射、零拷贝暴露给 NumPy、按需读取单个变量而不必反序列化整条记录。

### 1.2 `Project`

工程是一个**容器 + 索引 + 溯源日志**，不是一个巨型结构体。它持有全部实体的稳定 ID，并保证：

- 每个实体有 `id`（人类可读 slug，工程内唯一，用于脚本引用）与 `uuid`（全局唯一，用于跨工程引用）。
- 实体一律**只追加、不原地改写**：修改一个 Analysis 的配置会产生新的 Analysis（父指针指向旧的），使得任何已发布的结果永远可复现。GUI 的"重新计算"在底层就是新建 + 重定向默认视图。
- 工程可以是**惰性的**：大图像序列可外链（路径 + BLAKE3 摘要），工程文件本身保持在 MB 级。

```cpp
struct ProjectMeta {
  Uuid        uuid;
  std::string name, description, operator_name;
  Timestamp   created_utc, modified_utc;
  SemVer      schema_version;   // 文件 schema 版本
  std::string writer;           // "hl3-kernel 0.1.0 (git:abc1234)"
  std::vector<std::string> tags;
};
```

### 1.3 `Camera`

物理相机的**内参与光学模型**，与标定分离：相机描述"是什么"，标定描述"某次标定测到什么"。同一相机可以有多次标定，允许标定漂移分析。

```cpp
enum class CameraRole  { Primary, Secondary, Auxiliary, Thermal, Reference };
enum class ShutterKind { Global, Rolling };

struct Camera {
  EntityId    id;
  std::string label, vendor, model, serial;
  CameraRole  role;
  int         width_px, height_px;
  double      pixel_pitch_um;    // 方形像素；非方形用 pixel_aspect
  double      pixel_aspect;      // sy/sx，默认 1.0
  int         bit_depth;         // 8/10/12/16
  ShutterKind shutter;
  double      rolling_readout_us;// 卷帘补偿用，Global 时为 0
  std::optional<LensInfo> lens;  // 焦距、光圈、是否远心、工作距离
  EntityId    coord_system;      // 该相机在坐标系图中的节点
};
```

**为什么把 rolling shutter 放进核心而不是插件**：高速 DIC 里卷帘畸变是系统性误差源，公开产品线里普遍靠"买全局快门相机"回避。把它建模进数据结构，才有资格在低成本硬件上做出可信结果 —— 这是差异化点，不是可选项。

### 1.4 `Calibration`

```cpp
enum class DistortionModel {
  None, BrownConrady_k3p2, BrownConrady_k6p2s4,  // 通用
  Division_k1, OpenCVFisheye, Telecentric,        // 特殊光学
  StereoMicroscope,                               // 立体显微（非针孔主光线）
  Generic2DPolynomial                             // 兜底/插件
};

struct CameraCalib {
  EntityId        camera;
  Mat3d           K;                 // [[fx,s,cx],[0,fy,cy],[0,0,1]]
  DistortionModel model;
  std::vector<double> dist;          // 长度由 model 决定
  Rigid3d         pose_in_rig;       // 相机 ← 装置(rig) 坐标系
};

struct Calibration {
  EntityId    id;
  std::string method;                // planar_target_zhang / bundle_adjust / self_calib / imported
  Timestamp   epoch;
  std::vector<CameraCalib> cameras;
  MatXd       covariance;            // 全参数向量协方差 (N_param x N_param)
  std::vector<double> param_order;   // 协方差行列到参数名的映射（存字符串表）
  double      rms_reproj_px;
  Tensor3f    residuals;             // (view, point, 2) 重投影残差，供质量评估
  EntityId    target;                // 标定靶几何
  double      scale_mm_per_px;       // 仅 2D 退化标定使用
};
```

`covariance` 是**必填而非可选**：不确定度传播（第 1.10 节）需要它，而绝大多数开源实现只给 RMS 一个标量。给出完整协方差 + 残差张量，是"比公开对标产品更可审计"的具体动作。

### 1.5 `Sequence`

```cpp
enum class ImageStorage { Embedded, ExternalFiles, LiveStream };

struct Sequence {
  EntityId               id;
  std::string            label;
  int64_t                frame_count;
  double                 fps_nominal;
  std::vector<int64_t>   frame_index;    // 采集端原始索引（可不连续）
  std::vector<double>    timestamp_s;    // 单调采集时钟
  std::vector<int64_t>   trigger_id;     // 与模拟量/外部触发对齐
  std::vector<Roi2i>     roi_offset;     // 传感器 ROI 漂移（高速相机常见）
  std::map<EntityId, ImageStream> streams;  // camera_id -> 图像流
};

struct ImageStream {
  ImageStorage storage;
  std::string  format;                   // tiff/png/raw16/mraw/cine/...
  std::vector<std::string> paths;        // ExternalFiles 时
  std::vector<Blake3Hash>  hashes;       // 完整性校验，溯源必备
  DatasetRef   embedded;                 // Embedded 时指向 HDF5 dataset
};
```

**参考帧不是序列属性，而是分析属性**（见 1.8）。这允许同一序列跑「固定参考」「增量更新」「多参考分段」三种策略并排比较，而不必复制序列。

### 1.6 `AOI`

AOI 是**几何 + 语义**，不是一张位图。位图是它的一种缓存表示。

```cpp
enum class AoiMode { Static, TrackedRigid, TrackedDeformable, PerFrame };

struct Aoi {
  EntityId              id;
  std::string           label;
  EntityId              sequence;
  EntityId              reference_camera;
  AoiMode               mode;
  std::vector<Polygon2d> outers;   // 支持多连通域
  std::vector<Polygon2d> holes;
  std::vector<Seed>     seeds;     // 起算点：位置 + 可选初值 + 可选跨相机对应
  std::optional<BitMask> mask;     // 逐像素细掩膜（如遮挡、反光）
  std::vector<uint8_t>  valid_frames;  // 帧级启用/禁用
};

struct Seed {
  Vec2d  xy;
  std::optional<ShapeParams> initial_guess;  // 允许手动/自动起点
  bool   auto_detected;
  double confidence;
};
```

`AoiMode::TrackedDeformable` 覆盖大变形时 AOI 需随试样走的情况（拉伸至颈缩、软材料）。把它做成模式枚举而不是"重画 AOI"的手工流程，是可脚本化的前提。

### 1.7 `SubsetGrid`

统一表达三类离散化，这样局部 DIC、全局 FE-DIC、散点/标记点跟踪共用下游全部管线（应变、可视化、导出）。

```cpp
enum class GridKind      { Regular, Scattered, FeMesh, MarkerSet };
enum class ShapeFunction { Rigid, Affine, Quadratic, Irregular /*插件*/ };

struct SubsetGrid {
  EntityId              id;
  GridKind              kind;
  int32_t               subset_px;      // 局部 DIC 子区边长（奇数）
  int32_t               step_px;        // Regular 时的步长
  SubsetWindow          window;         // Square / Circular / Adaptive
  ShapeFunction         shape;
  std::vector<PointId>  point_id;       // 稳定 ID，跨帧/跨分析可追踪
  MatXd                 ref_xy;         // (P,2) 参考图像坐标（参考相机）
  std::vector<uint8_t>  valid;          // (P,)
  CsrTopology           cells;          // FeMesh/可视化：单元 → 节点 CSR
  CsrTopology           neighbors;      // 应变算子/平滑用邻接（CSR，不是定长 k）
};
```

用 **CSR 邻接**而不是定长 `k` 邻居数组：边界点、非规则网格、自适应细化时邻居数天然不等长，定长会引入边界偏差 —— 这正是虚拟应变片在边界处失真的常见来源之一。

### 1.8 `DisplacementField`

```cpp
struct AnalysisInputs {
  EntityId sequence, aoi, calibration;
  ReferencePolicy ref_policy;   // Fixed{frame} | Incremental | Multi{breakpoints} | Auto
};

// 逐帧 × 逐点的列式字段集合（(F,P) 二维数组，行主序，帧优先）
struct DisplacementField {
  Field2f u, v;                 // 必有
  std::optional<Field2f> w;     // 3D
  std::optional<Field2f> X, Y, Z;      // 3D 当前形貌（世界系）
  std::optional<Field3f> disparity;    // (F,P,2) 立体视差，供诊断
  Field3f  p_shape;             // (F,P,Np) 形函数参数：du/dx, du/dy, ...
  Field2f  zncc;                // 相关质量 [-1,1]
  Field2f  sigma;               // ZNSSD 残差 / 匹配代价
  Field2u16 iters;
  Field2u32 flags;              // 位域：见下
};
```

`flags` 位域（公开定义、跨版本稳定）：

| bit | 名称 | 含义 |
|-----|------|------|
| 0 | `CONVERGED` | ICGN 达到收敛判据 |
| 1 | `MASKED` | 被 AOI/掩膜排除 |
| 2 | `SEEDED` | 该点为种子或由种子直接传播 |
| 3 | `EXTRAPOLATED` | 初值来自外推而非邻居 |
| 4 | `EDGE_CLAMPED` | 子区触及图像/AOI 边界 |
| 5 | `LOW_CONTRAST` | 子区梯度能量低于阈值 |
| 6 | `EPIPOLAR_REJECT` | 立体：极线残差超限 |
| 7 | `TRIANGULATION_ILL` | 立体：三角化条件数差 |
| 8 | `OUTLIER_FILTERED` | 被后处理判为离群 |
| 9 | `INTERPOLATED_FILL` | 值来自空洞填补而非求解 |
| 10 | `GPU_PATH` | 由 GPU 后端求解（用于确定性审计）|

**把"这个值怎么来的"写进数据而不是日志**，是让下游敢用的关键。任何统计、任何图，都能按 flags 过滤并说明过滤规则。

### 1.9 `StrainField`

一个 Analysis 下可以挂**多套** StrainField（不同平滑窗口/不同张量），因为 VSG 尺寸是需要扫描而不是拍脑袋定的量。

```cpp
enum class StrainTensor { Engineering, GreenLagrange, EulerAlmansi, Hencky, Logarithmic };
enum class StrainMethod { LocalPlaneFit, SavitzkyGolay, FeGradient, SplineGlobal };

struct StrainField {
  EntityId      id;
  StrainTensor  tensor;
  StrainMethod  method;
  int32_t       window_pts;     // 平滑窗内测点数（奇数）
  double        vsg_px;         // 等效虚拟应变片尺寸（像素），由 window/step/subset 推得
  double        vsg_mm;         // 物理尺寸（有标定时）
  // 面内
  Field2f exx, eyy, exy;
  Field2f e1, e2, theta_p, gamma_max, von_mises;
  // 3D 曲面附加
  std::optional<Field2f> ezz_assumed;  // 由不可压/塑性假设推得，带 @assumption 属性
  std::optional<Field2f> curvature_k1, curvature_k2;
  std::optional<Field3f> surface_normal;  // (F,P,3)
};
```

`vsg_px` 与 `vsg_mm` **必须随场一起存**。空间分辨率与噪声的权衡是 DIC 结果最容易被误读的地方；把它做成数据而不是文档，报告里就无法省略。

### 1.10 `Uncertainty`

```cpp
enum class UqMethod {
  Propagated,          // 匹配 Hessian + 图像噪声 + 标定协方差 一阶传播
  Bootstrap,           // 子区重采样，需确定性 RNG
  RepeatStatic,        // 静态重复帧统计（噪声底板实测）
  SyntheticCalibrated  // 合成散斑标定后的经验模型
};

struct UncertaintyField {
  UqMethod method;
  Field2f  u_std, v_std;
  std::optional<Field2f> w_std;
  std::optional<Field3f> cov_uvw;   // (F,P,6) 上三角：Cuu,Cuv,Cuw,Cvv,Cvw,Cww
  std::map<std::string, Field2f> strain_std;   // 与 StrainField 变量同名
  // 全局标量
  double sigma_u_px_floor, sigma_v_px_floor;   // 实测噪声底板
  double calib_contrib_frac;                   // 标定不确定度占比
  double image_noise_sigma_dn;                 // 图像噪声估计（DN）
};
```

不确定度来源三分解 **（图像噪声 / 匹配病态 / 标定误差）**并分别可查，这是超过"只给一个相关系数"的实质内容。

### 1.11 `AnalogChannels`

```cpp
struct AnalogChannel {
  EntityId    id;
  std::string label, unit;      // 例如 "load", "kN"
  double      sample_rate_hz, gain, offset;
  std::vector<double> time_s;   // (M,) 与序列同一时钟域，或给出 clock_offset
  std::vector<double> value;    // (M,)
  double      clock_offset_s;   // 通道时钟 → 序列时钟
  SyncMethod  sync;             // HardwareTrigger | TimestampMatch | ManualOffset
  std::vector<int64_t> frame_map;  // (N,) 每帧对应的样本下标，-1 = 无对应
};
```

`frame_map` 是**预计算并持久化**的，不是每次读取时插值：同步策略本身是需要被审计的决定，不能是隐式行为。同一通道可以带多套同步方案并标注哪套在用。

### 1.12 派生变量（`DerivedVariable`）

见第 5.3 节。数据侧只需要：名称、表达式、单位、依赖列表、求值域（点/帧/全局）、可选缓存数组、`expr_hash`。

---

## 2. 文件格式

### 2.1 策略：用"公开 schema"当武器

对标产品的相关器与文件格式是封闭的，这意味着第三方无法独立验证其结果，也无法把数据无损搬走。我们的反制不是"我们也支持 HDF5"，而是：

1. **规范先行**：`spec/hl3-schema/1.0/` 目录下发布 JSON Schema + 散文规范（`docs/schema-hdf5.md`），以 CC-BY-4.0 授权，独立于内核代码的许可证。
2. **参考实现**：`python/src/hl3/io_ref/` 是**纯 Python + h5py**、零 C++ 依赖的只读参考读取器，一百来行能读全部字段。任何人可以在没有我们软件的情况下读自己的数据。
3. **一致性测试套件**：`spec/conformance/` 提供数十个小体积 `.hl3` 样例（含合法/非法边界用例）与期望解析结果，任何实现（包括别人的）都能自测。
4. **验证器**：`hl3 validate file.hl3 --strict` 给出逐条 schema 违规。
5. **语义化版本 + 前向兼容规则**：次版本号只增字段；读取器**必须保留未知 group/attribute 并在改写时原样写回**（这条写进规范，避免生态碎片）。
6. **双容器同构**：HDF5 与 Zarr v3 使用**同一逻辑路径树**，`hl3 convert a.hl3 a.hl3z` 是无损双向的。

### 2.2 HDF5 布局（摘要，完整版见 `docs/schema-hdf5.md`）

```
/                       @hl3_schema_version @hl3_writer @uuid @created_utc
/project/               @name @description @operator
  units/                @length @time @strain_display @angle @force
  coordinate_systems/<cs_id>/   @kind @parent   transform(4,4 f64)  [covariance(6,6 f64)]
/cameras/<cam_id>/      @label @serial @role @width_px @height_px @pixel_pitch_um @bit_depth
                        @shutter @rolling_readout_us
/calibrations/<cal_id>/ @method @epoch @rms_reproj_px
  cameras/<cam_id>/     K(3,3 f64)  dist(nd f64)@model  R(3,3 f64)  t(3 f64)
  covariance(Np,Np f64)   param_names(Np vlen-str)
  residuals(V,Q,2 f32)    target/points(Q,3 f64)  target/ids(Q i64)
/sequences/<seq_id>/    @label @frame_count @fps_nominal
  frames/               index(N i64) timestamp_s(N f64) trigger_id(N i64) roi_offset(N,2 i32)
  images/<cam_id>/      data(N,H,W[,C] u8|u16)   |   paths(N vlen-str) hashes(N,32 u8)
                        @storage @format @compression
/analog/<chan_id>/      @label @unit @sample_rate_hz @sync @clock_offset_s
                        time_s(M f64) value(M f64) frame_map(N i64)
/aois/<aoi_id>/         @label @sequence @mode
  polygons/<k>/vertices(V,2 f64) @role={outer|hole}
  seeds/xy(S,2 f64) seeds/auto(S u8) seeds/confidence(S f32)
  mask(H,W u8)  valid_frames(N u8)
/analyses/<ana_id>/     @label @type={2d|stereo|multiview} @kernel_version @git_sha
                        @config_hash @input_hash @parent_analysis
  config                (标量 vlen-str，规范化 JSON)
  grid/                 @kind @subset_px @step_px @shape_function
                        point_id(P u64) ref_xy(P,2 f64) valid(P u8)
                        cells/offsets(C+1 i64) cells/nodes(* i64)
                        neighbors/offsets(P+1 i64) neighbors/idx(* i32)
  frames/index(F i64)
  fields/               u(F,P f32) v(F,P f32) [w] [X Y Z] [disparity(F,P,2)]
                        p_shape(F,P,Np f32) zncc(F,P f32) sigma(F,P f32)
                        iters(F,P u16) flags(F,P u32)
  strain/<strain_id>/   @tensor @method @window_pts @vsg_px @vsg_mm
                        exx eyy exy e1 e2 theta_p gamma_max von_mises  (各 F,P f32)
  uncertainty/          @method  u_std v_std [w_std] cov_uvw(F,P,6 f32)
                        strain_std/<name>(F,P f32)   @sigma_u_px_floor ...
  diagnostics/          @solve_wall_s @threads @device @rng_seed @deterministic
                        per_frame_time_s(F f64)
/derived/<var_id>/      @name @expr @unit @domain  depends_on(vlen-str)  value(F,P f32)
/provenance/            log(vlen-str, 只追加 JSONL)   inputs/hashes(vlen-str)
/thumbnails/<seq_id>/   data(N,h,w u8)
```

**分块与压缩默认值**（可覆盖，写入 `@chunk`/`@compression` 属性）：

| 数据集类别 | 分块 | 压缩 | 理由 |
|-----------|------|------|------|
| `fields/*` (F,P) | `(min(F,16), min(P,4096))` | zstd-3 + shuffle | 兼顾"整帧渲染"与"单点时程"两种访问 |
| `fields/p_shape` (F,P,Np) | `(min(F,8), min(P,2048), Np)` | zstd-3 + shuffle | 体积大、访问少 |
| `images/data` | `(1, H, W)` | zstd-1（无损）| 逐帧解码；有损编码走外链 |
| `analog/*` | `(min(M,65536),)` | zstd-3 | 长一维 |

另提供 `@layout_hint = "frame_major" | "point_major"`，`hl3 repack` 可按访问模式重排（虚拟应变片时程分析用 point-major 可快一个量级）。

### 2.3 Zarr v3 映射

同一路径树，`group` → Zarr group，`dataset` → Zarr array，HDF5 attribute → Zarr `attributes`。差异只有三处，写进规范附录：

1. 变长字符串在 Zarr 用 `string` 数据类型或 JSON 侧车。
2. 用 **sharding codec** 把小分块聚合，避免对象存储上的小文件风暴。
3. 压缩器映射：`zstd` ↔ `blosc2(zstd)`，规范给出等价表。

目标场景：S3/MinIO 上的大批量实验、集群并行写入、云端可视化直读，这是单文件 HDF5 做不到的。

### 2.4 导出格式

| 格式 | 用途 | 关键点 |
|------|------|--------|
| **CSV / TSV** | 交换、Excel、快速检查 | 列名 = 变量注册表名；头部带 `# hl3-export` 元数据块（单位、坐标系、AOI、配置哈希），使 CSV 也可溯源 |
| **VTK / VTU / VTP** (XML, 二进制附加) | ParaView / VisIt | 规则网格 → `ImageData`/`StructuredGrid`；FE 网格 → `UnstructuredGrid`；散点 → `PolyData`。位移作 `Vectors`，应变张量作 6 分量 `Tensors`，不确定度作同名 `_std` 数组。时间序列输出 `.pvd` 集合 |
| **Exodus II** | FEA 闭环（Sierra/Cubit/Abaqus 转换链） | 节点变量 = u/v/w + 不确定度；单元变量 = 应变分量；`time_whole` = 帧时标。与 DIC→FE 验证工作流对接 |
| **glTF 2.0 / PLY / STL** | 形貌与彩色场共享、Web 预览 | 3D 形貌 + 顶点色（场着色）；STL 仅几何 |
| **NetCDF-4 / xarray** | 科学 Python 生态 | 直接由 HDF5 层加维度名导出 |
| **MATLAB `.mat` v7.3** | 存量用户迁移 | 本质是 HDF5，做名字映射即可 |
| **Parquet** | 大规模统计/数据湖 | 长表 (frame, point, var, value) 或宽表两种模式 |

导出全部经由统一的 `IExporter` 插件接口（第 4 节），核心只保证 CSV/VTK/HDF5 三种；Exodus 依赖 SEACAS，作为可选组件编译。

---

## 3. C++ 内核 API 与 pybind11 Python API

### 3.1 分层

```
   ┌─────────────────────────────────────────────────────────┐
   │  apps: hl3-studio (Qt6 GUI) · hl3-cli · hl3-snap · gauge│
   └───────────────┬─────────────────────────┬───────────────┘
                   │  Command (可序列化)      │
   ┌───────────────▼─────────────────────────▼───────────────┐
   │  hl3 Python API  (纯 Python 门面 + numpy/xarray 互操作)  │
   └───────────────────────┬─────────────────────────────────┘
                           │ pybind11
   ┌───────────────────────▼─────────────────────────────────┐
   │  hl3::core  数据模型 / 命令总线 / 单位 / 变量注册表      │
   │  hl3::io    HDF5 / Zarr / 导出                           │
   │  hl3::geom  坐标系图 / 三角化 / 网格                     │
   │  hl3::calib 标定与不确定度传播                           │
   │  hl3::corr  ICGN / FFT-CC / 全局 DIC / 路径策略          │
   │  hl3::strain 应变算子 / 平滑                             │
   │  hl3::uq    不确定度估计                                 │
   │  hl3::compute 线程池 / 设备抽象 / 确定性 RNG             │
   │  hl3::plugin C-ABI 插件宿主                              │
   └─────────────────────────────────────────────────────────┘
```

**GUI 绝不直接调用内核算法**。GUI 构造 `Command`，投递到 `CommandBus`，总线执行并写入命令日志。这个日志同时是：撤销栈、可复现脚本、审计轨迹。"Copy as Python" 与"会话录制为脚本"是同一机制的两个出口。

### 3.2 核心类型与错误处理

```cpp
// include/hl3/core/result.hpp
namespace hl3 {

enum class Status : int32_t {
  Ok = 0, InvalidArgument, NotFound, AlreadyExists, Unsupported,
  NotConverged, NumericalFailure, Canceled, IoError, SchemaViolation,
  PluginError, DeviceError, Internal
};

struct Error {
  Status      code;
  std::string message;      // 面向用户，已本地化键
  std::string context;      // "analyses/ana_02/grid" 之类的定位串
  std::vector<Error> causes;
};

template <class T>
class [[nodiscard]] Result {          // 类 std::expected；内核不抛异常跨模块
 public:
  bool ok() const noexcept;
  T&   value();                       // 非 ok 时 UB，需先判断
  const Error& error() const noexcept;
  template <class F> auto and_then(F&&) -> Result<...>;
};
using Void = Result<std::monostate>;

}  // namespace hl3
```

内核**不跨模块抛异常**（插件边界是 C ABI，异常无法安全穿越）；pybind11 层把 `Error` 翻译成 Python 异常层次 `hl3.HL3Error` → `hl3.NotConvergedError` 等。

### 3.3 字段视图（零拷贝的关键）

```cpp
// include/hl3/core/field.hpp
template <class T>
class FieldView {                     // (F, P) 行主序非拥有视图
 public:
  T* data(); const T* data() const;
  int64_t frames() const; int64_t points() const;
  std::span<T> frame(int64_t f);      // 连续
  T& at(int64_t f, int64_t p);
  Units unit() const;                 // 视图带单位，防止裸数组误用
};

class FieldSet {                      // 名字 → 类型擦除的列
 public:
  Result<FieldView<float>>  f32(std::string_view name);
  Result<FieldView<double>> f64(std::string_view name);
  std::vector<std::string>  names() const;
  Void   add(std::string_view name, DType, Units, int64_t F, int64_t P);
  bool   is_lazy(std::string_view name) const;   // 未从磁盘加载
};
```

`FieldSet` 支持**惰性列**：只有被访问的变量才从 HDF5 读入，配合分块使得"打开 50 GB 工程看一眼载荷曲线"是毫秒级操作。

### 3.4 求解器接口

```cpp
// include/hl3/corr/correlator.hpp
namespace hl3::corr {

struct IcgnParams {
  int32_t  subset_px      = 29;
  int32_t  step_px        = 7;
  ShapeFunction shape     = ShapeFunction::Affine;
  Interpolation interp    = Interpolation::BSpline5;  // Bicubic / BSpline3 / BSpline5
  Criterion criterion     = Criterion::ZNSSD;         // ZNCC / ZNSSD / PSSD
  double   conv_tol       = 1e-5;    // 形函数增量范数（像素）
  int32_t  max_iters      = 50;
  double   zncc_reject    = 0.80;
  PathStrategy path       = PathStrategy::ReliabilityGuided;  // 或 SeedParallel
  bool     deterministic  = true;
};

struct CorrelationRequest {
  const Sequence*    sequence;
  const Aoi*         aoi;
  const SubsetGrid*  grid;
  const Calibration* calibration;    // 2D 可为 nullptr
  ReferencePolicy    ref_policy;
  IcgnParams         params;
  DeviceSelector     device;         // Auto / Cpu / Cuda{idx} / Vulkan{idx}
  uint64_t           rng_seed = 0x484C33ull;
};

struct CorrelationResult {
  FieldSet fields;                   // u, v, [w], p_shape, zncc, sigma, iters, flags
  Diagnostics diag;
};

class ICorrelator {
 public:
  virtual ~ICorrelator() = default;
  virtual std::string_view name() const = 0;
  virtual Capabilities capabilities() const = 0;    // 支持的维度/形函数/后端/是否确定性
  virtual Result<CorrelationResult> solve(const CorrelationRequest&,
                                          ProgressSink&, CancelToken) = 0;
};

Result<std::unique_ptr<ICorrelator>> make_correlator(std::string_view id);

}  // namespace hl3::corr
```

`ProgressSink` + `CancelToken` 出现在**每个**长任务签名里，这样 GUI 进度条、CLI 进度、Python `tqdm`、Jupyter 小部件共用同一机制，而不是 GUI 独有。

```cpp
struct ProgressSink {
  virtual void on_stage(std::string_view stage, int64_t total) = 0;
  virtual void on_tick(int64_t done) = 0;
  virtual void on_message(LogLevel, std::string_view) = 0;
};
class CancelToken { public: bool requested() const noexcept; void request() noexcept; };
```

### 3.5 应变与不确定度

```cpp
// include/hl3/strain/strain.hpp
struct StrainRequest {
  const SubsetGrid* grid;
  const FieldSet*   disp;
  StrainTensor      tensor  = StrainTensor::GreenLagrange;
  StrainMethod      method  = StrainMethod::LocalPlaneFit;
  int32_t           window_pts = 5;
  bool              propagate_uncertainty = true;
  const UncertaintyField* disp_uq = nullptr;
};
Result<StrainResult> compute_strain(const StrainRequest&, ProgressSink&, CancelToken);

double vsg_size_px(int32_t window_pts, int32_t step_px, int32_t subset_px);  // (w-1)*step + subset

// include/hl3/uq/uq.hpp
struct UqRequest {
  UqMethod method = UqMethod::Propagated;
  const CorrelationResult* corr;
  const Calibration*       calib;
  double   image_noise_sigma_dn = 0.0;   // 0 = 自动估计
  int32_t  bootstrap_draws = 200;
  uint64_t rng_seed = 0x484C33ull;
};
Result<UncertaintyField> estimate_uncertainty(const UqRequest&, ProgressSink&, CancelToken);
```

### 3.6 命令总线

```cpp
// include/hl3/core/command.hpp
struct CommandDesc {
  std::string id;                    // "analysis.run"
  std::string python_call;           // "proj.analyses['{ana}'].run()"
  Json        params_schema;         // JSON Schema，GUI 自动生成表单
  bool        mutating, undoable;
};

class ICommand {
 public:
  virtual const CommandDesc& desc() const = 0;
  virtual Void execute(Project&, const Json& params, ProgressSink&, CancelToken) = 0;
  virtual Void undo(Project&) = 0;
  virtual std::string to_python(const Json& params) const = 0;   // ← 脚本化的核心
};

class CommandBus {
 public:
  Void   dispatch(std::string_view id, const Json& params);
  Void   undo(); Void redo();
  std::vector<JournalEntry> journal() const;
  std::string export_script(ScriptDialect = ScriptDialect::Python) const;
};
```

**GUI 的每个按钮都必须注册一个 `ICommand`**；CI 里加一条测试：遍历 GUI 动作表，断言 100% 有对应命令与 `to_python` 实现。这条测试就是 L2 铁律的执行机制。

### 3.7 Python API

绑定层薄，门面层厚：pybind11 只暴露内核对象与零拷贝数组；`hl3` 包用纯 Python 实现符合人体工学的 API、xarray 互操作、绘图与 CLI。这样迭代 API 不必重编 C++。

```python
import hl3
import numpy as np

# ---- 打开 / 新建 --------------------------------------------------------
proj = hl3.open("bending.hl3")                 # 或 hl3.Project.create("new.hl3")

# ---- 数据装载（2D 与 3D 同一套调用）------------------------------------
seq = proj.add_sequence("test01",
                        images={"cam0": sorted(glob("cam0/*.tif")),
                                "cam1": sorted(glob("cam1/*.tif"))},   # 2D 时只给 cam0
                        fps=100.0, link=True)                          # link=True 外链不复制

cal = proj.calibrate(target=hl3.targets.Checkerboard(rows=9, cols=12, pitch_mm=5.0),
                     images={"cam0": cal0, "cam1": cal1},
                     model="brown_conrady_k3p2")
print(cal.rms_reproj_px, cal.covariance.shape)

aoi = proj.add_aoi("gauge", polygon=[(120, 80), (900, 80), (900, 620), (120, 620)],
                   holes=[hole_poly], seeds=[(500, 350)])

# ---- 求解 ---------------------------------------------------------------
ana = proj.new_analysis(
    sequence=seq, aoi=aoi, calibration=cal,
    solver=hl3.solvers.ICGN(subset=29, step=7, shape="affine",
                            interp="bspline5", criterion="znssd"),
    reference=hl3.reference.Fixed(0),
    device="auto")
ana.run(progress=True)                          # 支持 tqdm / Jupyter / 静默

# ---- 后处理 -------------------------------------------------------------
ana.compute_strain(tensor="green_lagrange", window=5, method="local_plane_fit")
ana.estimate_uncertainty(method="propagated")

# ---- 取数：零拷贝 numpy + 带坐标的 xarray -------------------------------
u   = ana.field("u")                    # numpy (F, P) float32 视图，零拷贝
ds  = ana.to_xarray(["u", "v", "exx", "u_std"])     # dims: (frame, point)
img = ana.to_grid("exx", frame=42)      # 规则网格 → (H, W) 带 NaN 掩膜，直接 imshow

# ---- 虚拟应变片 / 引伸计 -------------------------------------------------
vsg  = ana.virtual_gauge(center=(500, 350), size_px=64, variable="eyy")
ext  = ana.extensometer(p0=(200, 350), p1=(800, 350))
load = proj.analog["load"].at_frames(ana.frames)     # 已按 frame_map 对齐

# ---- 自定义变量（与 GUI 公式编辑器同一注册表）----------------------------
proj.variables.define("stress_eq", "E * von_mises / (1 - nu**2)",
                      unit="MPa", constants=dict(E=210e3, nu=0.3))
sig = ana.field("stress_eq")            # 惰性求值 + 缓存

# ---- 导出 ---------------------------------------------------------------
ana.export("out/frame_%04d.vtu", frames="all", variables=["u", "v", "w", "exx", "u_std"])
ana.export("out/summary.csv", reduce="mean", over="point")
ana.export("out/dic.e", format="exodus")

# ---- 批处理 -------------------------------------------------------------
hl3.batch.run("recipe.yaml", workers=8)   # 与 CLI `hl3 batch recipe.yaml` 等价
```

对应 CLI（同一命令总线，参数由 `params_schema` 自动生成）：

```bash
hl3 new bending.hl3
hl3 seq add   bending.hl3 --id test01 --cam cam0=cam0/*.tif --cam cam1=cam1/*.tif --fps 100 --link
hl3 calib     bending.hl3 --target checkerboard:9x12x5.0 --model brown_conrady_k3p2
hl3 run       bending.hl3 --aoi gauge --subset 29 --step 7 --shape affine --device auto
hl3 strain    bending.hl3 --tensor green_lagrange --window 5
hl3 uq        bending.hl3 --method propagated
hl3 export    bending.hl3 --format vtu --out 'out/f_%04d.vtu'
hl3 validate  bending.hl3 --strict
hl3 script    bending.hl3 --export replay.py     # 把工程历史导出为可重跑脚本
```

### 3.8 与 NumPy / xarray 的所有权规则

零拷贝很容易变成悬垂指针。规则写死：

- `ana.field("u")` 返回的 `np.ndarray` 通过 pybind11 `py::capsule` **持有** `Analysis` 的 `shared_ptr`，工程被关闭后数组仍然合法。
- 数组默认 `writeable=False`；写回必须走 `ana.set_field("u", arr)`，触发溯源记录与派生变量失效。
- 惰性列在首次访问时物化；`ana.prefetch(["u","v"])` 可显式批量预取。

---

## 4. 插件 / 扩展系统

### 4.1 扩展点清单

| 接口 | 扩展内容 | 典型第三方用途 |
|------|----------|----------------|
| `IImageSource` | 图像/序列读取、相机驱动 | `.cine`/`.mraw` 高速格式、GenICam 相机、显微镜 |
| `ICorrelator` | 匹配求解器 | 全局 FE-DIC、深度学习种子、DVC |
| `IShapeFunction` | 子区形函数 | 不规则子区、样条形函数 |
| `IInterpolator` | 灰度插值 | 更高阶 B 样条、GPU 纹理插值 |
| `ICalibrationModel` | 畸变/投影模型 | 远心、立体显微、鱼眼、折射介质（水下）|
| `IStrainEstimator` | 位移→应变算子 | 无网格法、正则化微分 |
| `IUncertaintyEstimator` | UQ 方法 | 贝叶斯、蒙特卡洛 |
| `IExporter` / `IImporter` | 格式互通 | Exodus、Abaqus ODB、厂商格式 |
| `IVariableProvider` | 派生量 | 材料模型、损伤指标 |
| `IVisualLayer` | GUI 图层/面板 | 自定义叠加、专用报表 |
| `IAnalogSource` | 模拟量/触发 | DAQ 卡、试验机总线 |
| `ICommand` | 新命令（自动获得 GUI + CLI + Python 三种入口）| 领域专用工作流 |

一个扩展点带来三个入口，是"插件不是二等公民"的具体含义：注册一个 `ICommand` 就自动出现在 GUI 命令面板、CLI 子命令与 Python 门面里。

### 4.2 两条加载通道

**原生插件（C ABI）**。C++ ABI 跨编译器不稳定，所以插件边界是 **C 函数指针结构体**，C++ 侧提供 header-only 包装：

```c
/* include/hl3/plugin/abi.h  —— 纯 C，跨编译器稳定 */
#define HL3_ABI_VERSION 1

typedef struct hl3_status { int32_t code; const char* message; } hl3_status;

typedef struct hl3_correlator_vtable {
  const char* (*name)(void* self);
  uint64_t    (*capabilities)(void* self);
  hl3_status  (*solve)(void* self,
                       const struct hl3_corr_request* req,
                       struct hl3_corr_result*        out,
                       struct hl3_progress*           progress,
                       const volatile int*            cancel_flag);
  void        (*destroy)(void* self);
} hl3_correlator_vtable;

typedef struct hl3_plugin_desc {
  uint32_t    abi_version;        /* 必须 == HL3_ABI_VERSION */
  const char* id;                 /* "org.example.globaldic" 反向域名 */
  const char* version;            /* semver */
  const char* license_spdx;       /* 强制填写，用于许可证审计 */
  uint32_t    determinism;        /* 0=不保证 1=同后端确定 2=跨后端确定 */
  hl3_status  (*register_all)(struct hl3_registry* reg);
} hl3_plugin_desc;

/* 插件唯一导出符号 */
const hl3_plugin_desc* hl3_plugin_entry(void);
```

**Python 插件**。用入口点（`pyproject.toml` 的 `[project.entry-points."hl3.plugins"]`）发现，装饰器注册：

```python
import hl3

@hl3.plugin.correlator(id="org.example.dl_seed", version="0.2.0",
                       license="Apache-2.0", determinism=hl3.Determinism.SAME_BACKEND)
class DeepSeedCorrelator(hl3.plugin.CorrelatorBase):
    capabilities = hl3.Capabilities(dims={2, 3}, shapes={"affine"}, backends={"cpu", "cuda"})

    def solve(self, request, progress, cancel):
        ...
        return hl3.CorrelationResult(u=u, v=v, zncc=zncc, flags=flags)

@hl3.plugin.variable(name="damage_d", unit="1", domain="point")
def damage(ctx):
    return 1.0 - ctx["zncc"] / ctx["zncc"].max(axis=1, keepdims=True)
```

Python 插件在向量化数组层面工作（不是逐点回调），因此性能损失可接受；性能敏感者走原生通道。

### 4.3 清单、能力协商与"计量模式"

每个插件带 `plugin.toml`：

```toml
[plugin]
id = "org.example.globaldic"
version = "0.3.1"
license = "MPL-2.0"
abi = 1
determinism = "cross-backend"
provides = ["correlator", "exporter"]
requires = { hl3 = ">=0.4,<0.6" }
```

内核提供 **`--metrology-mode`**：该模式下拒绝加载 `determinism < cross-backend` 的插件、拒绝未声明许可证的插件、强制写入完整溯源。产出的 `.hl3` 带 `@metrology_certified = true`。这给"结果能不能进报告"一个机器可判定的答案，而不是靠人自觉。

失败隔离：原生插件加载失败/崩溃时，宿主捕获并降级（记录 `provenance` 事件、禁用该插件、继续运行）；可选 `--plugin-isolate` 把不受信插件跑在子进程里，走共享内存传数组。

---

## 5. 坐标系、单位与变量注册表

### 5.1 坐标系

约定必须显式写进文件，否则跨软件对比一定出错：

| 坐标系 | 定义 | 备注 |
|--------|------|------|
| `image[cam]` | 像素坐标 (u, v)，**原点在左上角像素中心 (0,0)**，u 向右，v 向下 | `@pixel_origin = "center"`；另一种 `"corner"` 约定必须显式声明 |
| `sensor[cam]` | 归一化相机坐标 (x, y) = 去畸变后的 (X/Z, Y/Z) | |
| `camera[cam]` | 右手系，**+Z 沿光轴向前，+X 向右，+Y 向下** | 与 OpenCV 一致，写进规范 |
| `rig` | 多相机装置系，默认 = 主相机的 `camera` 系 | |
| `world` | 标定确立的世界系（默认 = 首个标定视图的靶标系）| |
| `specimen` | 用户对齐的试样系（三点/平面拟合/最佳拟合圆柱）| 报告与 FE 对比用 |
| `plot` | 显示系（可翻转 v 轴以符合"y 向上"直觉）| 只影响显示，不影响数据 |

坐标系存成**有向图**，节点是坐标系，边是 `Transform{ Rigid3d pose; double scale; optional<Mat6d> cov; }`。查询 `graph.transform("specimen", "camera[cam1]")` 走 BFS 组合路径，同时组合协方差。无路径时报错而不是默默当作单位阵 —— 这类静默假设是跨软件结果对不上的常见根因。

```cpp
// include/hl3/geom/frames.hpp
class FrameGraph {
 public:
  Void add_frame(std::string_view id, std::string_view parent, const Transform&);
  Result<Transform> transform(std::string_view from, std::string_view to) const;
  Result<Mat6d>     transform_cov(std::string_view from, std::string_view to) const;
  std::vector<std::string> path(std::string_view from, std::string_view to) const;
};
```

**2D 的退化处理**：2D 分析里 `world` 与 `image` 之间只有一个各向同性尺度 `scale_mm_per_px`（可为空 = 结果保持像素单位）。内核不会替用户猜比例尺；未标定时应变仍然可算（无量纲），位移则明确带 `px` 单位。

### 5.2 单位

量纲用 7 维有理指数向量 `(L, M, T, Θ, I, N, J)` 表示，**外加第 8 维伪量纲 `px`**：

```cpp
struct Dimension { std::array<Rational, 8> e; };   // 第 8 位是 px

struct Units {
  Dimension dim;
  double    to_si;          // 该单位 → SI 基本单位的因子
  std::string symbol;       // "mm", "µε", "kN"
};
```

`px` 作为独立量纲的意义：`px → m` 的转换**必须**经过一个带溯源的 `ScaleFactor` 对象（来自标定或用户显式声明），否则编译期/运行期报错。这杜绝了"忘了标定，把像素当毫米发了报告"这一类事故。

存储一律 SI 基本单位（m, s, K, kg）+ 无量纲应变；显示层按 `UnitPolicy` 转换（长度 mm、应变 µε、力 kN 等）。CSV/VTK 导出头部写明单位。应变的 `µε` 只是显示缩放（×1e6），量纲仍是 1。

### 5.3 变量注册表与自定义公式

统一的变量表，内置量与用户公式**同级**：GUI 公式编辑器、Python `proj.variables.define`、插件 `IVariableProvider` 三者写进同一张表。

```cpp
enum class VarDomain { Point,    // (F,P)
                       Frame,    // (F,)
                       Global }; // 标量

struct VariableDef {
  std::string id, display_name, description;
  Units       unit;
  VarDomain   domain;
  std::string expr;                       // 内置量为空
  std::vector<std::string> depends_on;    // 由表达式解析得到，用于失效传播
  bool        cacheable;
  Blake3Hash  expr_hash;
};

class VariableRegistry {
 public:
  Void define(const VariableDef&);
  Result<Units> check(std::string_view expr) const;   // 注册时做量纲检查
  Result<FieldView<float>> evaluate(std::string_view id, EvalContext&) const;
  std::vector<std::string> topo_order() const;        // 依赖拓扑序；检测环
  void invalidate(std::string_view changed_id);       // 级联失效缓存
};
```

表达式语言（不是完整 Python，是可静态分析的受限子集）：

- 算术 `+ - * / **`、比较、`? :`、`and/or/not`。
- 逐元素函数：`sqrt exp log sin cos atan2 abs min max clamp sign hypot`。
- 沿轴归约：`mean(v, axis="point"|"frame")`、`std max min sum percentile`。
- 帧算子：`ref(v)`（参考帧值）、`delta(v)`（相对参考帧）、`diff(v)`（相邻帧差）、`cumsum`。
- 空间算子：`grad_x(v) grad_y(v) laplace(v) smooth(v, w=5)`（用 `SubsetGrid.neighbors` CSR）。
- 掩膜：`where(cond, a, b)`、`valid(v)`。
- 常量与材料参数：`proj.constants["E"]`。

编译为 AST → 量纲检查 → 类型/域检查 → 向量化求值（可选 SIMD 代码生成）。**注册时就报错**（量纲不符、循环依赖、未知变量），而不是求值到一半才炸。表达式与其哈希写进 `.hl3`，任何人可复算。

内置变量至少覆盖：`u v w x y z X0 Y0 Z0 zncc sigma iters flags exx eyy exy ezz e1 e2 theta_p gamma_max von_mises u_std v_std w_std vsg_px time_s frame` 以及全部模拟量通道 `analog.<name>`。

---

## 6. 并行、GPU 边界与确定性

### 6.1 线程池

```cpp
// include/hl3/compute/thread_pool.hpp
class ThreadPool {
 public:
  explicit ThreadPool(int threads = 0);   // 0 = 硬件并发数
  // 确定性 parallel_for：分块划分只依赖 n 与 grain，不依赖线程数
  void parallel_for(int64_t n, int64_t grain,
                    const std::function<void(int64_t begin, int64_t end)>&);
  // 确定性归约：固定二叉树合并顺序 → 与线程数无关的逐位结果
  template <class T, class Map, class Reduce>
  T parallel_reduce(int64_t n, int64_t grain, T init, Map, Reduce);
  int  thread_count() const;
  void set_affinity(AffinityPolicy);      // NUMA 感知
};
```

确定性的两个必要条件：

1. **分块划分与线程数解耦**。块边界由 `(n, grain)` 决定，不由 `n / nthreads` 决定。工作窃取只改变"谁执行哪块"，不改变"分成哪些块"。
2. **归约顺序固定**。按块索引做固定形状的二叉树合并，而非"谁先完成谁先加"。浮点加法不结合，这是唯一能保证逐位可复现的方式。

代价约 2–5% 吞吐（额外的中间缓冲与同步）。给一个 `--fast-reduce` 逃生阀，但计量模式下强制关闭。

### 6.2 GPU 调度边界

边界画在**「一批子区」**这个粒度，不是"一个子区"（启动开销）也不是"整个分析"（无法混合后端）：

```cpp
// include/hl3/compute/device.hpp
enum class Backend { Cpu, Cuda, Hip, VulkanCompute, Metal };

class IComputeDevice {
 public:
  virtual Backend backend() const = 0;
  virtual DeviceInfo info() const = 0;                 // 名称、显存、算力、FP64 支持
  virtual Result<Buffer> alloc(size_t bytes) = 0;
  virtual Void upload(Buffer&, const void*, size_t) = 0;
  virtual Void download(void*, const Buffer&, size_t) = 0;

  // 核心批处理入口 —— 所有后端只需实现这三个
  virtual Void build_interpolant(const ImagePlane&, Interpolation, Buffer& out) = 0;
  virtual Void icgn_batch(const IcgnBatchDesc&, ProgressSink&, CancelToken) = 0;
  virtual Void strain_batch(const StrainBatchDesc&) = 0;

  virtual bool bitwise_matches_cpu() const = 0;        // 一致性自证
};

Result<std::unique_ptr<IComputeDevice>> make_device(DeviceSelector);
```

规则：

- **CPU 实现是规范实现**。任何 GPU 后端必须通过一致性测试：在合成散斑基准上 `max|Δu| < 1e-6 px`、`max|Δe| < 1e-9`。不达标的后端在计量模式下不可用。
- GPU 内 FMA、快速数学、`__fdividef` 一类会破坏一致性的优化默认关闭；开启需显式 `--gpu-fast-math` 并在 `flags` 里打 `GPU_PATH` 位、在 `provenance` 里记录。
- 数据布局在 host 与 device 侧一致（SoA + 32 元素对齐），避免转置开销与"只在 GPU 上对"的布局假设。
- 后备逻辑：GPU 显存不足/设备丢失时自动分批或回落 CPU，**并把回落事件写进溯源**，而不是静默。
- 三个后端优先级：CUDA（成熟生态）→ Vulkan compute（跨厂商、Linux/AMD/Intel 全覆盖，是相对 Windows-only 竞品的实质差异）→ HIP/Metal 后续。

### 6.3 确定性 RNG

绝不用带内部状态的全局 RNG。用**计数器型（counter-based）** Philox4×32-10：

```cpp
// include/hl3/compute/rng.hpp
class DeterministicRng {
 public:
  // 值只取决于 (seed, stream, counter)，与调用顺序、线程、后端全部无关
  static uint64_t bits64(uint64_t seed, uint32_t stream, uint64_t counter);
  static double   uniform01(uint64_t seed, uint32_t stream, uint64_t counter);
  static double   normal(uint64_t seed, uint32_t stream, uint64_t counter);  // Box-Muller，固定分支
};

namespace rng_stream {   // 流 ID 常量表，避免不同用途撞流
  constexpr uint32_t kRansac        = 1;
  constexpr uint32_t kBootstrapUq   = 2;
  constexpr uint32_t kSpeckleSynth  = 3;
  constexpr uint32_t kSeedJitter    = 4;
  constexpr uint32_t kSubsampling   = 5;
}
```

`counter` 取**元素的全局索引**（点 ID、帧号、抽样轮次的组合），于是并行遍历顺序完全不影响结果。RANSAC、bootstrap 不确定度、合成散斑生成、随机子采样全部走这条路。`rng_seed` 写进 `/analyses/<id>/diagnostics`。

### 6.4 三层并行

| 层级 | 粒度 | 机制 | 备注 |
|------|------|------|------|
| 帧间 | 帧 | 线程池 / 多进程 / 集群 | 固定参考策略下帧间无依赖，是最优扩展维度 |
| 点间 | 子区 | 线程池 + SIMD / GPU | 可靠性引导路径有依赖 → 用"种子分区 + 区内引导 + 区间对账"保持可并行且确定 |
| 点内 | Hessian/插值 | SIMD (AVX2/AVX-512/NEON) | 通过 `std::experimental::simd` 或 xsimd 抽象 |

可靠性引导（RG）与并行天然冲突。解法：把 AOI 按种子做**确定性区域分解**（分解只依赖几何与种子位置，不依赖运行时），区内串行引导、区间并行，边界点用双向对账 + 固定优先级裁决。这样既保留 RG 的鲁棒性，又保留确定性与可扩展性。

集群/批处理层：`hl3 batch` 支持按帧区间切分投递到多机，结果按 Zarr 分片并行写入，最后 `hl3 merge` 合并。

---

## 7. 建议的 monorepo 目录树

```
hl3/
├─ CMakeLists.txt                  # 顶层，选项：HL3_WITH_CUDA / VULKAN / QT / EXODUS / PYTHON
├─ CMakePresets.json               # linux-gcc / linux-clang / windows-msvc / macos / ci-asan
├─ vcpkg.json                      # 依赖清单（可与 conanfile.py 并存）
├─ pyproject.toml                  # scikit-build-core 构建 wheel
├─ LICENSE                         # 内核：Apache-2.0（暂定，Round 2 定论）
├─ LICENSE-SPEC                    # 规范：CC-BY-4.0，独立授权
├─ CHANGELOG.md
│
├─ spec/                           # ★ 公开规范（可独立于代码分发）
│  ├─ hl3-schema/1.0/
│  │  ├─ project.schema.json
│  │  ├─ analysis.schema.json
│  │  ├─ calibration.schema.json
│  │  └─ variables.schema.json
│  ├─ conformance/                 # 小体积样例 .hl3 + 期望解析 JSON（含非法用例）
│  └─ CHANGES.md                   # schema 版本变更与兼容性声明
│
├─ docs/
│  ├─ schema-hdf5.md               # ★ 本轮附带产出
│  ├─ coordinate-systems.md
│  ├─ units-and-variables.md
│  ├─ plugin-abi.md
│  ├─ determinism.md
│  ├─ python-api/                  # sphinx / mkdocs
│  └─ adr/                         # 架构决策记录 ADR-0001...
│
├─ cpp/
│  ├─ include/hl3/
│  │  ├─ core/      result.hpp field.hpp project.hpp entity.hpp command.hpp
│  │  │             units.hpp variables.hpp progress.hpp log.hpp
│  │  ├─ io/        hdf5.hpp zarr.hpp csv.hpp vtk.hpp exodus.hpp image_io.hpp
│  │  ├─ geom/      frames.hpp transform.hpp mesh.hpp triangulate.hpp polygon.hpp
│  │  ├─ calib/     model.hpp target.hpp bundle.hpp stereo.hpp uncertainty.hpp
│  │  ├─ corr/      correlator.hpp icgn.hpp fftcc.hpp global_fe.hpp
│  │  │             interpolate.hpp criterion.hpp path.hpp stereo_match.hpp
│  │  ├─ strain/    strain.hpp smoothing.hpp vsg.hpp
│  │  ├─ uq/        uq.hpp propagate.hpp bootstrap.hpp noise_floor.hpp
│  │  ├─ compute/   thread_pool.hpp device.hpp rng.hpp simd.hpp buffer.hpp
│  │  └─ plugin/    abi.h registry.hpp host.hpp cxx_wrapper.hpp
│  ├─ src/                         # 与 include 镜像的实现
│  └─ tests/
│     ├─ unit/                     # Catch2 / GoogleTest
│     ├─ golden/                   # 逐位回归基线
│     └─ determinism/              # 变线程数/变后端一致性
│
├─ gpu/
│  ├─ cuda/         icgn_kernels.cu interp_kernels.cu strain_kernels.cu
│  ├─ vulkan/       *.comp (GLSL) + SPIR-V 构建规则
│  ├─ hip/
│  └─ conformance/  与 CPU 逐位对拍的测试
│
├─ python/
│  ├─ bindings/     module.cpp core_bind.cpp corr_bind.cpp io_bind.cpp
│  ├─ src/hl3/
│  │  ├─ __init__.py  project.py analysis.py sequence.py calibration.py aoi.py
│  │  ├─ solvers.py reference.py targets.py variables.py units.py
│  │  ├─ batch.py cli.py plugin.py
│  │  ├─ viz/        plot2d.py plot3d.py report.py templates/
│  │  ├─ io_ref/     ★ 纯 h5py 参考读取器（零 C++ 依赖）
│  │  └─ interop/    xarray_.py pandas_.py paraview_.py matlab_.py
│  └─ tests/
│
├─ apps/
│  ├─ hl3-cli/                     # 统一 CLI（命令由 CommandBus 自动暴露）
│  ├─ hl3-studio/                  # Qt6 GUI，2D/3D 同一可执行文件，按工程类型切换视图
│  │  ├─ src/  views/ panels/ commands/ theme/
│  │  └─ tests/gui_command_coverage/   # ★ 断言每个 GUI 动作都有 Python 等价
│  ├─ hl3-snap/                    # 采集（GenICam/Harvester + 厂商 SDK 适配）
│  └─ hl3-gauge/                   # 实时虚拟应变片 / 闭环输出
│
├─ plugins/
│  ├─ example-correlator-cpp/
│  ├─ example-variable-python/
│  ├─ camera-genicam/
│  ├─ export-exodus/
│  └─ import-fea/                  # Abaqus/Ansys 结果导入用于 DIC-FE 对比
│
├─ data/
│  ├─ synthetic/                   # 合成散斑生成配方（确定性种子）
│  ├─ calib-targets/               # 标定靶定义
│  └─ golden/                      # 回归基线（LFS 或按需下载）
│
├─ benchmarks/
│  ├─ throughput/  accuracy/  scaling/
│  └─ report/                      # 自动生成对比报告
│
├─ ci/
│  ├─ github/  workflows/*.yml
│  ├─ docker/  linux-build.Dockerfile
│  └─ scripts/ check_gui_command_parity.py  check_schema_compat.py
│
└─ tools/
   ├─ hl3-repack/  hl3-validate/  hl3-diff/     # 小工具
   └─ codegen/     variables_table.py units_table.py   # 由单一真源生成 C++/Python/文档
```

`tools/codegen/` 很关键：变量表、单位表、flags 位域、错误码在**一个 YAML 真源**里定义，生成 C++ header、Python 常量、JSON Schema 与文档表格。三处手写同一张表必然漂移。

---

## 8. 最小接口速写汇总

前面各节已给出主要签名。这里补三个还没出现、但对"两款产品共用一套地基"最关键的接口。

### 8.1 统一分析入口（2D/3D 同一签名）

```cpp
// include/hl3/core/analysis.hpp
namespace hl3 {

enum class AnalysisType { Planar2D, Stereo3D, MultiView3D };

struct AnalysisSpec {
  AnalysisType      type;
  AnalysisInputs    inputs;          // sequence / aoi / calibration / ref_policy
  std::string       correlator_id = "hl3.icgn";
  Json              correlator_params;
  std::optional<StrainRequest> strain;
  std::optional<UqRequest>     uq;
  DeviceSelector    device;
  uint64_t          rng_seed = 0x484C33ull;
  bool              metrology_mode = false;
};

class Analysis {
 public:
  const EntityId& id() const;
  AnalysisType    type() const;
  Blake3Hash      config_hash() const;   // 配置指纹，用于缓存与复现
  Blake3Hash      input_hash()  const;   // 输入图像+标定指纹

  Void run(ProgressSink&, CancelToken);
  Void run_frames(std::span<const int64_t>, ProgressSink&, CancelToken);  // 增量/重算子集

  const SubsetGrid&  grid()   const;
  FieldSet&          fields();
  Result<StrainField&>      strain(std::string_view id = "default");
  Result<UncertaintyField&> uncertainty();
  const Diagnostics& diagnostics() const;
};

// 工程级：注意 2D 与 3D 是同一函数，靠 spec.type 分派
Result<Analysis*> create_analysis(Project&, const AnalysisSpec&);

}  // namespace hl3
```

### 8.2 立体扩展点（3D 专属能力挂在共享结构上，而非分叉）

```cpp
// include/hl3/corr/stereo_match.hpp
namespace hl3::corr {

struct StereoParams {
  double  epipolar_tol_px   = 0.5;      // 极线残差阈值
  bool    enforce_epipolar  = true;     // 沿极线的一维搜索
  int32_t cross_check       = 1;        // 左右一致性检查
  bool    joint_optimize    = true;     // 时空联合优化（同时解跨相机与跨时刻）
};

// 立体匹配 → 视差 → 三角化 → 世界坐标；每步均可单独取用与审计
Result<FieldSet> stereo_match(const CorrelationRequest&, const StereoParams&,
                              ProgressSink&, CancelToken);

Result<FieldSet> triangulate(const Calibration&, const FieldSet& disparity,
                             TriangulationMethod = TriangulationMethod::OptimalMidpoint,
                             Mat6d* out_point_cov = nullptr);   // ← 逐点协方差直接产出

}  // namespace hl3::corr
```

### 8.3 IO 门面

```cpp
// include/hl3/io/project_io.hpp
namespace hl3::io {

enum class Container { Hdf5, Zarr };

struct OpenOptions {
  bool     read_only     = false;
  bool     lazy_fields   = true;      // 惰性列
  bool     verify_hashes = false;     // 校验外链图像完整性
  Container container    = Container::Hdf5;
};

Result<std::unique_ptr<Project>> open(const std::filesystem::path&, const OpenOptions&);
Result<std::unique_ptr<Project>> create(const std::filesystem::path&, const ProjectMeta&, Container);
Void save(Project&);                                  // 增量写，保留未知 group
Void save_as(Project&, const std::filesystem::path&, Container);

struct ValidationReport { bool ok; std::vector<Error> violations; SemVer schema_version; };
Result<ValidationReport> validate(const std::filesystem::path&, bool strict);

// 导出统一入口；format 由 IExporter 插件注册表解析
Void export_fields(const Analysis&, std::string_view format,
                   const std::filesystem::path& pattern,   // 支持 "%04d" 帧占位
                   const ExportOptions&, ProgressSink&, CancelToken);

}  // namespace hl3::io
```

---

## 9. 交给后续轮次的开放问题

1. **许可证定调**：内核 Apache-2.0 还是 MPL-2.0？若要参考 OpenCorr（MPL-2.0）需注意文件级 copyleft；DICe 的许可证需逐条复核。规范文件单独 CC-BY-4.0 已可先定。（→ R1-G1）
2. **全局 FE-DIC 是内核一等公民还是插件？** 本设计已用 `GridKind::FeMesh` + `ICorrelator` 为它留位，但正则化项、网格自适应是否进核心待定。（→ R1-O1 / R2）
3. **Schema 1.0 冻结时机**：建议在第一次跑通 iDICs Challenge 数据集之后再冻结，避免过早承诺。此前用 `0.x` 并明确声明不稳定。（→ R1-G2）
4. **实时通路**：`hl3-gauge` 的低延迟要求可能与"结果全量落盘 + 溯源"冲突。倾向做成"环形缓冲 + 抽稀落盘 + 事后补全"，需 Round 2 定方案。
5. **卷帘快门与热漂移补偿**是否进 Schema 1.0：已在 `Camera` 里留字段，补偿算法归属待定。
6. **DVC（体相关）的前向兼容**：当前 Schema 的 `ref_xy(P,2)` 需要能扩到 `(P,3)`。建议 1.0 就允许最后一维为 2 或 3，避免将来破坏性变更。

---

## 附：API 亮点（一句话版）

- `hl3.Project` / `Analysis` **同一签名跑 2D 与 3D**，靠 `AnalysisType` 分派，不分叉代码。
- **命令总线**：GUI 每个按钮 = 一个 `ICommand`，自带 `to_python()`；CI 强制 100% 覆盖，GUI 可"导出为脚本"。
- **公开 schema + 纯 h5py 参考读取器 + 一致性套件 + `hl3 validate`**，格式本身作为竞争武器。
- **零拷贝** `ana.field("u") → np.ndarray`（capsule 持有所有权、默认只读），`to_xarray()` 带维度名。
- **不确定度是字段不是报告**：`u_std/v_std/w_std/cov_uvw` + 三来源分解，与位移场同生命周期。
- **`px` 是独立量纲**，未经溯源的标定不能转成 mm —— 编译期/运行期拦截。
- **确定性三件套**：与线程数解耦的分块、固定顺序归约、counter-based Philox RNG。
- **GPU 边界在"一批子区"**，CPU 为规范实现，GPU 必须通过 `<1e-6 px` 逐位对拍才可用于计量模式。
- **C ABI 插件 + Python entry-point 插件**双通道，插件强制声明 SPDX 许可证与确定性等级。
- **`--metrology-mode`**：机器可判定的"这份结果能不能进报告"。
