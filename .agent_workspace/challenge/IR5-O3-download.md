# IR5-O1 / O2 / O3 实现说明（父调度器代行）

- `src/hl3/bench/download.py`：manifest Drive id + gdown；拒绝 SEM 文件夹。
- `src/hl3/bench/challenge2d.py`：Sample 14/15 TIFF → `run_sequence`；Sample 15 xlsx 线切割。
- `src/hl3/bench/challenge_stereo.py`：从 Translate.zip 抽 35 mm Step01/02；左相机 2D。
- `src/hl3/stereo/calib_io.py`：3×4 文本/json/npy 摄入（尚无官方 P 文件可喂）。
- CLI：`python -m hl3.bench …` 与 `python -m hl3 challenge …`。
- extra：`hl3[bench] = pillow, gdown`。
