ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR1-F3 · `hl3.pipeline.run_2d` 公开 Python API 冻结（S1）

- **状态**：FROZEN（S1 起生效）。推翻任何冻结条目需父调度器书面 ADR 并在 `MASTER_PLAN.md` 留痕（FRZ 纪律）。
- **本文冻结的对象**：`hl3.pipeline` 的**调用面**（名字、签名、返回结构、可观察语义）。这是 S4 CLI（`hl3 run` 等）唯一允许依赖的 Python 入口。
- **本文不冻结的对象**：数值内核细节（效力归 R1-O1 §2 / R2-O1，RUL-08 顺序）；HDF5 应变组属性（效力归 `hl3.io.hdf5_schema` 与 IR1-F4）；实现文件的内部私有函数。
- **约束对象**：IR1-O3（`src/hl3/pipeline/**` 实现者）、IR1-O2（`src/hl3/strain/**`，其公开类型经本命名空间再导出）、Impl-R3 的 S4 CLI。
- **法务**：独立实现公开算法；不接触任何 VIC 二进制或专有细节；显微镜零实现（RUL-04/06，`LEGAL.md`）。

---

## 1. 冻结的导入面

`hl3.pipeline` 的 `__all__` **恰好**为以下六个名字。物理定义可以放在别处（如 `StrainParams` 定义于 `hl3.strain`），但从 `hl3.pipeline` 的再导出是冻结契约的一部分。

| 名字 | 种类 | 一句话 |
|------|------|--------|
| `run_2d` | 函数 | 参考图 + 变形图 + 参数 → 位移场 + 应变场（一次调用走完 2D 链） |
| `Pipeline2DParams` | frozen dataclass | 全链参数容器：`icgn` + `strain` |
| `StrainParams` | frozen dataclass | 应变引擎参数（PLS/VSG） |
| `Run2DResult` | frozen dataclass | `run_2d` 返回值，含 `displacement` 与 `strain` |
| `DisplacementField` | frozen dataclass | 逐 POI 位移解（原始值 + 状态，不掺 NaN） |
| `StrainField` | frozen dataclass | 逐 POI 应变（无效点 = NaN） |

冻结导入路径：`from hl3.pipeline import run_2d, Pipeline2DParams, StrainParams, Run2DResult, DisplacementField, StrainField`。

---

## 2. `run_2d` 签名与语义

```python
def run_2d(
    reference: np.ndarray,          # (H, W) 灰度图，任意实数 dtype，内部转 float64
    deformed: np.ndarray,           # (H, W)，必须与 reference 同形状
    params: Pipeline2DParams | None = None,   # None → Pipeline2DParams()
) -> Run2DResult: ...
```

**命名裁决（冻结）**：派工里的口头写法 `run_2d(ref, def, params)` 中 `def` 是 Python 保留字，不能做形参名。冻结的形参名为 **`reference` / `deformed` / `params`**，与内核 `icgn_first_order(reference, target, ...)` 的第一参数命名一致；`deformed` 而非 `target` 是 pipeline 层语义（同一相机、不同时刻）。CLI 按位置传参即可视作 `(ref, def, params)`。

**语义（全部冻结）**：

1. **单帧**。一次调用处理一张变形图。多帧序列由调用方（S4 CLI）循环并按帧堆叠为 schema 的 `(F, P)`；S1 唯一参考策略即 `{"kind": "fixed", "frame": 0}`。序列级入口（增量参考、跨帧种子传播）留给未来**新增名字**（如 `run_2d_sequence`），不得改动 `run_2d` 自身。
2. **POI 网格由参数决定**。网格 = `hl3.correlate.icgn.make_grid(reference.shape, params.icgn)`（默认 margin 公式随内核）。S1 不暴露自定义 `points` / AOI 参数——研究用途直接调内核 `icgn_first_order`。未来扩展只能以**关键字专用、默认值复现冻结行为**的方式追加。
3. **纯函数、不碰文件**。`run_2d` 不读写磁盘、无 RNG、无全局状态；HDF5 写入是 `hl3.io` 与 CLI 的职责。
4. **计量规范路径**。CPU float64 参考实现（RUL-02）；同平台同输入 → 输出逐位可复现；S1 参考实现单线程。
5. **失败语义两层**：
   - **调用级错误 → 异常**（计算开始前抛出）：非 2-D 图像、含非有限像素、形状不匹配、非法参数（dataclass `__post_init__` 校验）→ `ValueError`；类型完全不对 → 常规 Python `TypeError`。
   - **逐点失败 → 永不抛异常**：以 `DisplacementField.status`（`hl3.correlate.icgn.Status`，取值编号已冻结）与 `StrainField` 的 NaN 表达。fail-closed：绝不返回貌似合理的编造数。
6. **默认网格非空有保证**（`make_grid` 的 margin 校验使然）；图像小到放不下一个 subset → `ValueError`。

---

## 3. `Pipeline2DParams`

```python
@dataclass(frozen=True)
class Pipeline2DParams:
    icgn: ICGNParams = ICGNParams()        # hl3.correlate.icgn.ICGNParams，原样复用，不包一层
    strain: StrainParams = StrainParams()

    @property
    def vsg_px(self) -> float: ...         # = vsg_size_px(strain.window_pts, icgn.step, icgn.subset_size)
    def to_config(self) -> dict: ...       # 供 @config_hash 的规范化配置字典
```

冻结条目：

- 字段名 `icgn`、`strain` 及其类型；**不得**把 ICGN 参数摊平重命名——`ICGNParams` 的字段语义效力归内核。
- `vsg_px` 属性存在且等于 `hl3.io.hdf5_schema.vsg_size_px(window_pts, step_px, subset_px)`，其中 `subset_px = 2 * icgn.subset_radius + 1`（iDICs GPG 式 7.2；与 schema 模块同一函数，禁止另写一份公式）。
- `to_config()` 存在，返回值必须能通过 `hl3.io.hdf5_schema.canonical_json`（无 NaN/Inf），且至少含键 `correlator / criterion / interp / shape_function / subset_px / step_px / conv_tol / max_iters / deterministic / strain{...}`。**精确键集在 S1 为 draft**，由 IR1-O3 定稿并被 `@config_hash` 回归测试锁定后升格冻结。

## 4. `StrainParams`

```python
@dataclass(frozen=True)
class StrainParams:
    window_pts: int = 5                  # 正奇数 >= 3，以 POI 计（不是像素）
    tensor: str = "green_lagrange"       # S1 实现集: {"engineering", "green_lagrange"}
    weighting: str = "uniform"           # 冻结槽位: {"uniform", "gaussian"}；S1 仅实现 uniform
    min_valid_fraction: float = 0.5      # neighbor_min = ceil(f * window_pts**2)
```

冻结条目与裁决：

- **方法固定** `method = "local_plane_fit"`（PLS，Pan 2007；R1-O1 §2.11 步骤 1）。不是参数——S1 唯一实现；其余 `STRAIN_METHODS` 取值（`savitzky_golay / fe_gradient / spline_global`）是 schema 已留的槽位，落地时以新增枚举值方式进入 `StrainParams`，不破坏本签名。
- `tensor` 取值必须属于 `hl3.io.hdf5_schema.STRAIN_TENSORS`；S1 实现 `engineering` 与 `green_lagrange`（默认后者，随 R1-O1 §1.6）。未知取值 → `ValueError`，禁止静默猜测（schema §11.2 纪律）。
- `exy` 为**张量剪应变**分量（`γ_xy = 2·exy`），与 schema 数据集 `exy` 同义。
- **邻点判据（冻结）**：参与拟合的邻点必须 `status == Status.CONVERGED`（`LOW_ZNCC` 保留但不参与应变拟合，R1-O1 §1.5/§2.6）；窗口 = 以该 POI 为中心的 `window_pts × window_pts` POI 索引窗与网格的交集（边界自然裁剪）；有效邻点数 `< ceil(min_valid_fraction · window_pts²)` → 该点应变 = NaN，**不外推、不补零、不缩窗**。
- PLS 的 Δx/Δy 以**像素**计（= 索引偏移 × `icgn.step`），因此拟合系数直接是位移梯度 `u_x, u_y, v_x, v_y`。
- **对 R1-O1 §1.6 的一处 S1 偏差（如实登记）**：产品默认加权是 `GAUSSIAN(σ = L/4)`，S1 只实现 `uniform` 并以之为默认。`gaussian` 落地后翻转默认值属于数值行为变更，须过 A4/G2 门并在报告留痕。此偏差不改变 R1-O1 的效力顺位。

---

## 5. `DisplacementField`

字段布局向内核 `ICGNResult` 看齐（降低搬运成本），追加网格与元数据。全部数组按 POI 索引，`(P,)` 或 `(P, k)`。

```python
@dataclass(frozen=True)
class DisplacementField:
    x: np.ndarray            # (P,) f64 参考构形 x [px]
    y: np.ndarray            # (P,) f64 参考构形 y [px]
    p: np.ndarray            # (P, n_shape_params) f64 形函数参数
    zncc: np.ndarray         # (P,) f64；-1 表示"从未评估"
    iterations: np.ndarray   # (P,) i32
    status: np.ndarray       # (P,) i32，hl3.correlate.icgn.Status（编号冻结）
    grid_shape: tuple[int, int]   # (ny, nx)，P == ny * nx
    shape_function: str      # "affine"（S1）| "quadratic"（IR1-O1 落地后）
    space: str               # 恒为 "px"（S1 无标定；schema @space）

    @property
    def u(self) -> np.ndarray: ...        # (P,) = p[:, 0]（affine 布局）
    @property
    def v(self) -> np.ndarray: ...        # (P,) = p[:, 3]（affine 布局）
    @property
    def valid(self) -> np.ndarray: ...    # (P,) bool == (status == Status.CONVERGED)
    @property
    def n_points(self) -> int: ...
    def masked(self, field_name: str) -> np.ndarray: ...   # 无效点置 NaN 的副本；语义同 ICGNResult.masked
```

冻结条目：

- **原始值 + 状态**，位移数组本身不掺 NaN（与 schema「fields 存原始值、flags 判有效」的口径一致）；要 NaN 版用 `masked(...)`。
- **点序（冻结）**：行主序、y 外 x 内，`index = iy * nx + ix`，与 `make_grid` 的 meshgrid-ravel 及 schema `ref_xy` 注记一致。`(P,)` ↔ `(ny, nx)` 的 reshape 因此无歧义。
- `p` 的第二维 = `n_shape_params`（affine=6、quadratic=12，`hl3.io.hdf5_schema.SHAPE_PARAM_COUNT`）。**affine 布局冻结**为 `(u, u_x, u_y, v, v_x, v_y)`；quadratic 布局由 IR1-O1 在其报告定稿，唯一硬约束：`u`/`v` 访问器语义不变。
- `u`、`v`、`valid`、`n_points`、`masked` 五个访问器名字与语义冻结。

## 6. `StrainField`

```python
@dataclass(frozen=True)
class StrainField:
    exx: np.ndarray          # (P,) f64，无效点 = NaN
    eyy: np.ndarray          # (P,) f64
    exy: np.ndarray          # (P,) f64（张量剪分量）
    tensor: str              # 实际使用的张量族
    method: str              # "local_plane_fit"（S1）
    window_pts: int
    vsg_px: float            # = Pipeline2DParams.vsg_px
    grid_shape: tuple[int, int]   # 与 DisplacementField 相同的点序

    @property
    def valid(self) -> np.ndarray: ...      # (P,) bool == np.isfinite(exx)
    @property
    def n_points(self) -> int: ...
    # 派生量（按需计算，公式效力归 R1-O1 §2.11 步骤 3）：
    @property
    def e1(self) -> np.ndarray: ...         # (exx+eyy)/2 + sqrt(((exx−eyy)/2)² + exy²)
    @property
    def e2(self) -> np.ndarray: ...         # (exx+eyy)/2 − sqrt(...)
    @property
    def theta_p(self) -> np.ndarray: ...    # ½·atan2(2·exy, exx−eyy) [rad]
    @property
    def gamma_max(self) -> np.ndarray: ...  # e1 − e2
    @property
    def von_mises(self) -> np.ndarray: ...  # 等效应变；确切公式与假设由 IR1-O2 在 docstring 与报告写死
```

冻结条目：

- **NaN 语义**：应变数组是 NaN 承载的（与位移相反）——无效点、邻点不足点、掩膜点一律 NaN；`valid == isfinite(exx)`，且三个分量的 NaN 模式必须一致。
- 张量公式（`F = I + ∇u`；工程应变线性化 / `E = ½(FᵀF − I)`）效力归 R1-O1 §2.11；本文只冻结**分量名与派生量名字**。`von_mises` 的常数约定 R1-O1 未唯一化，冻结要求：IR1-O2 选定后在 docstring 显式给出公式与"平面应力 + 不可压近似"等前提，之后即视为冻结。
- 元数据四元组 `tensor / method / window_pts / vsg_px` 与 schema `strain/<id>` 必填属性（`STRAIN_REQUIRED_ATTRS`）一一对应——CLI 写文件时**直接透传，不得再算**。

## 7. `Run2DResult`

```python
@dataclass(frozen=True)
class Run2DResult:
    displacement: DisplacementField
    strain: StrainField
    params: Pipeline2DParams          # 实际生效参数的回显（含全部默认值）

    def __iter__(self): ...           # 永远恰好 yield (displacement, strain)
```

冻结条目：

- 属性名 `displacement` / `strain` / `params`。
- **二元组解包糖永久冻结**：`disp, strain = run_2d(...)` 永远成立。后续阶段（S2/S3 的 UQ、诊断）只能以**新增属性**扩展，`__iter__` 产出个数与顺序不得改变——这就是"返回 DisplacementField + StrainField"承诺的向后兼容实现方式。

---

## 8. 面向 S4 CLI 的映射表（资料性；schema 侧效力归 `hl3.io.hdf5_schema` 与 IR1-F4）

| API 成员 | HDF5 落点（`/analyses/<id>/…`） | 备注 |
|----------|--------------------------------|------|
| `displacement.x, y` | `grid/ref_xy` | 列拼接为 (P, 2) |
| `displacement.u, v` | `fields/u`, `fields/v` + `@space="px"` | 写入方加帧轴 → (F, P)；可降型 f32（附录 A） |
| `displacement.p` | `fields/p_shape` | 连同 `grid/@shape_function`、`@n_shape_params` |
| `displacement.zncc` | `fields/zncc` | |
| `displacement.iterations` | `fields/iters` | |
| `displacement.status` | `fields/flags` | 按下表映射为 `FieldFlags` 位域 |
| `strain.exx, eyy, exy` | `strain/default/{exx,eyy,exy}` | NaN 原样落盘 |
| `strain.tensor/method/window_pts/vsg_px` | `strain/default/@*` | 透传 |
| `params.to_config()` | `config` 数据集 + `@config_hash` | 经 `canonical_json` / `config_hash` |

**Status → FieldFlags 映射（资料性草案，写入器实现处定稿）**：`CONVERGED → CONVERGED` 位（FFT-CC 起步的点另加 `SEEDED`）；`MASKED → MASKED`；因平坦/低对比判死的 `SINGULAR_HESSIAN` 可加 `LOW_CONTRAST`；其余失败态一律**不置 `CONVERGED` 位**，从而被 schema §9.5 的 `valid_mask` 判无效。禁止置保留位 12–23。

## 9. 最小用例（契约级示例）

```python
import numpy as np
from hl3.pipeline import run_2d, Pipeline2DParams, StrainParams
from hl3.correlate.icgn import ICGNParams

params = Pipeline2DParams(
    icgn=ICGNParams(subset_radius=10, step=5, search_radius=8),
    strain=StrainParams(window_pts=5, tensor="green_lagrange"),
)
disp, strain = run_2d(reference_image, deformed_image, params)

u_map = disp.masked("u").reshape(disp.grid_shape)      # NaN 掩膜后的 (ny, nx) 云图
exx_map = strain.exx.reshape(strain.grid_shape)        # 应变本身即 NaN 承载
assert strain.vsg_px == params.vsg_px
```

## 10. 非目标（S1 明确不在 `run_2d` 契约内）

序列/增量参考、AOI 多边形与自定义 POI、标定与物理单位（`space` 恒 `"px"`）、UQ 传播（S3）、刚体去除等后处理算子、GPU 后端、文件 IO、任何显微镜/SEM 能力（RUL-04 零实现）。

## 11. 兼容性与变更规则（冻结）

1. §1 六个名字在 v1.0 前不得改名、删除或移出 `hl3.pipeline`。
2. 一切扩展 = 追加关键字专用参数（默认值复现冻结行为）或追加新名字；已冻结的位置参数个数与顺序不变。
3. 数值行为变更（默认插值、加权翻转、二阶形函数默认化等）必须过相应 A/G2 门并在轮次报告留痕；禁止只改代码不留证据。
4. 冲突消解按 RUL-08：`LEGAL.md` → R2-F1 裁决 → Gate/协议 → 内核规格（R1-O1/R2-O1）→ 本文（调用面）→ 实现代码注释。数值语义以内核规格为准，调用面以本文为准。

## 12. 交接清单

- **IR1-O3**：按本文实现 `src/hl3/pipeline/**` 与 `tests/test_pipeline_2d.py`；`to_config()` 键集定稿；Status→Flags 映射若由 pipeline 层承担则在其报告定稿。
- **IR1-O2**：`StrainParams` 与 `StrainField` 的物理定义、PLS 实现、`von_mises` 公式定稿（§6 约束内）。
- **IR1-O1**：quadratic 形函数 `p` 布局定稿（§5 约束内）。
- **IR1-F4**：`strain/<id>` schema 属性面冻结；与 §8 表若有出入，以 F4 + `hdf5_schema` 为准。
- **S4 CLI**：只允许 import §1 的六个名字 + `hl3.correlate.icgn.{ICGNParams, Status}` + `hl3.io.hdf5_schema` 公开面。

*IR1-F3 完。本文未改动 `src/**` 任何文件。*
