# IR5-F1 2D Challenge 协议（父调度器代行）

官方入口：https://idics.org/challenge/ → Drive `1tNUKPJ7UJOm23JhERtkrIy5gSBiwV3Dj`（2D Challenge 1.0）。
SEM `sem.org/dic-challenge`：404；`sem.org/dicchallenge`：错误页。

最小可跑集：Sample 14（无 xlsx 真值）+ Sample 15（`CommandedDisplacementLineCut.xlsx`，列 k50…k400 对 y）。

计分（独立实现，非 Jones/Reu MATLAB）：
- 沿 POI 网格中央列取 `v(y)`，插值到真值 `y`，RMSE / bias。
- 必须 `search_radius` ≥ 约 10 px（K200 |v| 达 ~10 px）。过小窗口会丢掉大位移区、虚假变好。

默认报告参数：subset 21、step 16、VSG = (5−1)*16+21 = 85 px。不得与 Reu 2018 十二家表直接并列，除非 VSG/滤波对齐。
