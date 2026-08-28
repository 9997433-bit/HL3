ACTUAL_MODEL_SLUG: gpt-5.6-sol-xhigh-fast

# IR4-G1：HL3 ICGN / 应变数学与 Ncorr、OpenCorr 论文及 VIC 公开定义的算法对账

> 审查日期：2026-08-28  
> 审查对象：当前 checkout 的 `src/hl3/correlate/icgn.py`、`src/hl3/strain/**` 及对应测试。  
> 外部证据：Blaber–Adair–Antoniou 的 Ncorr 论文；Jiang 的 OpenCorr 论文及该论文明确引用的方法论文；VIC-2D 公开用户手册和厂商公开知识库。  
> 边界：**没有阅读或比较 OpenCorr 源码**，也没有运行 OpenCorr/VIC；所以本文判定的是“公开数学/论文表述 parity”，不是逐位输出、速度或产品 parity。

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| HL3 二阶 warp 是否完整？ | **参数化完整，群运算不完整。** 12 个参数覆盖二维总次数 ≤2 的全部位移单项式，没有漏 `x²/xy/y²`；但二次映射的复合与逆一般不是二次映射，HL3 的 6×6 lift 会截掉三、四次项。它是实用的二阶截断 IC-GN，不是精确闭合的二次 warp 群。 |
| Hessian 是否完整？ | **12×12 Gauss–Newton Hessian 列是完整的，但不是目标函数的精确 Newton Hessian。** `JᵀJ` 包含全部 12 参数且每 POI 预计算一次，符合 IC-GN。可是当前条件数检查使用了反向的参数缩放，须修正后才能把 Hessian 健康门判为 parity pass。 |
| 插值是否 C1？ | **是，而且内部区域更强。** HL3/OpenCorr 论文路线的三次 B-spline 为 C2；Ncorr 的五次 B-spline 为 C4，因此都至少 C1。三者仍不数值等价：阶数、边界延拓和参考梯度取得方式不同。 |
| 应变张量是否等价 VIC User Manual？ | **部分等价。** HL3 的 Green–Lagrange、材料 Hencky、Euler–Almansi 与 VIC 公共公式同式；HL3 的 `engineering` 是小应变张量，明确**不等价** VIC 的转动不变 engineering strain；HL3 还缺 VIC 列出的 logarithmic Euler–Almansi、Biot。HL3 的 von Mises、Tresca 采用的厚度方向假设/归一化也与 VIC 公共公式不同。 |

总门判定：

- **IC-GN 数学骨架：conditional pass**；
- **二阶形函数：representation pass / exact-composition fail**；
- **Hessian 健康门：fail，存在可定位的缩放方向错误**；
- **插值 C1：pass，但不能宣称 Ncorr 插值 parity**；
- **VIC 张量族 parity：partial；若 API 名称被理解为 VIC 语义，则当前 fail**。

## 1. 证据强度与可比范围

### 1.1 Ncorr

Blaber et al. (2015) 给出了足够完整的算法公式：

- 仅使用一阶仿射、6 参数 warp；
- ZNSSD/IC-GN；
- 每个 subset 预计算 GN Hessian，Cholesky 求解，非正定时拒绝；
- 五次 B-spline 同时用于亚像素灰度与参考灰度导数；
- 应变不用 IC-GN 直接输出的梯度，而在位移场上做局部最小二乘平面拟合，再计算 Green–Lagrange 应变。

因此 Ncorr 列可以作公式级对账，但**不能**作为二阶 warp 参照：该论文没有二阶形函数。

### 1.2 OpenCorr

Jiang (2023) 是模块/架构论文：它公开报告一阶及二阶 ICGN、三次 B-spline、梯度模块和局部位移拟合应变模块，但把 ICGN2D2 的细节指向 Gao et al. (2015)，把应变拟合原理指向 Pan et al. (2007)。

因此本文只作以下论文级结论：

- OpenCorr **宣称/提供**一阶和二阶 ICGN；
- 其二阶路线属于 Gao 等人的 12 参数二阶 IC-GN 方法族；
- 灰度插值属于三次 B-spline 路线，参考梯度属于四阶中心差分路线；
- 应变由 POI 邻域位移多项式拟合的一阶导数得到，公开层面有 Cauchy/Green、Lagrangian/Eulerian 选择。

论文没有给出足以复现当前 OpenCorr 版本所有病态判据、边界延拓、正则化和浮点顺序的细节。故本文**不声称 HL3 与 OpenCorr 逐位相同**。

## 2. ICGN 总体对账

| 项目 | HL3 当前实现 | Ncorr 论文 | OpenCorr 论文路线 |
|---|---|---|---|
| 相关准则 | ZNSSD 最小化，报告 ZNCC | ZNSSD 最小化，NCC/邻点给初值 | ZNSSD/IC-GN 方法族 |
| warp | 一阶 6 参数；二阶 12 参数 | 一阶 6 参数 | 一阶和二阶 |
| 更新 | `W(p) ← W(p)·W(dp)⁻¹` | 同一逆合成更新 | 同一方法族 |
| 参考梯度 | 四阶中心差分后，再作三次 B-spline 采样 | 五次 B-spline 曲面的解析偏导 | 四阶中心差分 |
| 目标灰度 | 预滤波三次 B-spline | 五次 B-spline | 三次 B-spline |
| Hessian | 6×6 / 12×12 `JᵀJ`，每 POI 一次 | 6×6 GN Hessian，每 subset 一次 | IC-GN 常量 GN Hessian；论文未完整公开健康门 |
| 线性求解 | 条件门 → 微小对角加载 → Cholesky | Cholesky；失败即拒绝 | 论文级细节不足 |
| 位移场传播 | 可 FFT-CC 独立粗种子；无 Ncorr 式完整 RG 队列 | reliability-guided 邻点传播 | 有 FFT/feature-guided 等模块，非本文重点 |

HL3 与两篇论文的核心 IC-GN 关系是“同一数学家族”，不是“相同软件实现”。尤其 Ncorr 的五次样条与 HL3/OpenCorr 路线的三次样条会产生不同的亚像素 S 曲线误差。

## 3. 二阶 warp：完整到什么程度

### 3.1 参数化没有缺项

HL3 对 POI 局部坐标 `(dx,dy)` 使用

```text
u(dx,dy) = u + u_x dx + u_y dy
           + 1/2 u_xx dx² + u_xy dxdy + 1/2 u_yy dy²

v(dx,dy) = v + v_x dx + v_y dy
           + 1/2 v_xx dx² + v_xy dxdy + 1/2 v_yy dy²
```

即

```text
p = (u,u_x,u_y,u_xx,u_xy,u_yy,
     v,v_x,v_y,v_xx,v_xy,v_yy)
```

这正好是二维标量二次多项式每分量 6 项、两分量 12 项。纯二次项的 `1/2` 是二阶导数参数约定，不是漏乘；`xy` 混合项没有 `1/2` 也正确。

所以，如果“完整”指**单个 subset 内任意二维二次位移场能否表示**，答案是 **yes**。Ncorr 论文只能表示仿射场；OpenCorr 论文报告的 ICGN2D2 与 HL3 在这一层属于同一 12 参数方法族。

### 3.2 二次 warp 不构成精确群

若 `A(x)`、`B(x)` 都为二次映射，则 `A∘B` 一般含三次、四次项；`B⁻¹` 一般也不是二次多项式。HL3 采用 Gao 路线的单项式 lift：

```text
S = (dx², dy², dxdy, dx, dy, 1)ᵀ
```

把 warp 表为 6×6 矩阵，矩阵相乘/求解后只读回表示 `x,y` 的两行，相当于把真实复合投影回二阶空间。其含义应准确写成：

> 每次更新保留复合结果的二阶可表示部分，而不是精确求得物理二次映射的逆。

仿射子群上没有高次项，更新是精确的；存在曲率时则为截断近似。

### 3.3 现有测试证明了什么、没有证明什么

现有测试有价值：

- 12 参数 ↔ 6×6 表示往返；
- 仿射子群与一阶更新一致；
- lift 代数中的 `compose_inverse_second_order(p,p)` 回零；
- 一个固定 warp/增量族在 31×31 subset 上的复合缺陷随增量缩小；
- 解析二次位移场中，二阶结果显著优于一阶。

但应避免把这些扩大成全局证明：

1. `compose_inverse_second_order(p,p)=0` 证明的是 **lift 矩阵代数自洽**，不是二次物理映射存在精确二次逆；
2. 报告中的 `1.899e-4 / 1.151e-5 / 7.640e-7 px` 是三个固定样本的回归值，不是对全部允许曲率、平移、subset 半径的统一误差界；
3. 退化检查只先看 POI 中心处的 2×2 线性块；高曲率 warp 可能在 subset 边缘发生 `det(DW)≤0`，当前没有全 subset 可逆性/折叠检查。

所以“二阶 warp 完成”的准确说法是：

> **完整实现了 12 参数二阶形函数和一个经样本测试的截断逆合成算子；尚未证明所有允许输入上的可逆性与统一截断界。**

## 4. Hessian

### 4.1 HL3 的 12×12 Hessian 列完整

令二阶基

```text
b = (1, dx, dy, dx²/2, dxdy, dy²/2)
```

HL3 最速下降图为

```text
J = [ f_x b | f_y b ]                  # N×12
H_raw = JᵀJ                            # 12×12
H = 2 / ||f-f_mean||² · H_raw
```

这里 12 列全部存在，没有把曲率列遗漏，也没有用 6×6 lift 的大小误当 Hessian 大小。6×6 是 warp 复合表示；优化 Hessian 正确地是 12×12。

和 Ncorr Appendix A1 一样，这个 `H` 是采用 Gauss–Newton 假设、忽略归一化残差二阶项后的**近似 Hessian**。它不是 ZNSSD 对参数的精确二阶导数。称其“GN Hessian”是正确的，称其“exact Hessian”不正确。

### 4.2 对称正定不是无条件性质

`JᵀJ` 总是对称半正定；仅当 `J` 满列秩时才正定。低纹理、单方向条纹或二阶列近线性相关时会奇异/病态。

- Ncorr 论文：预期极小值邻域内 Hessian 正定，使用 Cholesky；分解失败则拒绝该点。
- HL3：先作特征值条件数门，再加 `1e-9·trace(H)/n` 对角加载，再 Cholesky；病态点返回 `SINGULAR_HESSIAN`。
- OpenCorr：公开论文足以确认常量 GN Hessian 方法族，但不足以确认与 HL3 相同的条件阈值、加载及拒绝语义。

HL3 “先检查原矩阵、后加载”这一顺序是好的：真正秩亏不会被正则项伪装成可信解。

### 4.3 当前条件数缩放方向错误

HL3 以

```text
S = diag(1,r,r,r²/2,r²,r²/2,  1,r,r,r²/2,r²,r²/2)
```

定义“subset 边缘像素运动”坐标 `q = S p`，收敛判据 `||S·dp||` 也是这个语义。

既然 `p = S⁻¹q`，则

```text
J_q = J_p S⁻¹
H_q = S⁻¹ H_p S⁻¹
```

但 `_well_conditioned()` 当前实际计算：

```text
H_checked = S H_p S
```

方向正好相反。它会进一步放大平移、梯度、曲率列的单位差，而不是消除单位差。

以固定种子白噪纹理、`r=15`、中心 31×31 subset 的当前代码实算：

| 矩阵 | `cond₂` |
|---|---:|
| 原始 `H` | `2.7644e4` |
| 当前 `S H S` | `1.3969e9` |
| 正确坐标变换 `S⁻¹ H S⁻¹` | `2.1148e1` |

默认阈值 `1e10` 使这个样本仍通过，但更大 subset 或较各向异性的健康纹理可能被误拒。这个错误**只在健康门**，并不直接改变已通过点的 GN 解；但它使 `SINGULAR_HESSIAN` 判定依赖错误的参数单位。

另一个较小问题是对角加载 `λ·trace(H)/n·I` 直接施加在混合了 px、无量纲和 px⁻¹ 参数的坐标中，也不是参数尺度不变的。若保留加载，宜在 `q` 坐标中定义，再映射回 `p` 坐标。

### 4.4 Hessian 判定

| 判据 | 结果 |
|---|---|
| 二阶 12 列是否齐全 | **pass** |
| 是否 IC-GN 每 POI 只预计算一次 | **pass** |
| 是否 GN 近似而非精确 Newton | **是，且应明确标注** |
| SPD/奇异失败是否有语义 | **pass** |
| 条件数是否按边缘运动正确无量纲化 | **fail** |
| 能否据此宣称与 Ncorr/OpenCorr Hessian parity | **不能；修正缩放并加半径不变性测试后再判** |

## 5. 插值与 C1

### 5.1 连续性

对简单整数 knot 的基数 B-spline，次数 `p` 的拼接连续性为 `C^(p-1)`：

| 路线 | 灰度插值 | 内部 knot 连续性 | C1？ |
|---|---|---:|---|
| HL3 | 三次、双三次 B-spline，预滤波系数 | C2 | **yes** |
| Ncorr | 五次、双五次 B-spline | C4 | **yes** |
| OpenCorr 论文路线 | 三次、双三次 B-spline | C2 | **yes** |

因此用户问的“Interpolation C1?”答案明确为 **yes**。这里的 C2/C4 指图像内部的分片拼接；边界数值仍受各自 padding/extension 规则影响。

### 5.2 连续不等于相同

三条路线至少有三处不等价：

1. **阶数**：Ncorr 五次样条的支撑和频响不同于 HL3/OpenCorr 三次样条；
2. **边界**：HL3 使用 whole-sample symmetric (`reflect101`) 折叠；Ncorr 论文描述边值 padding + DFT 解系数；OpenCorr 论文不足以证明边界逐点相同；
3. **梯度一致性**：
   - Ncorr 从同一五次 B-spline 灰度曲面取解析偏导，灰度与梯度相容；
   - HL3 先在整数图上作四阶中心差分，再分别用三次 B-spline 插值梯度图；
   - OpenCorr 论文路线同样公开为四阶中心差分梯度 + 三次 B-spline 灰度插值。

HL3 的梯度图本身仍是 C2，但通常

```text
BSpline(FD4(image)) != ∇ BSpline(image)
```

所以“C1 pass”不能推出“导数一致”或“Ncorr 插值 parity”。如果目标是复现 Ncorr 数学，应使用同一五次样条曲面的解析导数；如果目标是 OpenCorr 论文路线，HL3 当前四阶差分选择更接近。

## 6. 位移梯度与应变计算路线

| 项目 | HL3 | Ncorr 论文 | OpenCorr 论文路线 |
|---|---|---|---|
| 应变用 IC-GN `p` 中梯度？ | 否 | 否；论文明确认为它太噪 | 否；对位移邻域拟合 |
| 梯度估计 | POI 方窗加权 PLS；线性/二次可选 | 可独立调半径的局部位移平面 LS | POI 邻域位移多项式拟合 |
| 缺点处理 | 有效 mask、最少邻点、秩判据；失败为 NaN | 论文给局部 over-constrained LS | 公开有邻点数/ZNCC 筛选概念 |
| 主要张量 | 小应变、GL、EA、Hencky | GL | Cauchy/Green，Lagrangian/Eulerian |

HL3 与 Ncorr 在“**先对位移做局部 LS，再由四个梯度算 GL**”上高度一致；只要邻域、权重、坐标和输入位移完全相同，GL 代数同式。但窗口形状、边界、权重和有效点筛选不同，不能据公式同式宣称场值逐点相同。

HL3 还提供

```text
L_VSG = (window_pts - 1)·step_px + subset_px
```

并把 VSG 随结果记录。VIC 公开手册也明确 strain filter 尺寸以**数据点而非像素**计；不过 VIC 的 90% center-weighted decay/box filter 与 HL3 的 Gaussian/uniform PLS 并未证明具有相同权重核和传递函数。

## 7. 与 VIC User Manual 公共应变定义逐项对账

统一记

```text
H = ∇u
F = I + H
C = FᵀF
```

### 7.1 张量本体

| VIC 公开名称/公式 | HL3 | 数学 parity |
|---|---|---|
| Lagrange / Green–Lagrange：`E=(C-I)/2` | `green_lagrange_strain()` 同式 | **exact** |
| Hencky / material logarithmic：`E_H=ln(C)/2` | `hencky_strain()` 同式 | **exact** |
| Euler–Almansi：`e=(I-F⁻ᵀF⁻¹)/2` | `euler_almansi_strain()` 同式 | **exact** |
| Logarithmic Euler–Almansi：手册列为 `ln(FFᵀ)/2` | 无对应入口 | **missing** |
| Biot | 无对应入口 | **missing** |
| Engineering：由 GL 分量恢复伸长和夹角变化 | HL3 为 `(H+Hᵀ)/2` | **not equivalent** |

HL3 与 VIC 都默认 Green–Lagrange，这一点对齐。

### 7.2 `engineering` 是实质性不等价，不是命名小差异

VIC 公开公式为

```text
εx  = sqrt(1 + 2Exx) - 1
εy  = sqrt(1 + 2Eyy) - 1
εxy = asin(2Exy / sqrt((1+2Exx)(1+2Eyy)))
```

它从 Green–Lagrange 张量恢复材料线段伸长和夹角变化，因此对任意刚体转动给零。

HL3 当前：

```text
ε_HL3 = (H + Hᵀ)/2
```

在纯转角 `θ` 下给

```text
εxx = εyy = cos(θ)-1
```

例如 2° 时约 `-609 µε`。现有 HL3 测试还专门断言这个伪应变；该测试证明实现符合“小应变张量”定义，同时也直接证明它**不符合 VIC engineering 定义**。

建议：

- 将当前名字明确为 `infinitesimal` / `linearized_cauchy`；
- 若因 schema 兼容必须保留 `engineering`，至少记录其 definition id，不能暗示 VIC 语义；
- 新增单独的 `vic_engineering`/`extension_angle` 实现，并用刚体转动严格为零锁测；
- VIC 的 engineering `exy` 是完整角剪切量；HL3 `StrainField.exy` 始终是张量非对角分量，语义也需分开。

### 7.3 principal strain 与角度

给定同一对称张量，HL3 的主值公式与标准 2×2 特征值分解一致，因此 `e1/e2` 数学上可对齐。

角度不能直接逐数比较：HL3 明定图像坐标 `+y` 向下，正角在屏幕上为顺时针；VIC 公开说明使用右手坐标、`+y` 向上。比较 `theta_p` 或 shear 符号前必须作坐标变换。

### 7.4 von Mises 不等价

VIC 厂商公开知识库给出的 principal plane-strain 公式是

```text
ε_v,VIC = 2/3 · sqrt(ε1² - ε1ε2 + ε2²)
```

其厚度方向语义是平面应变约束。

HL3 当前为

```text
ε_v,HL3 = 2/sqrt(3) · sqrt(ε1² + ε1ε2 + ε2²)
```

并显式假设不可压缩 `ε3=-(ε1+ε2)`。系数、交叉项符号和厚度方向假设都不同，所以结果不可互换。HL3 公式在其已声明假设下自洽，但函数名若不附 assumption，会被误读为 VIC 的内建 von Mises。

### 7.5 Tresca 不等价

VIC 公共描述采用平面应变 `ε3=0`，并输出最大主应变差的一半：

- `ε1,ε2` 异号：`(ε1-ε2)/2`；
- 同号：`max(|ε1|,|ε2|)/2`。

HL3 构造不可压缩 `ε3=-(ε1+ε2)`，返回三主值的 `max-min`，没有 `/2`。因此厚度假设和归一化均不同。

## 8. 最终 parity 矩阵

| 能力 | 对 Ncorr 论文 | 对 OpenCorr 论文 | 对 VIC 公开数学 |
|---|---|---|---|
| 一阶 IC-GN/ZNSSD | 同一核心公式；插值/初始化不同 | 同一方法族 | VIC 内核公开信息不足，不判 |
| 二阶 12 参数表示 | Ncorr 论文无此能力 | 论文级同一方法族 | VIC 公共手册未给足证据，不判 |
| 二阶精确复合/逆 | **否，HL3 为截断** | 论文指向 Gao 路线；不能从模块论文断言逐项相同 | 不判 |
| 12×12 GN Hessian | Ncorr 只有 6×6 | 方法族对齐 | 不判 |
| Hessian 病态门 | HL3 更显式，但缩放方向错误 | 公开细节不足 | 不判 |
| 插值 C1 | 两者都满足；Ncorr 是 C4、HL3 C2 | 两者三次 B-spline，至少 C2 | VIC 公开有多抽头样条选项，非本文公式级 parity |
| GL strain | 同式且都走位移局部 LS | Green/Lagrangian 路线同族 | **exact formula parity** |
| Hencky / EA | Ncorr 论文未提供 | 公开模块粒度不足 | **exact formula parity** |
| Engineering | Ncorr 论文未提供 | Cauchy 小应变语义更接近 HL3 | **fail** |
| von Mises / Tresca | Ncorr 论文未提供 | 公开粒度不足 | **fail** |
| VSG/应变窗口结果 | 独立 strain window 思路一致 | 局部拟合思路一致 | 尺寸以 POI 计的概念对齐；核不保证相同 |

## 9. 建议的修正顺序

1. **修 Hessian 条件数坐标变换**：`S H S` 改为 `S⁻¹ H S⁻¹`，增加同一物理纹理在不同 `r`/参数单位下判定稳定的测试。
2. **消除 `engineering` 误标**：保留线性小应变但改成不可混淆的名字；另实现 VIC 公共公式并测刚体转动。
3. **给等效应变附 assumption**：把当前函数明确命名为 incompressible closure；如需 VIC parity，新增 plane-strain von Mises/Tresca，禁止静默复用同名。
4. **把二阶声明降到准确范围**：文档写“complete quadratic basis + truncated composition”，不要写“exact second-order inverse”；增加全 subset `det(DW)>0` 检查或至少报告最小 Jacobian。
5. **若目标是 Ncorr 数值路线**：评估五次 B-spline及同一插值曲面的解析梯度；仅 C1/C2 连续性通过并不足以复制 Ncorr 亚像素误差。
6. **补 VIC 张量面**：按需求增加 logarithmic Euler–Almansi、Biot；主方向输出必须携带坐标轴/角度正向元数据。

## 10. 参考资料

1. Blaber, J., Adair, B., Antoniou, A. (2015), “Ncorr: Open-Source 2D Digital Image Correlation Matlab Software,” *Experimental Mechanics* 55, 1105–1122. DOI: [10.1007/s11340-015-0009-1](https://doi.org/10.1007/s11340-015-0009-1).  
2. Jiang, Z. (2023), “OpenCorr: An open source library for research and development of digital image correlation,” *Optics and Lasers in Engineering* 165, 107566. DOI: [10.1016/j.optlaseng.2023.107566](https://doi.org/10.1016/j.optlaseng.2023.107566).  
3. Gao, Y. et al. (2015), “High-efficiency and high-accuracy digital image correlation for three-dimensional measurement,” *Optics and Lasers in Engineering* 65, 73–80. DOI: [10.1016/j.optlaseng.2014.05.013](https://doi.org/10.1016/j.optlaseng.2014.05.013).  
4. Pan, B., Li, K., Tong, W. (2013), “Fast, Robust and Accurate Digital Image Correlation Calculation Without Redundant Computations,” *Experimental Mechanics* 53, 1277–1289. DOI: [10.1007/s11340-013-9717-6](https://doi.org/10.1007/s11340-013-9717-6).  
5. Pan, B. et al. (2007), “Full-field strain measurement using a two-dimensional Savitzky–Golay digital differentiator in digital image correlation,” *Optical Engineering* 46, 033601. DOI: [10.1117/1.2714926](https://doi.org/10.1117/1.2714926).  
6. Pan, Z. et al. (2016), “Performance of global look-up table strategy in digital image correlation with cubic B-spline interpolation and bicubic interpolation,” *Theoretical and Applied Mechanics Letters* 6, 126–130. DOI: [10.1016/j.taml.2016.04.003](https://doi.org/10.1016/j.taml.2016.04.003).  
7. Correlated Solutions, *VIC-2D User Manual*, public download, Chapter 12 “Strain Calculation”: [public manual attachment](https://correlated.kayako.com/api/v1/articles/86/attachments/5544/download).  
8. Correlated Solutions, “Strain Tensors and Criteria in VIC,” public knowledge-base article: [public article](https://correlated.kayako.com/article/2-strain-tensors-and-criteria-in-vic).

---

**一句话可对外复述**：HL3 已有完整 12 参数二阶形函数、常量 12×12 GN Hessian和至少 C2 的样条插值，但二阶逆合成是截断近似，Hessian 条件数缩放目前有方向错误；应变只在 Green–Lagrange、Hencky、Euler–Almansi 三项与 VIC 公共公式等价，engineering、von Mises、Tresca 不能按 VIC 同名量解释。
