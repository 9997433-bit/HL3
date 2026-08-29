ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR3-F4 · FEA 契约：DIC 点 → 三角网格最近邻投影（S4）

- **状态**：FROZEN（Impl-R3 起生效）。推翻任何冻结条目需父调度器书面 ADR 并在 `MASTER_PLAN.md` 留痕（FRZ 纪律）。
- **本文冻结的对象**：`hl3.fea` 的**调用面**（名字、签名、返回结构、可观察语义）与 S4 最近邻投影的**数学定义**——从 DIC 点列到简单三角网格节点的最近邻映射，及其双向取值（FE→DIC gather / DIC→FE scatter）。
- **本文不冻结的对象**：等效 VSG 同滤波链对比、归一化残差 z 判定、实测边界条件导出（B6 完整闭环，见 R3-F4 路线图 §S4/S8）；全局 FE-DIC 求解器（RUL-05：v1.x 官方 beta）；Exodus / Abaqus inp 导入。它们只共享本文的 `TriMesh` 词表。
- **约束对象**：IR3-O3（`src/hl3/fea/**` 与对应测试的实现者）、IR3-G2（`tests/test_s4_smoke.py` 的 `hl3.fea` import 冒烟）、IR3-G3（pyproject extras，见 §8 资料性建议）。
- **法务**：numpy 暴力最近邻 + VTK **公开数据模型**（单元类型码、legacy/XML 文件格式均为公开规范，schema-hdf5.md §9.1 已引用）；不接触任何 VIC/iris 二进制或专有细节（RUL-04/06，`LEGAL.md`）。禁止 GPU 内核、相机 SDK、显微镜能力（IR3 派工总则）。

---

## 1. S4 链条定位（一句话）

FEA 闭环（B6）的最小可用第一环：**把 DIC 测得的点列贴到用户给的 FE 三角网格上**，使 `dic_value − fe_value` 逐点残差在同一索引系下可算。S4 冻结的方法**只有** `nearest_node`（逐点取欧氏距离最近的网格节点）；`barycentric`（三角形内重心坐标插值）与最近表面点投影是已预留的未来取值，本轮传入即错（fail-closed，§5 条 4）。

DIC 侧输入刻意解耦为裸 `(P, D)` 数组，不绑定结果类——适配是一行事：

| DIC 链 | 点列来源 | D | 单位 |
|--------|----------|---|------|
| 2D（`ICGNResult` / `Dic2DRun`） | 参考位置 `ref_xy` 或变形位置 `(x+u, y+v)` | 2 | px |
| 立体 3D（`Dic3DRun.frames[i]`） | `np.column_stack([X, Y, Z])` | 3 | world 系（schema §9.2：米） |

**同系同单位是调用者的责任**：本模块不做任何单位换算、不做网格↔DIC 坐标配准（对齐/ICP 是 S4 非目标，§9）。

## 2. 冻结的导入面

`hl3.fea` 的 `__all__` **恰好**为以下四个名字：

| 名字 | 种类 | 一句话 |
|------|------|--------|
| `TriMesh` | frozen dataclass | 节点 + 三角单元的简单网格容器（构造时结构校验） |
| `Projection` | frozen dataclass | 逐点最近邻结果 + `gather`/`scatter_mean` 双向取值 |
| `project_points` | 函数 | `(P, D)` 点列 × `TriMesh` → `Projection`（纯 numpy） |
| `mesh_from_vtk` | 函数 | `.vtk`/`.vtu` 文件 → `TriMesh`（**惰性** import vtk） |

冻结导入路径：`from hl3.fea import TriMesh, Projection, project_points, mesh_from_vtk`。

**import 纪律（冻结）**：`import hl3.fea` 在**只有 numpy** 的环境必须成功——`vtk` 只允许在 `mesh_from_vtk` 函数体内 import（与 `h5py` 在 `hl3.io` 的惰性模式同款）。IR3-G2 的冒烟测试即以此为判据。

## 3. `TriMesh`

```python
@dataclass(frozen=True)
class TriMesh:
    nodes: np.ndarray       # (N, D) f64，D ∈ {2, 3}，N ≥ 1，全部有限
    triangles: np.ndarray   # (T, 3) i64，值域 [0, N)；T ≥ 0

    @property
    def n_nodes(self) -> int: ...
    @property
    def n_triangles(self) -> int: ...
    @property
    def dim(self) -> int: ...           # = D
    def cells_csr(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...
```

冻结条目：

1. `__post_init__` 结构校验（违规 → `ValueError`）：`nodes` 非 `(N, D)`、`D ∉ {2, 3}`、`N == 0`、节点坐标含非有限值、`triangles` 非 `(T, 3)`、索引越界或为负。数组按 `np.asarray(..., dtype=np.float64 / np.int64)` 规范化后存储。
2. **允许** `T == 0`（裸节点云）与重复/退化三角形——`nearest_node` 只消费节点，不消费连通性；未来 `barycentric` 方法落地时可对单元追加更严校验，属追加规则。
3. `cells_csr()` 返回 schema §9.1 `cells/` 三元组：`offsets = arange(0, 3T+1, 3) (i64)`、`nodes = triangles.ravel() (i64)`、`types = full(T, 5, u8)`——**5 = VTK_TRIANGLE**（公开 VTK 单元类型码）。这是 `grid/@kind="fe_mesh"` 落盘与 VTK/Exodus 导出的唯一口径，禁止另写一份。

## 4. `project_points`（S4 冻结的数学定义）

```python
def project_points(
    points: np.ndarray,                # (P, D) f64，D 必须等于 mesh.dim
    mesh: TriMesh,
    *,
    max_distance: float | None = None, # None → 不设门；否则须有限且 > 0
    chunk_size: int = 4096,            # 仅限内存峰值，不得影响任何输出位
) -> Projection: ...
```

冻结条目：

1. **距离与选点公式**（逐位冻结）：对每个坐标全有限的点 i，
   ```
   d2[i, n] = Σ_k (points[i, k] − nodes[n, k])²     # 直接差平方和，f64
   j[i]     = argmin_n d2[i, n]                      # numpy argmin：并列取最小下标
   distance[i] = sqrt(d2[i, j[i]])
   ```
   禁止 ‖a‖²+‖b‖²−2a·b 展开式（可产生负零/精度漂移）；并列平局**恒取最小节点下标**——这是确定性的一部分，不是实现细节。
2. **分块纪律**：`chunk_size` 只允许沿 **P 轴**切块（每块独立算全量节点距离），因此任意 `chunk_size ≥ 1` 的输出与一次算完**逐位相同**；测试必须断言（§10 条 3）。禁止沿 N 轴分块或引入 KD-tree/scipy——未来任何加速都必须保持条 1 的输出逐位不变，且 numpy 仍是唯一必备依赖。
3. **`max_distance` 门**：`distance[i] > max_distance` **严格大于**才判未匹配（等于算匹配上）。`max_distance ≤ 0` 或非有限（除 `None`）→ `ValueError`。
4. **`method` 词表**：本轮无 method 参数，结果恒为 `"nearest_node"`。未来方法（`barycentric` 等）以**追加关键字参数**方式进入，默认值必须复现本文冻结行为。
5. **缺测 → 未匹配，永不抛异常**：点行含任何非有限坐标 → 该点不进入距离计算，直接 `node_index = −1`、`distance = NaN`；超 `max_distance` 门同款。**调用级错误 → `ValueError`**：`points` 非 2 维、`points.shape[1] != mesh.dim`。
6. **空点列不抛**：`P == 0` → 各数组为空的合法 `Projection`（沿用「空网格 → 空结果不抛」全库惯例）；空网格在 `TriMesh` 构造期已被拒（§3 条 1），本函数无需重查。
7. **纯函数**：不读写磁盘、无 RNG、无全局状态；CPU float64；同平台同输入逐位可复现（RUL-02）。

## 5. `Projection`（结果 + 双向取值）

```python
@dataclass(frozen=True)
class Projection:
    node_index: np.ndarray            # (P,) i64；−1 = 未匹配
    distance: np.ndarray              # (P,) f64；未匹配处为 NaN，其余为欧氏距离
    n_nodes: int                      # 网格节点数回显（gather/scatter 的形状依据）
    method: str = "nearest_node"
    max_distance: float | None = None # 门的回显；None = 未设门

    @property
    def matched(self) -> np.ndarray: ...          # (P,) bool == node_index >= 0
    @property
    def n_points(self) -> int: ...
    @property
    def matched_fraction(self) -> float: ...      # 空点列 → 0.0（同 MatchOutcome 口径）
    def gather(self, node_values: np.ndarray) -> np.ndarray: ...
    def scatter_mean(self, values: np.ndarray) -> np.ndarray: ...
```

冻结条目：

1. `isnan(distance) == ~matched` 精确成立；`node_index ≥ 0` 处 `distance` 恒有限（NaN 模式单一来源，同 `StrainField` 纪律）。
2. **`gather`（FE→DIC 方向）**：`node_values (n_nodes,)` → `(P,)` f64；`out[i] = node_values[node_index[i]]`（匹配点），未匹配点为 NaN。`node_values` 自身的 NaN 原样透传（上游缺测不是本层的错误）。形状不符 → `ValueError`。这一方向使逐点残差 `dic − gather(fe)` 一行可算。
3. **`scatter_mean`（DIC→FE 方向）**：`values (P,)` → `(n_nodes,)` f64；节点 n 的值 = 映射到 n 的匹配点中**有限值**的算术平均（非有限 `values[i]` 视为缺测剔除，不是 0）；零个有限贡献者的节点 → NaN。求和顺序冻结为**点下标升序累加**（`np.bincount` 语义），保证逐位可复现。形状不符 → `ValueError`。
4. 多分量场（u/v/w 各一列）以逐列多次调用表达；`(P, K)`/`(N, K)` 批量签名是未来追加槽位，本轮传入非 1 维 → `ValueError`。

## 6. `mesh_from_vtk`（可选 VTK 读入，fail-closed）

```python
def mesh_from_vtk(path: str | os.PathLike) -> TriMesh: ...
```

冻结条目：

1. **惰性依赖**：函数体内才 `import vtk`；缺失 → `ModuleNotFoundError`，消息必须指名 `pip install vtk`（镜像 h5py 缺失时的处置）。模块顶层 import 永不触碰 vtk（§2 import 纪律）。
2. **扩展名分派**：`.vtk` → legacy `vtkUnstructuredGridReader`；`.vtu` → `vtkXMLUnstructuredGridReader`；其他扩展名 → `ValueError`。`.vtp`/PolyData、Exodus、Abaqus inp 是未来追加取值（§9）。
3. **只收三角形**：文件中任何单元类型 ≠ 5（VTK_TRIANGLE）→ `ValueError`，消息列出出现过的违规类型码。不静默跳过、不静默拆分四边形——「简单三角网格」是 S4 的边界，糊过去会让对比结果不可解释。
4. **坐标不降维**：VTK 点恒为 (x, y, z)，返回 `TriMesh` 恒为 `D = 3`，**不**因 z 全零而静默压成 2D。平面对比时由调用者显式二选一：给 DIC 点补 `z = 0`，或自己切掉网格第三列——坐标系语义必须是调用者的明示决定。
5. 读文件本身是 I/O，不在 §4 条 7 的纯函数纪律内；但同一文件两次读入的 `TriMesh` 必须逐位相同。

## 7. Schema 落点映射（资料性；效力归 `hl3.io.hdf5_schema` 与 IR1-F4）

| 契约产物 | HDF5 落点 | 备注 |
|----------|-----------|------|
| `TriMesh.nodes` | `grid/ref_xy (P, D)`，`grid/@kind = "fe_mesh"` | FE 节点即 POI 的分析形态；D ∈ {2,3} 与 schema §9.1 一致 |
| `TriMesh.cells_csr()` | `grid/cells/{offsets, nodes, types}` | `types` 恒为 5（VTK_TRIANGLE），§3 条 3 |
| `Projection.scatter_mean(u)` 等 | `fields/u` 等（节点场） | 写入器加帧轴，可降型 f32（附录 A） |
| `Projection.node_index / distance` | 分析级诊断数据集（命名归 schema 追加流程） | 本轮不落盘也合法；落盘名不得与 §9 既有名冲突 |

## 8. 依赖声明（资料性建议，效力归 pyproject 独占者 IR3-G3）

建议 `pyproject.toml` 追加 extras `fea = ["vtk>=9"]`，与既有 `hdf5 = ["h5py>=3.8"]` 同款可选模式。**不追加也不违反本契约**——vtk 的存在性检测只发生在 `mesh_from_vtk` 运行时。

## 9. S4 非目标（明确不在本契约内）

- 最近表面点投影 / 重心坐标插值（`barycentric` 方法槽位）；点到三角形距离。
- 网格↔DIC 坐标配准（刚体对齐、ICP、基准点拟合）。
- 等效 VSG 同滤波链对比报告、归一化残差 z 判定、实测边界条件导出（B6 后续环，S8）。
- 全局 FE-DIC 求解（RUL-05：v1.x beta，接口另行冻结）。
- 四边形/高阶单元、Exodus/Abaqus inp/PolyData 导入、KD-tree/scipy 加速、GPU 路径。
- 不确定度随投影的传播（`hl3.uq` 词表兼容，留槽）。

## 10. 测试与门挂钩（资料性，供 IR3-F1 定门、IR3-O3 落测试）

1. **手算锚点**：单位正方形两三角网格（4 节点）上若干手算点，`node_index`/`distance` 与手算值逐位相等。
2. **平局确定性**：与两节点严格等距的点恒取最小节点下标。
3. **分块不变性**：`chunk_size ∈ {1, 3, 默认}` 的输出与一次算完逐位相同。
4. **缺测语义**：NaN 坐标点 → `(−1, NaN)` 不抛；`max_distance` 边界上等于算匹配、严格大于算未匹配。
5. **双向取值**：`gather(nv)[matched] == nv[node_index[matched]]` 精确成立；`scatter_mean` 含 NaN 剔除与空节点 NaN 的手算对照。
6. **失败语义**：维度不匹配、空网格构造、越界三角形、非法 `max_distance`、非 1 维 values → `ValueError`；空点列 → 空结果不抛。
7. **确定性**：同输入两次调用逐位相同；无 RNG。
8. **import 冒烟**：无 vtk 环境 `import hl3.fea` 成功（IR3-G2 的 `tests/test_s4_smoke.py` 覆盖）。
9. **VTK 往返**（`pytest.importorskip("vtk")`）：写一个微型三角网格文件读回，`nodes`/`triangles` 逐位相等；含非三角单元的文件 → `ValueError`。

## 11. 兼容性与变更规则（冻结）

1. §2 四个名字在 v1.0 前不得改名、删除或移出 `hl3.fea`。
2. 一切扩展 = 追加关键字专用参数（默认值复现冻结行为）或追加新名字；已冻结的位置参数个数与顺序不变；`method` 词表只增不改。
3. 数值行为变更（加速结构、新投影方法默认化）必须保持 §4 条 1 的输出逐位不变或走 ADR，并过相应门留痕。
4. 冲突消解按 RUL-08：`LEGAL.md` → R2-F1 裁决 → Gate/协议 → schema（`hdf5_schema` + IR1-F4）→ 本文 → 实现代码注释。

## 12. 交接清单

- **IR3-O3**：按本文实现 `src/hl3/fea/**` 与对应测试（§10 条 1–7、9 必须落测试）；新文件加 `SPDX-License-Identifier: Apache-2.0`（ADR-LIC-001 规则 1）。
- **IR3-G2**：`hl3.fea` 面世后冒烟用例从 skip 转真实 import（其报告已预留）。
- **IR3-G3**：§8 的 extras 建议自行取舍；出入以 pyproject 独占权为准。
- **S4 写入器 / validate**：按 §7 表透传；`fe_mesh` 网格的 `@vsg_px` 口径缺口沿用 IR1-F4 G-1 登记，本文不解决。

*IR3-F4 完。本文未改动 `src/**` 任何文件。*
