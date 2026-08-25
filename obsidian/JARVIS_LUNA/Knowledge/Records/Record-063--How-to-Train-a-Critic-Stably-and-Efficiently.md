---
title: "Record 063 · How-to-Train-a-Critic-Stably-and-Efficiently"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-25T04:08:35.340488+00:00
tags: [{', '.join(tags)}]
---

# Record 063 · How-to-Train-a-Critic-Stably-and-Efficiently

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.23566v1)

**제목:** How to Train a Critic Stably and Efficiently

How to Train a Critic Stably and Efficiently
Group-based reinforcement learning methods such as GRPO for large language models avoid training a critic by sampling multiple responses for each prompt. A reliable critic could instead estimate token-level advantages from one response, but standard critic-based training recipes are often unstable. We study this instability and develop \textbf{Best-Practice Critic Optimization (BPCO)}, a recipe that combines DPPO, value predictions bounded to the reward range, Monte Carlo value targets, unnormalized policy advantages, and length-adaptive generalized advantage estimation. Because the critic is used only during training, BPCO can also condition it on reward-defining information, such as a reference answer or grading rubric, that is hidden from the policy. Controlled experiments isolate the effect of each design choice. Across mathematical reasoning tasks with models ranging from 1.5B parameters to 30B-A3B mixtures of experts, BPCO improves a strong critic-based baseline consistently, and matches or exceeds a group-based baseline while sampling one response per prompt. The same recipe also improves learning with rubric-based rewards. These results show that a carefully designed critic provides a reliable alternative to group-relative advantage estimation. Code is available at https://github.com/QPHutu/golden_critic

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[Model-Routing-and-MoE]] [[JARVIS Real Knowledge Index]]
