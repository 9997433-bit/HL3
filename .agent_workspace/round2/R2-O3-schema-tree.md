ACTUAL_MODEL_SLUG: claude-opus-5-thinking-high-fast

# R2-O3 · HDF5 schema 与仓库骨架冻结

> 子代理：R2-O3（opus-fast）· Round 2 · 主攻「schema 落到可执行代码 + 目录树冻结」
> 法律遵守：本轮未下载、未安装、未运行、未观察任何商业 DIC 软件；未 vendor 任何 copyleft 源码。全部产出为原创或依据公开规范。

---

## 0. 一句话结论

`docs/schema-hdf5.md` 从「一份很详细的散文」变成了**可执行的规范**：每个组名、属性、枚举、flags 位在 `src/hl3/io/hdf5_schema.py` 里都有对应常量，配一个写→验→读的往返闭环和 23 个测试；过程中查出并修掉了规范里 **2 处自相矛盾**、**2 处物理上做不到的硬性要求**。目录树按「Python 优先、C++ 后置」冻结，与 R1-O3 §7 的 C++ monorepo 提案的差异已显式记录，不是悄悄改掉的。

---

## 1. 本轮交付

| 文件 | 性质 | 说明 |
|------|------|------|
| `src/hl3/io/hdf5_schema.py` | 新增，约 1 060 行 | schema 常量 + 位域 + 参考写入器 / 读取器 / 验证器 |
| `tests/test_hdf5_schema.py` | 新增，23 测试 | 无依赖层 9 个（无 h5py 也能跑）+ 容器层 14 个 |
| `src/hl3/io/__init__.py` | 新增 | io 子包 |
| `docs/schema-hdf5.md` | 修订 `1.0.0-draft` → `1.0.0-draft.2` | 6 条修订，全部登记在新增的第 14 节 |
| `README.md` | 重写（原文只有一行 `# HL3`） | 中文项目概览 + 英文一句话 + 法律声明 |
| `pyproject.toml` | **合并**，非覆盖 | R2-O1 已建此文件；我只补了缺的包与许可证元数据 |
| `.gitignore` | 新增 | 顺带把误提交的 7 个 `.pyc` 移出索引 |

提交（4 个，均已推送到 `cursor/dic-sota-plan-259d`）：

```
48ac48b chore: ignore build caches, untrack committed bytecode, declare Apache-2.0 metadata
0017572 feat(io): freeze HDF5 schema constants with reference writer, reader and validator
b8f3198 docs(schema): amend HDF5 spec to draft.2 with a full amendment log
a5e4e8f docs: write project README with status, scope and legal notice
```

**未删除、未改写任何其他子代理的代码。** `pyproject.toml` 按派工要求只做增量合并；`src/hl3/__init__.py`、`.github/workflows/ci.yml`、`src/hl3/correlate/`、`src/hl3/stereo/` 一律未动。

---

## 2. 冻结目录树

快照点：`a5e4e8f`。标 `[O1]` / `[O2]` / `[G2]` / `[G3]` 者为其他子代理产出，此处仅登记不改动；标 `[O3]` 为本轮产出。

```
HL3/
├─ README.md                          [O3] 项目概览（中）+ 一句话（英）+ 法律声明
├─ LICENSE                            [G1] Apache-2.0（ADR-LIC-001）
├─ pyproject.toml                     [O1 建 / O3 合并] setuptools + src 布局
├─ .gitignore                         [O3]
│
├─ .github/
│  └─ workflows/ci.yml                [G3] CPU-only 单测（无 GPU、无 Wine）
│
├─ docs/
│  └─ schema-hdf5.md                  [O3 修订] .hl3 / .hl3z 格式规范（CC-BY-4.0）
│
├─ src/
│  ├─ hl3/
│  │  ├─ __init__.py                  __all__ = capture, correlate, io, stereo
│  │  ├─ capture/
│  │  │  ├─ __init__.py               [G3]
│  │  │  └─ mock.py                   [G3] 确定性无硬件采集
│  │  ├─ correlate/
│  │  │  ├─ __init__.py               [O1]
│  │  │  └─ icgn.py                   [O1] CPU 一阶 IC-GN 参考相关器（ZNSSD）
│  │  ├─ io/
│  │  │  ├─ __init__.py               [O3]
│  │  │  └─ hdf5_schema.py            [O3] ★ schema 常量 + 参考读写器 + 验证器
│  │  └─ stereo/
│  │     ├─ __init__.py               [O2]
│  │     ├─ calibrate.py              [O2]
│  │     └─ triangulate.py            [O2] 投影矩阵、基础矩阵、四档三角化
│  └─ tests/
│     └─ test_mock_capture.py         [G3] ⚠ 位置见 §6 问题 1
│
├─ tests/
│  ├─ test_env_guards.py              [G3]
│  ├─ test_hdf5_schema.py             [O3] ★ 23 测试
│  ├─ test_icgn_synth.py              [O1]
│  └─ test_stereo_synth.py            [O2] ⚠ 快照时 1 项失败，属 O2 在途工作
│
└─ .agent_workspace/                  规划工作区，不随发行包分发
   ├─ LEGAL.md  MASTER_PLAN.md  PROGRESS.md  ROUND1_BRIEF.md
   ├─ research/{oss_dic_landscape,vic_public_feature_baseline}.md
   ├─ round1/  R1-F1…F4, R1-O1…O3, R1-G1…G3 + scripts/synth_speckle.py
   └─ round2/  R2-F3, R2-F4, R2-G1…G3, R2-O1, R2-O3(本文)
               + scripts/{interpolation_scurve,noise_floor_stub}.py
```

规模：44 个受管文件，Python 约 4 350 行。已提交测试 55 项全绿（不含 O2 在途的 `test_stereo_synth.py`）。

### 2.1 与 R1-O3 §7 monorepo 提案的差异（显式记录，不是悄悄改的）

R1-O3 §7 提出的是一棵 C++ 优先的 monorepo：`cpp/include/hl3/{core,io,geom,calib,corr,strain,uq,compute,plugin}`、`gpu/{cuda,vulkan,hip}`、`python/{bindings,src/hl3}`、`apps/{hl3-cli,hl3-studio,hl3-snap,hl3-gauge}`、`plugins/`、`spec/`、`benchmarks/`、`tools/codegen/`。

Round 2 实际长出来的是一棵**纯 Python 树**。这不是执行偏差，而是 Round 1 遗留冲突 2（「GPU 目标 vs 本环境」）的必然结果：本环境 4 vCPU、无 GPU、无 CUDA，C++/CUDA 树在这里既编不了也测不了，先建一棵空骨架只会得到一堆无人验证的目录。

**冻结决定**：以 `src/hl3/<子系统>/` 为当前唯一真源，按下表向 R1-O3 §7 演化。C++ 树在**有可编译可测的内容时**才建，不预先占位。

| R1-O3 §7 提案 | 当前 | 演化路径 |
|---------------|------|----------|
| `cpp/include/hl3/corr/` | `src/hl3/correlate/icgn.py` | Python 版是规范实现；C++ 版落地时须逐位对拍它 |
| `cpp/include/hl3/io/hdf5.hpp` | `src/hl3/io/hdf5_schema.py` | 常量表将来由 `tools/codegen/` 从**单一 YAML 真源**同时生成 Python 与 C++ —— R1-O3 §7 已警告过「三处手写同一张表必然漂移」，本轮的常量表就是那个真源的第一个消费者 |
| `python/src/hl3/io_ref/` | `src/hl3/io/hdf5_schema.py` 的无依赖层 | 已满足「纯 h5py、零 C++ 依赖」的要求；将来若拆包，拆的是包名不是逻辑 |
| `spec/hl3-schema/1.0/*.json` | 尚无 | JSON Schema 由常量表生成，Round 3 |
| `spec/conformance/` | 尚无目录，但生成器已有 | `write_synthetic_hl3()` 已能产出「2D 完整」用例；缺其余 5 类 |
| `gpu/`、`apps/`、`plugins/`、`benchmarks/` | 尚无 | 有内容再建 |

`.gitignore` 已为 `spec/conformance/**/*.hl3` 预留例外：一致性样例是**要**入库的产物，其余 `.hl3` 一律忽略。

---

## 3. schema 修订（`draft` → `draft.2`）

6 条全部登记在 `docs/schema-hdf5.md` 第 14 节。**没有一条反转 R1 的语义决定** —— flags 位分配、路径树、必填/应当级别、坐标与单位约定一律未动。其中 4 条是实现时撞上的硬问题：

| # | 问题 | 为什么必须改 |
|---|------|-------------|
| **A-1** | §3 写「`@hl3_schema_version` 必须为 `"1.0.0"`」，但文首写版本是 `1.0.0-draft`，§12.1 又写「冻结前一律 `1.0.0-draft.N`」 | 三处互斥。照 §3 原文写文件，等于宣称已冻结，§12.1 的四条冻结条件立即失效 |
| **A-3** | §3 要求 `@uuid` 必须是 **UUIDv4** | 与铁律 L4「同输入同配置逐位相同」直接冲突：v4 是随机的，同一算例跑两次得到两个不同文件，一致性样例根本无法逐位比对。改为「应当 v4，确定性写入器可用 v5」 |
| **A-4** | 附录 A 把 **zstd-3** 定为默认压缩 | zstd 在 HDF5 里是**注册过滤器（id 32015）不是内置过滤器**。原装 h5py 打不开 zstd 数据集 —— 也就是说 §12 承诺「任何人都能读的一致性样例」在原文规则下事实上读不了。改为：默认值可降级，但 `@compression` 必须如实写明实际编码；一致性样例应当只用内置过滤器 |
| **A-2** | §2.5 硬性要求 **BLAKE3-256** | BLAKE3 不在任何语言的标准库里。硬性要求它，「零依赖参考读取器」这个卖点就不成立。改为允许 `blake2b-256` 降级，且**必须如实写进 `@hash_algo`**；算法不同的哈希报「无法校验」而非「不匹配」 |

A-5 是新增第 13 节（规范条款 ↔ 参考实现符号映射），A-6 是补 SPDX 标识。

**一以贯之的原则：一切降级都写进文件，不写进口头约定。** 两处降级（哈希、压缩）都做成了文件里可查的属性，而不是「反正大家都知道」。

---

## 4. 参考实现要点

### 4.1 依赖分层 —— 为什么值得费这个劲

常量、位域、路径助手、规范化 JSON、哈希**只依赖标准库**。没有 h5py、甚至没有 numpy，`import hl3.io.hdf5_schema` 也必须成功；只有三个真正碰文件的入口需要 h5py，缺失时抛 `Hdf5Unavailable` 并由 `skip_reason()` 给出人话原因。

理由不是洁癖：**schema 的定义本身不应该有安装门槛**。如果第三方要先装齐二进制依赖才能查到「flags 的 bit 6 是什么」，那这个「公开格式」就只公开了一半。9 个无依赖测试专门守这条线。

### 4.2 合成算例 —— 位移和应变都有闭式解

均匀单轴拉伸叠加刚体平移：

```
u(x, y, f) = tx·f + ε·f·(x − x₀)
v(x, y, f) = ty·f − ν·ε·f·(y − y₀)
```

于是 `exx = ε·f`、`eyy = −ν·ε·f`、`exy = 0` **逐点精确成立**。往返读写可以逐位断言，不需要任何外部数据集，也不需要相关器参与 —— 这条 IO 回归链与 R2-O1 的 ICGN 内核完全解耦，任一方回归时不会误伤另一方。默认算例 3 帧 × 20 点，文件 50.6 KiB。

位移单位写 `"px"`：合成算例没有标定，就不假借 1 px = 1 mm。

### 4.3 验证器不是空跑

`validate_file()` 覆盖必填属性、枚举合法性、交叉引用（`@sequence` / `@aoi` / `@calibration` 指向的实体是否存在）、形状一致性、`ref_xy` 末维 ∈ {2,3}、flags 保留位、`dist` 长度与 `@model` 是否匹配、立体分析是否给了 `w` 和 `w_std`。

6 个参数化测试故意把合法文件改坏（删根属性、`@space` 写成 `"mm"`、`@type` 写成 `"4d"`、`@sequence` 指向不存在的序列、`@tensor` 写成未知值、删 `fields/v`），断言验证器每一种都能抓到。

`strict` 模式在合成样例上报 1 条 SHOULD 级缺失（`@git_sha`：参考写入器不是内核，没有内核 SHA 可写）。这条**故意保留**并写成测试 —— 它证明 strict 模式不是空跑。

### 4.4 验证结果

```
$ python -m hl3.io.hdf5_schema selftest
OK  schema=1.0.0-draft.2  hash_algo=blake2b-256
OK  往返一致：u/v/exx  形状=(3, 20)  vsg=57.0 px  空间单位=px
OK  strict 违规数=1  文件体积=50.6 KiB

$ python -m pytest -q tests/test_hdf5_schema.py
23 passed

$ python -m ruff check src/hl3/io tests/test_hdf5_schema.py
All checks passed!

$ python -m pip wheel --no-deps -w /tmp .
hl3-0.0.1.dev0-py3-none-any.whl
  License: Apache-2.0 · License-File: LICENSE
  Provides-Extra: hash, hdf5, test
  含 hl3.{capture, correlate, io, stereo} 四个子包
```

---

## 5. 给 O1 / O2 的落盘接口

两位的内核目前把结果留在内存里。要落进 `.hl3`，用这些常量而不是字符串字面量，散文与代码就不会各自漂移：

```python
from hl3.io import hdf5_schema as hs

# 位移场（R2-O1）
hs.SG_FIELDS, hs.DS_U, hs.DS_V, hs.DS_ZNCC, hs.DS_FLAGS
hs.A_SPACE                      # 未标定 2D 必须写 "px"
hs.FieldFlags.CONVERGED         # 收敛位
hs.FieldFlags.EDGE_CLAMPED      # 子区触边
hs.FieldFlags.LOW_CONTRAST      # 梯度能量不足
hs.valid_mask(flags)            # §9.5 判据，别各写各的

# 立体（R2-O2）
hs.DS_W, hs.DS_X, hs.DS_Y, hs.DS_Z, hs.DS_DISPARITY
hs.FieldFlags.EPIPOLAR_REJECT   # 极线残差超限
hs.FieldFlags.TRIANGULATION_ILL # 三角化条件数差
hs.DISTORTION_PARAM_COUNT       # @model → dist 长度，验证器会查
hs.DS_COVARIANCE                # 标定协方差；缺了就不能用 propagated UQ

# 通用
hs.config_hash(cfg)             # 规范化 JSON 的哈希，可复现
hs.vsg_size_px(w, step, subset) # (w-1)*step + subset
```

三条约定，验证器会强制：

1. **`fields/u` 的 `@space` 必须显式写。** 没有标定就写 `"px"`，不允许假借 1 px = 1 mm。
2. **立体分析的 `@calibration` 与 `w`、`w_std` 都是必填。** 只给 u/v 的「伪 3D」文件不合规。
3. **不得置位 flags 的 bit 12–23**（规范保留）。插件私有位在 24–31。

---

## 6. 发现的问题（Round 3 必须处理）

**1 · `src/tests/` 位置不对，本地 `pytest` 收不到。** `pyproject.toml` 的 `testpaths = ["tests"]` 让裸跑 `pytest` 收集 55 项，CI 因为显式写了 `pytest -q tests src/tests` 才收到 86 项。也就是说 `src/tests/test_mock_capture.py` 在开发者本地是**静默不跑**的。建议移到 `tests/test_mock_capture.py`，删掉 CI 里的 `src/tests` 参数。（G3 的文件，本轮未擅动。）

**2 · CI 不装 h5py，我这 23 个测试里的 14 个在 CI 里静默跳过。** 降级路径本身是设计好的（`pytest.importorskip`），但「设计成会跳过」和「一直在跳过」是两回事 —— 目前 CI 从未真正验证过容器读写。一行修复：

```diff
-        run: python -m pip install --upgrade numpy pytest
+        run: python -m pip install --upgrade numpy pytest h5py
```

（G3 的文件，本轮未擅动。）h5py 有 manylinux wheel，不需要编译，CPU-only 约束不受影响。

**3 · 一致性样例只覆盖 6 类里的 1 类。** §12 列了最小合法 / 2D 完整 / 3D 完整 / 边界 / 非法 / 前向兼容六类，目前只有「2D 完整」有生成器。**「前向兼容」那一类最关键也最没被验证**：规范 §11.2 条 3 要求「改写文件时必须原样保留未识别的 group / dataset / attribute」，而参考实现现在**根本没有改写路径**，这条规则一行代码都没实现过。生态碎片化就是从这里开始的。

**4 · 标定、内嵌图像、模拟量、`/derived`、`/thumbnails` 只有常量没有写入器。** O2 的标定一落地就会第一个撞上 `/calibrations` 的写入。

**5 · Zarr v3（附录 C）零实现。** `hl3 convert` 的无损往返未验证，「双容器同构」目前只是承诺。

**6 · `pyproject.toml` 用的是 `license = { text = "Apache-2.0" }`（旧式）。** 新版 setuptools 已弃用该写法。等最低 setuptools 提到 77 再切 PEP 639 的 `license = "Apache-2.0"` —— 现在切会让本环境的 setuptools 68 直接报错。

**7 · `1.0.0` 冻结条件一条都没满足。** §12.1 的四条（参考实现过全部一致性用例、**外部**独立读取器、iDICs Challenge 跑通、3D 实测不确定度链路）目前 0/4。**不得**去掉 `-draft` 后缀 —— 过早冻结会把上面这些窟窿变成永久的兼容性负担。

---

## 7. 与 Round 1 遗留冲突的对应

| R1 遗留冲突 | 本轮进展 |
|-------------|---------|
| 2 · GPU 目标 vs 本环境 | 目录树按「CPU/Python 为规范实现，C++/GPU 有内容再建」冻结，见 §2.1 |
| 3 · 吞吐口号需统一协议 | 本轮**未产出任何性能数字**；README 明写吞吐未经测量 |
| 7 · 尚无相关器代码 | O1 已落地；本轮补上它的落盘接口（§5） |
| R1-O3 §9 开放问题 3「Schema 冻结时机」 | 维持「跑通 Challenge 前不冻结」，见 §6 问题 7 |
| R1-O3 §9 开放问题 6「DVC 前向兼容」 | 已落实：`ref_xy` 末维允许 2 或 3，验证器强制检查 |

---

## 8. 法律与合规自查

- 未下载、未安装、未运行、未反编译任何商业 DIC 软件；未申请评估密钥。
- 未 vendor、未改写、未翻译 OpenCorr 或任何 MPL/GPL 项目的源文件。本轮代码全部为原创。
- HDF5 布局、坐标约定、畸变模型标识依据的是 HDF5 规范、OpenCV 公开相机模型与 VTK/Exodus 公开数据模型，均为公开标准。
- 依据 ADR-LIC-001 执行规则 1，已给新增源文件加 `SPDX-License-Identifier: Apache-2.0`、给 `docs/schema-hdf5.md` 加 `CC-BY-4.0`；依据规则 2，包元数据已声明 Apache-2.0。
- README 明确声明与 Correlated Solutions 无关联、非衍生、非逆向，并附英文摘要。
