ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR3-F3 · S4 社区版 GUI 基线范围：位移云图查看器 + 多边形 AOI（`src/hl3/gui/**`）

- **状态**：FROZEN（S4 起生效）。推翻冻结条目需父调度器书面 ADR 并在 `MASTER_PLAN.md` 留痕（FRZ 纪律）。
- **本文冻结的对象**：S4 社区版 GUI 的**范围边界**（做什么/不做什么）、技术选型裁决、模块布局、导入纪律、AOI 侧车格式、无头测试契约。
- **本文不冻结的对象**：控件摆放、快捷键全集、配色与字号等观感细节（实现自由度）；`hl3.viz` 无头渲染 API（IR3-O2 独占，见其 `IR3-O2-viz.md`）；FEA 契约（IR3-F4）；伞式 `hl3` 命令行（IR3-F2）。
- **约束对象**：IR3-O3（`src/hl3/gui/**` 与对应测试的实现者）。协调对象：IR3-O2（viz）、IR3-F2（CLI 契约）、IR3-G3（CI 与 `viz` extra）。
- **法务与红线**：RUL-06——我们从未合法见过 VIC 的 UI，任何"对齐 iris"表述被永久禁止；GAP-1（iris 级可视化）**保持开放**，本文交付物不改变该结论。`src/ tests/ docs/ benchmarks/` 四目录不得出现竞品产品字符串（R3-F2 L-2 正则；本文位于 `.agent_workspace/` 不在扫描面内）。IR3 派工红线：无 GPU 内核、无相机 SDK、无显微镜——GUI 不含任何采集/实况/显微功能。

---

## 1. 定位：基础查看器 + AOI 编辑，明确不是 iris 级

R3-F4 路线图 S4 工作项原文："社区版 GUI 基线（基础查看器 + AOI 编辑，明确不是 iris 级）"。本文把这句话变成可验收的边界：

1. **只做两件事**：(a) 打开 `.hl3` 文件、按帧查看位移场彩色云图；(b) 在参考图像坐标系里画/改多边形 AOI 并保存。
2. **诚实标注**：matplotlib 交互控件是功能级而非产品级；这是**刻意的基线**，产品级打磨按 GAP-1 留给 S8 之后的 beta 用户回路。README 与 docstring 中的措辞必须是"basic viewer"口径，禁止"出版级/专业级/对标 X"。
3. GUI 是内核之上的**薄壳**（R1-F3 #9 结构性原则）：不含任何算法。相关、应变、UQ、验证逻辑一概不进 `hl3.gui`。

## 2. 技术选型（裁决，冻结）

**裁决：matplotlib 为唯一渲染与交互层，窗口壳用 matplotlib 自带的 `TkAgg` 后端（tkinter）。不引入 Qt、不做 Web 前端。**

| 层 | 选型 | 理由 |
|----|------|------|
| 渲染 | matplotlib（`viz` extra 已有，见 `pyproject.toml`） | 零新增依赖；与 IR3-O2 无头渲染同库，S4+1 可合流 |
| 窗口/事件循环 | tkinter（标准库）经 `TkAgg` 后端 | 零 pip 依赖；三平台自带（Linux 发行版或需系统包 `python3-tk`，写入文档即可） |
| 多边形交互 | `matplotlib.widgets.PolygonSelector` | 现成的顶点绘制/拖拽，不自研控件 |
| 帧切换 | 键盘事件（`mpl_connect("key_press_event")`）或 `matplotlib.widgets.Slider` | 二选一或并存，实现自由 |

Qt6 曾在 R2-F3 §17 出现为 v1 方向，但 Qt 绑定的依赖体量与许可审计（PyQt GPL / PySide LGPL）需要独立 ADR-LIC 条目——S4 不开这个口子。**扩展规则**：换 GUI 工具包 = 推翻本裁决，需 ADR。

依赖纪律（冻结）：**不新增 `gui` extra**。GUI 复用现有 `viz = ["matplotlib"]` extra；tkinter 不可经 pip 安装，缺失时按 §5 退出码 2 处理并给出系统包提示。

## 3. 模块布局与导入纪律（冻结）

| 文件 | 内容 |
|------|------|
| `src/hl3/gui/__init__.py` | 仅 docstring（含 SPDX 头）。包导入无副作用；**在没有 matplotlib、tkinter、h5py 的环境里 `import hl3.gui` 必须成功**（与 `hl3.io.hdf5_schema` 依赖分层同口径）。 |
| `src/hl3/gui/aoi.py` | **纯逻辑** AOI 模型：多边形列表（role + 顶点数组）、合法性检查（≥3 顶点、role 枚举）、侧车 JSON 序列化/反序列化。只允许 import 标准库 + numpy + `hl3.io.hdf5_schema` 的 `canonical_json`。**禁止** import matplotlib/tkinter/h5py。 |
| `src/hl3/gui/view.py` | `main(argv: Sequence[str] \| None = None) -> int` + `__main__` guard；查看器类。matplotlib/tkinter 在函数体内延迟 import，缺失时抛/捕获为操作性错误。 |

导入纪律（冻结）：`hl3.gui.*` 只允许 import 标准库、numpy、matplotlib（运行时延迟）、`hl3.io.hdf5_schema` 公开面（`read_analysis`、`AnalysisData`、`valid_mask`、`canonical_json`、`Hdf5Unavailable`、常量）。**禁止直接 import h5py**——读 `.hl3` 只经 `read_analysis`；§4.2 的可选写回是唯一例外（届时经 h5py 追加，但必须走延迟 import 并复用 `Hdf5Unavailable` 语义）。禁止 import `hl3.correlate/stereo/strain/uq/pipeline`（薄壳原则）。

**`hl3.viz` 协调（裁决）**：IR3-O2 与本项并行落地，为避免合并顺序耦合，S4 内 `hl3.gui` **允许但不要求**复用 `hl3.viz`；若两者各自实现了"标量场→彩色散点"的绘制，S4+1 必须去重合流到 `hl3.viz`（登记为技术债，写入 `IR3-O3-fea-gui.md`）。

## 4. 功能范围（冻结）

### 4.1 位移云图查看器（MUST）

1. 经 `read_analysis(path, analysis_id)` 打开 `.hl3`；`--analysis` 缺省时取名字序第一个分析（与参考读取器同语义）。
2. 显示字段：`u`、`v`、`mag`（`hypot(u, v)`）。3D 分析若含 `w` 则追加 `w`。切换方式实现自由，但 `--field` 初值必须生效。
3. 渲染为**散点云图**（`ref_xy` 上着色，对 `regular`/`scattered`/`fe_mesh`/`marker_set` 一律成立）；`kind="regular"` 时可选升级为规则图像/`tripcolor`，不强制。
4. **有效性判据单一事实源**：只绘制 `hl3.io.hdf5_schema.valid_mask(flags)` 为真的点（§9.5）。GUI 不得自行解读 flags 位。无效点不画或画为中性底色，二选一。
5. 色条必须存在，标签含单位，单位**只**取自 `fields/u@space`（`px` 或 `m`），不得猜测或换算。
6. 帧导航：初始帧 = 最后一个已解算帧（形变最大、信息量最大）；`--frame N` 覆盖；左右方向键或滑条切换。标题显示 `analysis_id`、`frames/index` 的真实帧号与当前字段——**不含时间戳或随机内容**（确定性铁律 L4 在 GUI 标题同样生效）。
7. 色图默认用感知均匀色图（matplotlib 默认 viridis 即可）；色图名不冻结。

### 4.2 多边形 AOI 编辑（MUST，写回为 SHOULD)

1. 在与 `ref_xy` 同一参考图像坐标系里，用 `PolygonSelector` 绘制/编辑多边形；支持 ≥1 个 `role="outer"` 与 ≥0 个 `role="hole"`（枚举与 schema §8.2 一致）；每个多边形 ≥3 顶点，float64。
2. **保存为侧车 JSON（MUST）**：`--save-aoi PATH` 或界面动作写出侧车文件，内容经 `canonical_json` 序列化（字节级确定），格式冻结如下：

```json
{
  "hl3_aoi_sidecar": "1.0",
  "label": "…",
  "mode": "static",
  "sequence": "seq0",
  "reference_camera": "cam0",
  "polygons": [
    {"role": "outer", "vertices": [[x, y], "…"]},
    {"role": "hole", "vertices": [[x, y], "…"]}
  ]
}
```

顶点序按 schema §8.2 约定逆时针为正向；`sequence`/`reference_camera` 从所查看分析的 AOI/相机引用继承。侧车内**禁止**出现绝对路径、时间戳、主机名（确定性 + 隐私）。

3. **写回 `.hl3`（SHOULD，非 v0 验收门）**：若实现，只允许**追加**新的 `/aois/<新 id>` 组（含 `@label/@sequence/@reference_camera/@mode` 与 `polygons/<k>/`），禁止覆盖或删除任何既有组（规范 §11.2 条 3 原样保留义务）；必须更新根 `@modified_utc` 并向 `/provenance/log` 追加一条 `canonical_json` 事件。做不到这三点就不做写回。
4. AOI 编辑不触发任何重算：GUI 不调用相关器。侧车/写回的消费方是 CLI 与 pipeline（IR3-F2 契约的事）。

## 5. 调用面（冻结）

```text
python -m hl3.gui.view [-h] [--analysis ID] [--field {u,v,w,mag}] [--frame N] [--save-aoi PATH] path
```

- argparse 设 `prog="python -m hl3.gui.view"`（与 IR2-F4 §2 同理）。
- 退出码：`0` 正常关窗退出；`2` 没能启动——用法错误（argparse 自身）、文件不存在/不可读/非 HDF5（`OSError`）、h5py 缺失（`Hdf5Unavailable`）、matplotlib/tkinter/显示环境缺失。操作性错误单行走 stderr，格式 `error: <原因>`（tkinter 缺失时附系统包提示）。**没有退出码 1**：GUI 不做合规判定，那是 `hl3.cli.validate` 的职责。
- S4 伞式命令 `hl3 view` 若设立，必须路由到本 `main`——归 IR3-F2 契约裁决，本文只预留接线点。
- 库函数**不得**自行调用 `plt.show()`/`mainloop()`；事件循环只在 `main` 的交互路径里启动，且在 `--save-aoi` 等可无头完成的路径上不启动（可测性前提）。

## 6. 无头环境与测试契约（交给 IR3-O3）

本云环境**无显示服务器**：交互路径在此处不可人工验证——这正是 §3 逻辑/渲染分层是冻结项而非建议的原因。测试要点（`tests/` 下 IR3-O3 自有测试文件；**不得**改动 IR3-G2 独占的 `tests/test_s4_smoke.py`）：

1. 导入冒烟**不得** skip：`import hl3.gui`、`import hl3.gui.aoi` 在无 matplotlib/tkinter/h5py 时必须成功。
2. AOI 模型往返：构造多边形 → 侧车 JSON → 解析回来逐位一致；同一模型两次序列化字节相同；非法输入（<3 顶点、未知 role）报错。
3. 渲染冒烟走 `matplotlib.use("Agg")`：用 `write_synthetic_hl3` 生成算例，构造 Figure 并断言绘制点数 = `valid_mask` 真值数；翻转一个点的 `MASKED` 位后重新绘制，点数减一（有效性判据接线证明）。带 `pytest.mark.skipif`（h5py 或 matplotlib 缺失时跳过，口径同 `test_hdf5_schema.py`）。
4. 退出码 2 路径：不存在的文件；坏参数。禁止在测试里启动 Tk 事件循环。

## 7. 非目标（S4 明确不做，冻结）

动画/视频导出、4K/PDF 出版级导出（无头出版出图归 `hl3.viz`/S8）、FEA 场叠加显示（FEA 归 IR3-F4/IR3-O3 的 fea 模块，GUI 叠加是 S4+1 以后的事）、3D 表面/点云视图、暗色主题与绘图模板、工程管理界面（新建/合并工程）、种子点编辑、椭圆/裂纹缝 AOI 工具（R1-F3 #14 的后续项）、图像底图显示（合成算例 `@storage="none"` 无图像；有图像时的底图叠加留待 S4+1）、实况采集/实时显示（S6，需硬件）、任何显微镜功能（RUL-04）、i18n、插件体系。

## 8. 扩展规则

允许：追加带默认值的旗标（默认行为复现本文契约）；追加只读显示量（如 `zncc`、`sigma` 场）——它们走与位移相同的 §4.1 管线；侧车 JSON 追加**可选**键（`"hl3_aoi_sidecar"` 版本号相应递增次版本）。不允许（需 ADR）：更换 GUI 工具包；改变退出码语义；侧车既有键改名/改语义；GUI 内出现任何算法实现。

## 9. 冲突消解

按 RUL-08：`LEGAL.md` → Gate/协议 → `docs/schema-hdf5.md` 与 `hl3.io.hdf5_schema`（数据语义，含 §8.2 AOI 与 §9.5 有效性）→ IR3-F2（伞式 CLI 调用面）→ 本文（GUI 范围与选型）→ `IR3-O3-fea-gui.md` 与实现注释。AOI 数据语义若与本文示例有出入，以 schema 为准；GUI 范围边界与选型以本文为准。

*IR3-F3 完。本文未改动 `src/**` 任何文件。*
