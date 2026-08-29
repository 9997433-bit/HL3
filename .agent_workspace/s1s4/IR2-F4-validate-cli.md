ACTUAL_MODEL_SLUG: claude-fable-5-thinking-xhigh

# IR2-F4 · `python -m hl3.cli.validate` 契约（S3）

- **状态**：FROZEN（S3 起生效）。推翻冻结条目需父调度器书面 ADR 并在 `MASTER_PLAN.md` 留痕（FRZ 纪律）。
- **本文冻结的对象**：S3 结构验证 CLI 的**调用面**——模块路径、参数、退出码、输出流约定、导入纪律。
- **本文不冻结的对象**：检查项本身的内容与措辞（效力归 `hl3.io.hdf5_schema.validate_file` 与 docs/schema-hdf5.md §12）；S4 `hl3` 伞式命令行（Impl-R3）。
- **约束对象**：IR2-O3（`src/hl3/cli/validate.py` 与 `tests/test_validate.py` 的实现者）；Impl-R3 的 S4 CLI（`hl3 validate` 子命令必须路由到本文的 `main`）。
- **法务**：纯包装器，不新增任何算法；不接触 VIC 二进制或专有细节；显微镜零实现（RUL-04/06，`LEGAL.md`）。

---

## 1. 定位：薄包装，单一事实源

规范 §12 要求参考实现提供 `hl3 validate file.hl3 [--strict]`。截至 IR1，唯一入口是 Python 函数 `hl3.io.hdf5_schema.validate_file(path, strict=...)`（见 docs/schema-hdf5.md §12「实现现状」段）。本文把它包装成可从 shell 调用的模块：

```bash
python -m hl3.cli.validate path.hl3            # 结构 + 必填字段 + 交叉引用完整性
python -m hl3.cli.validate path.hl3 --strict   # 追加 SHOULD 级检查
```

**铁律（冻结）**：CLI 自身**不得实现任何检查**。全部检查逻辑、违规文案、strict 语义都只存在于 `validate_file` 一处；`validate_file` 未来长出哈希校验与单位可解析性检查（§12 完整版）时，CLI 自动继承，零改动。CLI 只负责三件事：参数解析、把违规列表打印出来、把结果折算成退出码。

## 2. 模块布局（冻结）

| 文件 | 内容 |
|------|------|
| `src/hl3/cli/__init__.py` | 仅 docstring（含 SPDX 头）。包导入无副作用、不需要 h5py、不预先 import 子模块。 |
| `src/hl3/cli/validate.py` | `main(argv: Sequence[str] | None = None) -> int` + `if __name__ == "__main__": raise SystemExit(main())`。 |

- `main` 是唯一公开入口（`__all__ = ["main"]`），**返回**退出码而不是自己调 `sys.exit`——测试可以进程内调用 `main([...])` 并断言返回值。argparse 在用法错误时自行 `SystemExit(2)`，属于允许的例外。
- argparse 须设 `prog="python -m hl3.cli.validate"`，保证 `-h` 文本与真实调用方式一致（经 `-m` 运行时 `sys.argv[0]` 是文件路径，不可用作 prog）。
- `import hl3.cli.validate` 在**没有 h5py 的环境里必须成功**（与 `hdf5_schema` 的依赖分层一致）；h5py 只在 `validate_file` 运行时经由 `Hdf5Unavailable` 表达缺失。

**导入纪律（冻结）**：`hl3.cli.validate` 只允许 import 标准库 + `hl3.io.hdf5_schema` 的公开面（`validate_file`、`Hdf5Unavailable`）。禁止直接 import h5py、numpy 或 `hl3` 其余子包。

## 3. 命令行界面（冻结）

```text
python -m hl3.cli.validate [-h] [--strict] path
```

| 参数 | 语义 |
|------|------|
| `path`（必填，恰好一个） | 待验证的 `.hl3` 文件路径，原样传给 `validate_file(path, ...)`。 |
| `--strict` | `validate_file(path, strict=True)`；缺省 `strict=False`。 |
| `-h` / `--help` | argparse 默认帮助。 |

无 `--version`、无短旗标、无多文件。扩展规则见 §7。

## 4. 输出契约（冻结）

- **stdout**：每条违规单独一行，**逐字**输出 `validate_file` 返回的字符串（如 `/analyses/ana_01: 缺必填属性 @config_hash`），不加前缀、不重排、不去重、不翻译。随后一行汇总：
  - 零违规：`OK <path>`
  - N 条违规：`FAIL <path>: <N> 条违规`
- **stderr**：只承载「验证没跑起来」的操作性错误，单行，格式 `error: <原因>`（h5py 缺失时原因即 `Hdf5Unavailable` 的消息原文）。
- 编码 UTF-8。**确定性（铁律 L4）**：同一文件 + 同一旗标 → stdout 逐字节相同。`validate_file` 按 h5py 的名字序遍历组，本身确定；CLI 不得引入时间戳、随机序或环境相关内容。

## 5. 退出码（冻结）

| 码 | 含义 | 触发 |
|----|------|------|
| 0 | 验证已运行，零违规 | `validate_file` 返回空列表 |
| 1 | 验证已运行，≥1 条违规 | `validate_file` 返回非空列表 |
| 2 | 验证没能运行 | 用法错误（argparse）；文件不存在/不可读/不是 HDF5 容器（`OSError`）；h5py 缺失（`Hdf5Unavailable`） |

**裁决（冻结）**：打不开的文件是退出码 2 而不是 1。理由：违规报告的唯一事实源是 `validate_file` 的返回列表，CLI 不得自行编造违规条目（§1 铁律）；「garbage 文件算不算不合规」若未来有定论，应在 `validate_file` 内长成报告级检查，届时退出码 1 自动随之成立，CLI 零改动。

## 6. 参考实现骨架（资料性，非逐字冻结）

```python
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hl3.cli.validate", description=...)
    parser.add_argument("path")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        problems = validate_file(args.path, strict=args.strict)
    except Hdf5Unavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: 无法打开 {args.path}: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    if problems:
        print(f"FAIL {args.path}: {len(problems)} 条违规")
        return 1
    print(f"OK {args.path}")
    return 0
```

## 7. 非目标与扩展规则

**S3 明确不做**：哈希校验与单位可解析性（§12 完整版，待 `validate_file` 生长）；`--json` 机器可读输出；多文件/glob；`hl3 diff`、`hl3 repack`；伞式 `hl3` console script（Impl-R3 的 S4 交付，落地时须在 `pyproject.toml` `[project.scripts]` 注册并路由到本 `main`，`python -m` 形式永久保留）。

**扩展只允许**：追加带默认值的旗标（默认行为复现本文契约）；退出码 0/1/2 的语义不得改变；stdout 违规行的「逐字透传」不得改变。

## 8. 交给 IR2-O3 的测试要点（`tests/test_validate.py`）

1. 模块导入测试**不得** skip（无 h5py 也必须能 import）；运行类测试用 `pytest.mark.skipif(skip_reason() is not None, ...)`，与 `tests/test_hdf5_schema.py` 同口径。
2. 合规路径：`write_synthetic_hl3(tmp) → main([str(p)]) == 0`，stdout 恰为 `OK <path>` 一行；`--strict` 对合成算例同样为 0（selftest 已保证 strict 违规数为 0）。
3. 违规路径：写合成文件后用 h5py 删一个必填属性（如根 `@hl3_schema_version`）→ 返回 1，stdout 含 `validate_file` 的对应违规原文与 `FAIL` 汇总行。
4. 退出码 2：不存在的路径；非 HDF5 的假文件（写几个字节的文本）。
5. 至少一个 subprocess 冒烟：`[sys.executable, "-m", "hl3.cli.validate", path]`，验证 `-m` 接线（`__init__.py`、`__main__` guard）真实可用；其余用例走进程内 `main([...])` + capsys。

## 9. 冲突消解

按 RUL-08：`LEGAL.md` → Gate/协议 → `hl3.io.hdf5_schema` 与 docs/schema-hdf5.md §12（检查项语义）→ 本文（CLI 调用面）→ 实现代码注释。检查内容与本文示例文案若有出入，以 `validate_file` 实际返回为准；调用面（参数、退出码、流向）以本文为准。

*IR2-F4 完。本文未改动 `src/**` 任何文件。*
