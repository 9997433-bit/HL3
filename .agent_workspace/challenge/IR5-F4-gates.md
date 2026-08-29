# IR5-F4 本轮门（父调度器代行）

| 门 | 结果 |
|----|------|
| G-C2D-1 2D 样本下载或记录官方失败 | **PASS** Sample14.zip 4.5 MB、Sample15.zip 14.8 MB |
| G-C2D-2 runner + skip + JSON | **PASS** `hl3.bench.challenge2d`，无缓存 skip |
| G-C3D-1 stereo 数据 | **PASS** Translate.zip 已缓存（不入库） |
| G-C3D-2 stereo 3D 成绩 | **FAIL** 无标定，仅左相机 2D 诊断 |
| G-CLAIM-1 不宣称对标 VIC | **PASS** JSON `claim` 字段写明 |
| G-DATA-1 无图像进 git | **PASS** gitignore cache |
| A1/A3/A5 R2-F1 | **未关闭**（A5 需 3D+标定+官方分析脚本口径） |
