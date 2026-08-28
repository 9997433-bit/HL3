ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR2-F3 · UQ 契约：位移协方差 → 应变标准差 API（S3）

- **状态**：FROZEN（Impl-R2 起生效）。推翻任何冻结条目需父调度器书面 ADR 并在 `MASTER_PLAN.md` 留痕（FRZ 纪律）。
- **本文冻结的对象**：`hl3.uq` 的**调用面**（名字、签名、返回结构、可观察语义）与传播链 B/C/D 三段的**数学定义**——从逐 POI 位移协方差到逐 POI 应变分量标准差。
- **本文不冻结的对象**：A 段核内公式 `Cov(p) ≈ 2σ_n²·H⁻¹` 的效力归 R1-O1 §2.6/§6.2（已在 `hl3.correlate.icgn` 落地）；HDF5 `uncertainty/` 组属性面的效力归 `hl3.io.hdf5_schema` 与 `docs/schema-hdf5.md` §9.4；噪声底板/bootstrap 等其他 UQ 方法只共享词表，不在本契约内。
- **约束对象**：IR2-O3（`src/hl3/uq/**`、`tests/test_uq.py` 实现者）、IR2-F4（validate CLI 校验规则）、Impl-R3 的 S4 写入器。
- **法务**：独立实现公开方法（Pan 2007 PLS 方差、一阶 delta 法、iDICs GPG §5.4）；不接触任何 VIC 二进制或专有细节（RUL-04/06，`LEGAL.md`）。

---

## 1. 传播链总览（四段，责任分账）

| 段 | 内容 | 落点 | 状态 |
|----|------|------|------|
| A | 图像噪声 σ_n → 逐 POI 形函数参数协方差 `Cov(p) = 2σ_n²·H⁻¹` | `hl3.correlate.icgn`，`ICGNResult.covariance (P, k, k)` | **已实现**（`compute_covariance=True` 时填充） |
| B | `Cov(p)` → 逐 POI 位移方差三元组 `Var(u), Var(v), Cov(u,v)` | `hl3.uq.displacement_variances` | 本契约冻结，IR2-O3 实现 |
| C | 位移方差网格 → PLS 梯度 4×4 协方差（线性算子传播） | `hl3.uq.propagate_strain_std` 内部 | 本契约冻结公式 |
| D | 梯度协方差 → 应变分量 std（一阶 delta 法） | 同上，产出 `StrainStdField` | 本契约冻结公式 |

链条成立的原因：PLS 应变（`hl3.strain.pls`）对邻点位移是**线性**估计器——每个梯度都是窗口内位移的固定加权和——所以 C 段是精确的线性方差传播；只有 D 段（非线性张量族）需要线性化。

## 2. 冻结的导入面

`hl3.uq` 的 `__all__` **恰好**为以下四个名字：

| 名字 | 种类 | 一句话 |
|------|------|--------|
| `displacement_variances` | 函数 | `ICGNResult` → 逐 POI `Var(u)/Var(v)/Cov(u,v)`（B 段） |
| `DisplacementVariances` | frozen dataclass | B 段结果 + `u_std`/`v_std` 访问器（schema `uncertainty/` 直供） |
| `propagate_strain_std` | 函数 | 位移方差网格 + 应变参数 → 应变 std 场（C+D 段一次走完） |
| `StrainStdField` | frozen dataclass | 逐 POI 应变分量 std（NaN 承载）+ 假设登记元数据 |

冻结导入路径：`from hl3.uq import displacement_variances, DisplacementVariances, propagate_strain_std, StrainStdField`。

## 3. B 段：`displacement_variances`

```python
def displacement_variances(result: ICGNResult) -> DisplacementVariances: ...

@dataclass(frozen=True)
class DisplacementVariances:
    u_var: np.ndarray        # (P,) f64  Var(u) [位移单位²]，NaN 承载
    v_var: np.ndarray        # (P,) f64  Var(v)
    uv_cov: np.ndarray       # (P,) f64  Cov(u, v)（同一 POI 的 u–v 交叉项）
    shape_order: int         # 来源回显：1 = affine，2 = quadratic

    @property
    def u_std(self) -> np.ndarray: ...   # (P,) sqrt(u_var)，NaN 保留 → uncertainty/u_std
    @property
    def v_std(self) -> np.ndarray: ...   # (P,) sqrt(v_var)，NaN 保留 → uncertainty/v_std
```

冻结条目：

1. **提取索引**按 `hl3.correlate.icgn.shape_param_labels(order)` 的冻结布局：`u` 恒为 `p[0]`；`v` 为 `p[3]`（一阶）/ `p[6]`（二阶）。即 `u_var = C[:, 0, 0]`、`v_var = C[:, iv, iv]`、`uv_cov = C[:, 0, iv]`，`iv ∈ {3, 6}`。禁止另写一份索引常量——与 `ICGNResult.v` 访问器同源。
2. **fail-closed**：`result.covariance is None`（即 `compute_covariance=False` 的解）→ `ValueError`。没有协方差就没有 UQ 可提取，不猜、不用 ZNCC 之类代理量顶替。
3. **NaN 语义原样透传**：核只为 `CONVERGED` 与 `LOW_ZNCC` 点填协方差，其余点是 NaN；B 段不按 status 重掩膜——有效性判据在 C 段与应变拟合共用同一个 `valid` mask（§4 条 3），两处判据不允许分叉。
4. 单位：`Var` 为位移单位的平方。S2/S3 未标定 2D 链恒为 px²；σ_n 的灰度单位（DN）→ px² 的换算已发生在 A 段核内。

## 4. C+D 段：`propagate_strain_std`

```python
def propagate_strain_std(
    u: np.ndarray,                       # (ny, nx) 与 compute_strain 的同一份位移网格
    v: np.ndarray,                       # (ny, nx)
    u_var: np.ndarray,                   # (ny, nx) Var(u)，NaN = 该点无协方差
    v_var: np.ndarray,                   # (ny, nx) Var(v)
    params: StrainParams | None = None,  # 必须与产出该应变场的参数值相同；None → StrainParams()
    *,
    step_px: float,                      # 与 compute_strain 相同的值、相同的单位
    uv_cov: np.ndarray | None = None,    # (ny, nx) Cov(u, v)；None → 按 0 处理
    valid: np.ndarray | None = None,     # 与 compute_strain 相同的邻点判据 mask（status == CONVERGED）
    check_against: StrainField | None = None,   # 提供时做 fail-closed 一致性交叉校验
    image_noise_sigma_dn: float | None = None,  # 仅回显进元数据（→ @image_noise_sigma_dn）
) -> StrainStdField: ...
```

冻结条目：

1. **签名镜像 `compute_strain`**。std 描述的必须是**实际使用的那个估计器**：同一份 `u/v`、同一个 `params`、同一个 `step_px`、同一个 `valid`。窗口、权重、掩膜与 `hl3.strain.pls.pls_gradients` 完全一致地重建每点有效权重（§5 C 段）；网格→标量 POI 阵的适配沿用 `hl3.strain.grid_from_points`，禁止另写栅格化。
2. **等价性纪律**：IR2-O3 独占路径是 `src/hl3/uq/**`，不得改 `src/hl3/strain/**`；`hl3.uq` 内部凡与 PLS 重叠的量（拟合梯度、邻点计数、NaN 模式）必须有测试断言与 `pls_gradients` 输出**逐位相等**（同一法方程、同一特征值秩判据 `_REL_EPS` 语义），防止两份实现漂移。
3. **`valid` 判据同源**：冻结判据仍是 IR1-F3 §4 的 `status == Status.CONVERGED`——`LOW_ZNCC` 点不参与应变拟合，因此也不参与 std 传播；`u_var` 在该点是否有限无关紧要。
4. **`check_against` 语义**：给出时，重建的梯度 NaN 模式必须与 `check_against` 的 NaN 模式完全一致，且 `tensor/method/window_pts/weighting` 元数据一致，否则 `ValueError`——参数漂移是本链最隐蔽的错法，交叉校验是廉价保险。省略时不校验（研究用途）。
5. **纯函数**：不读写磁盘、无 RNG、无全局状态；CPU float64；同平台同输入逐位可复现（RUL-02）。

### 返回值 `StrainStdField`

```python
@dataclass(frozen=True)
class StrainStdField:
    exx_std: np.ndarray            # (P,) f64，NaN 承载；点序与 StrainField 相同（行主序）
    eyy_std: np.ndarray            # (P,)
    exy_std: np.ndarray            # (P,) 张量剪分量的 std；gamma_xy_std = 2 * exy_std
    tensor: str                    # 被传播的张量族（回显）
    window_pts: int
    grid_shape: tuple[int, int]
    method: str = "propagated"                  # UQ_METHODS 成员，本链恒为 "propagated"
    neighbor_correlation: str = "independent"   # 假设登记（§6 A1），冻结的槽位名
    image_noise_sigma_dn: float | None = None   # 回显 → @image_noise_sigma_dn

    @property
    def valid(self) -> np.ndarray: ...          # (P,) bool == np.isfinite(exx_std)
    @property
    def n_points(self) -> int: ...
    def as_grid(self, name: str) -> np.ndarray: ...       # (ny, nx) 视图，语义同 StrainField.as_grid
    def schema_datasets(self) -> dict[str, np.ndarray]: ...  # {"exx": exx_std, "eyy": ..., "exy": ...}
    def schema_attrs(self) -> dict[str, object]: ...      # {"method": ..., "image_noise_sigma_dn": ...?}
```

- 三个 std 分量共享一个 NaN 模式，`valid == isfinite(exx_std)` 精确成立（与 `StrainField` 同一纪律）。
- `schema_datasets()` 的键**必须**与 `strain/<id>` 数据集同名（`exx/eyy/exy`）——schema §9.4 的 `strain_std/<name>` 同名规则；派生量（`e1`、`von_mises` 等）的 std 是 S3 非目标，键集扩展走追加规则。

## 5. 冻结的公式

**C 段（精确线性传播）。** 记某 POI 的拟合窗口内有效邻点 j 的索引单位偏移为 `(dx_j, dy_j)`，`A` 为基函数矩阵（`_TERMS` 顺序：index 1 = dx 项、index 2 = dy 项），`W = diag(w_j)` 为窗口权重×掩膜，`G = AᵀWA`。定义每点两行有效权重向量

```
c_x = (G⁻¹ AᵀW) 的第 1 行,   c_y = (G⁻¹ AᵀW) 的第 2 行
```

（正是 `pls_gradients` 读出 `u_x`/`u_y` 的那两行帽子矩阵）。令 `g = (u_x, u_y, v_x, v_y)`，其 4×4 协方差在假设 A1/A2（§6）下：

```
Cov(u_a, u_b) = Σ_j c_a[j]·c_b[j]·Var(u_j) / step_px²      a, b ∈ {x, y}
Cov(v_a, v_b) = Σ_j c_a[j]·c_b[j]·Var(v_j) / step_px²
Cov(u_a, v_b) = Σ_j c_a[j]·c_b[j]·Cov(u_j, v_j) / step_px²
```

除以 `step_px²` 与 `pls_gradients` 的"索引单位拟合、末端除步长"完全对应。

**D 段（一阶 delta 法）。** 对每个分量 ε：`Var(ε) = J_ε Σ_g J_εᵀ`，`std = sqrt`。雅可比按张量族冻结（在拟合出的梯度处取值）：

| tensor | J_exx | J_eyy | J_exy |
|--------|-------|-------|-------|
| `engineering` | `(1, 0, 0, 0)` | `(0, 0, 0, 1)` | `(0, ½, ½, 0)` |
| `green_lagrange` | `(1+u_x, 0, v_x, 0)` | `(0, u_y, 0, 1+v_y)` | `½·(u_y, 1+u_x, 1+v_y, v_x)` |

- `engineering` 的传播是**精确**的（线性张量）；`green_lagrange` 是一阶近似，二阶修正是未来关键字槽位。
- **S3 张量范围冻结为 `{engineering, green_lagrange}`**。`euler_almansi / hencky / logarithmic` 的解析雅可比未定稿，S3 传入 → `ValueError`（fail-closed，禁止静默按 engineering 近似）；落地时以新增取值方式进入，不破坏签名。

**闭式锚点（gate 判据，冻结）。** uniform 权重、linear 拟合、完整 L×L 窗、同方差 `Var(u)=σ_u²`、`uv_cov=0` 时：

```
Var(u_x) = 12·σ_u² / (L²·(L²−1))  （索引单位）
σ_exx(engineering) = (σ_u / step_px) · sqrt(12 / (L²·(L²−1)))
```

（Pan 2007 的 PLS 应变噪声闭式。例：σ_u = 0.01 px、step = 5、L = 5 → σ_exx ≈ 2.83e-4。）实现必须在合成输入上与该闭式相对偏差 ≤ 1e-12。

## 6. 假设登记（冻结的诚实声明，随结果落盘）

| 编号 | 假设 | 后果与登记方式 |
|------|------|----------------|
| A1 | **邻点 POI 误差相互独立**。step < subset 时子集重叠使相邻误差正相关，std 系统性**偏低** | `neighbor_correlation="independent"` 随 `StrainStdField` 携带；相关性修正 = 未来关键字，默认值复现冻结行为 |
| A2 | 同一 POI 的 u–v 交叉项取核的 2×2 块（`uv_cov`），跨 POI 交叉项为 0 | A1 的推论；`uv_cov=None` → 按 0 处理并如实为"忽略同点交叉项" |
| A3 | 核协方差模型：两图各自 i.i.d. 高斯 σ_n、以收敛解为条件（R1-O1 §2.6）。插值偏差、散斑图案诱导偏差是**系统误差**，不在随机 std 内 | 文档级声明；validate 报告须原样引用 |
| A4 | D 段为一阶 delta 法 | `green_lagrange` 大应变下近似；二阶修正为未来槽位 |

## 7. NaN 与错误语义（冻结，沿用全库两层惯例）

- **调用级错误 → `ValueError`**：形状不匹配、非 2-D 网格、`step_px` 非有限或 ≤ 0、`params` 非法（委托 `StrainParams.__post_init__`）、S3 范围外的 tensor、`covariance is None`（B 段）、**有限但为负的方差**（坏输入不是缺测）、`check_against` 不一致。
- **缺测 → NaN，永不抛异常**：
  1. 应变本身为 NaN 的点（邻点不足、掩膜、中心缺测）→ std 为 NaN；
  2. 应变有限、但**参与该点拟合的任一有效邻点**的 `u_var`/`v_var`（或给出的 `uv_cov`）非有限 → 该点 std 为 NaN，应变值本身不受影响。fail-closed：绝不把缺失方差当 0，也绝不缩窗重算——那会让 std 描述另一个估计器。
- 恒有 `isfinite(std) ⊆ isfinite(strain)`：std 的有效集是应变有效集的子集，永不反向。

## 8. Schema 落点映射（资料性；效力归 `hl3.io.hdf5_schema` 与 IR1-F4）

| 契约产物 | HDF5 落点（`/analyses/<id>/uncertainty/…`） | 备注 |
|----------|---------------------------------------------|------|
| `DisplacementVariances.u_std / v_std` | `u_std`、`v_std` | 必填数据集；写入器加帧轴 → (F, P)，可降型 f32（附录 A） |
| `u_var / v_var / uv_cov` | `cov_uvw` 上三角 `[Cuu, Cuv, Cuw, Cvv, Cvw, Cww]` | 可选；2D 分析 w 项写 0 或整组省略，由写入器与 IR1-F4 定稿 |
| `StrainStdField.schema_datasets()` | `strain_std/{exx, eyy, exy}` | 名字与 `strain/<id>` 数据集**同名**（schema §9.4） |
| `method` | `@method = "propagated"` | `UQ_METHODS` 成员；词表校验在 `hdf5_schema` |
| `image_noise_sigma_dn` | `@image_noise_sigma_dn` | `ICGNParams.image_noise_sigma` 的回显，透传不再算 |

validate CLI（IR2-F4 / IR2-O3 的 `hl3.cli.validate`）至少检查：`@method` 在词表内；`u_std/v_std` 存在；立体分析必须有 `w_std`；`strain_std/` 下的名字 ⊆ `strain/` 数据集名；所有 std 值非负或 NaN；`@method="propagated"` 而上游缺协方差时报错（3D 情形 schema 已有"无标定协方差不能用 propagated"检查）。

## 9. S3 非目标（明确不在本契约内）

- **参考更新序列的组合方差**：`ReferenceMode ≠ FIXED` 时 `compose_total` 的分段方差合成未定义；此类运行不得写 `@method="propagated"` 的 `strain_std`（`u_std/v_std` 对各自分段参考仍有意义）。登记为 GAP，留给后续轮。
- 派生量（`e1/e2/theta_p/gamma_max/von_mises/tresca`）的 std——`strain_std/<name>` 同名规则已留槽位。
- 其他 UQ 方法（`bootstrap / repeat_static / synthetic_calibrated`）：只共享 `UQ_METHODS` 词表与 `uncertainty/` 落点；噪声底板 `@sigma_*_px_floor` 归 `repeat_static` 工具链。
- 立体链的 `w_std` 与标定协方差项 `Σ_cal`（`hl3.stereo.triangulation_covariance` 已有匹配项；合成归 IR2-F2/IR2-O2 范围）。
- 跨 POI 相关性建模、GPU 路径、任何显微镜能力（RUL-04 零实现）。

## 10. 测试与门挂钩（资料性，供 IR2-F1 定门、IR2-O3 落测试）

1. **闭式锚点**：§5 公式，相对偏差 ≤ 1e-12（uniform/linear/完整窗/同方差）。
2. **等价性**：`hl3.uq` 重建的梯度与 `pls_gradients` 输出逐位相等（含带洞窗口、边界、秩亏拒绝）。
3. **Monte Carlo**：合成噪声位移场 ≥ 100 次实现，预测 std / 实测 std 之比落在 **[0.8, 1.25]**（沿用 R1-O1 §5.6 T6 与立体协方差研究的同一口径）。
4. **链路端到端**：σ_n → `ICGNResult.covariance` → B → C+D → `strain_std`，与直接对图像加噪的实测应变散布同比落在 [0.8, 1.25]。
5. **失败语义**：负方差 → `ValueError`；邻点方差含 NaN → 仅该点 std 为 NaN；`covariance=None` → `ValueError`；空网格 → 空结果不抛。
6. **确定性**：同输入两次调用逐位相同；无 RNG。

## 11. 兼容性与变更规则（冻结）

1. §2 四个名字在 v1.0 前不得改名、删除或移出 `hl3.uq`。
2. 一切扩展 = 追加关键字专用参数（默认值复现冻结行为）或追加新名字；已冻结的位置参数个数与顺序不变。
3. 数值行为变更（相关性修正默认化、二阶 delta、张量范围扩容）必须过相应 A/G2 门并在轮次报告留痕。
4. 冲突消解按 RUL-08：`LEGAL.md` → R2-F1 裁决 → Gate/协议 → 内核规格（R1-O1 §2.6/§6.2）→ 本文（B/C/D 段与调用面）→ 实现代码注释。

## 12. 交接清单

- **IR2-O3**：按本文实现 `src/hl3/uq/**` 与 `tests/test_uq.py`（§10 条 1/2/5/6 必须落测试）；`hl3.cli.validate` 落 §8 的校验规则。
- **IR2-F4**：validate CLI 契约中 `uncertainty/` 校验条目与本文 §8 对齐；出入以 `hdf5_schema` + IR1-F4 为准。
- **IR2-G3**：`benchmarks/metrology/metrics.json` s3 段建议键：`s3.uq.closed_form_rel_err`、`s3.uq.mc_ratio_mean`、`s3.uq.chain_ratio_mean`。
- **S4 写入器**：按 §8 表透传，不得再算；`@method` 与假设登记字段原样落盘。

*IR2-F3 完。本文未改动 `src/**` 任何文件。*
