---
title: "Record 092 · SWE-Prime-Fewer-Trajectories-Better-Performance"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-28T02:15:47.957854+00:00
tags: [{', '.join(tags)}]
---

# Record 092 · SWE-Prime-Fewer-Trajectories-Better-Performance

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.27449v1)

**제목:** SWE-Prime: Fewer Trajectories, Better Performance

SWE-Prime: Fewer Trajectories, Better Performance
To improve large language models' ability to resolve real-world software issues, prior work has focused on constructing large-scale agent trajectory datasets and performing supervised fine-tuning (SFT) on successful trajectories. However, task success does not guarantee high-quality supervision: successful trajectories may still contain ineffective, redundant, or risky steps. Directly using such trajectories for SFT can introduce noisy supervision and encourage models to imitate undesirable problem-solving behaviors. Therefore, we propose SWE-Prime, a multi-granularity, two-stage SFT data selection method that progressively filters training data at the trajectory and segment levels. Specifically, the first stage performs trajectory-level screening based on process quality, result quality, and data representativeness, selecting a high-quality and representative subset of successful trajectories. The second stage performs segment-level selection by grouping consecutive steps into semantic segments and assessing each segment based on its contribution to the final solution, learnability, and potential risks. During SFT, all segments remain in the sequence to preserve context, while only selected segments contribute to the loss computation. Experiments on SWE-Bench Pro and SWE-Bench Verified show that training on the 10% trajectory subset selected by SWE-Prime outperforms training on the full resolved dataset, yielding relative performance gains of up to 12.2% and 24.2%, respectively.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[AI-Agents]] [[JARVIS Real Knowledge Index]]
