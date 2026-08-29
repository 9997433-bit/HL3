# IR5-G2 实跑

命令与墙钟（4 vCPU，无 GPU）：

```
python -m hl3.bench 2d --sample both --subset 21 --step 16 --k 200   # ~54 s
python -m hl3.bench stereo --subset 21 --step 80 --lens 35-mm          # ~9 s
```

JSON 在 `benchmarks/challenge/results/`。图像未提交。
