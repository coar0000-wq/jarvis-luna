---
title: "Record 843 · Improving-Cross-Problem-Vehicle-Routing-with-Locally-Augmented-Prefere"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-09-02T19:36:54.977915+00:00
tags: [{', '.join(tags)}]
---

# Record 843 · Improving-Cross-Problem-Vehicle-Routing-with-Locally-Augmented-Prefere

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.24859v1)

**제목:** Improving Cross-Problem Vehicle Routing with Locally Augmented Preferences and Representation Disentanglement

Improving Cross-Problem Vehicle Routing with Locally Augmented Preferences and Representation Disentanglement
Multi-task vehicle routing problem (VRP) solvers seek to handle multiple VRP variants within a single unified model, avoiding the need to train a separate model for every variant. In spite of recent progress, current approaches remain limited on two fronts. On the training side, reinforcement learning suffers from reward-scale disparities and shrinking advantage signals as policies improve, whereas preference optimization stagnates once sampled tours become near-identical and thus fundamentally limited by the quality of the policy's own generated solutions, leaving both paradigms with weak supervision as training progresses. On the architecture side, existing fully shared encoders entangle constraint-dependent representations across heterogeneous variants, which limits generalization. We address these gaps with two model-agnostic contributions. First, we propose Preference Optimization with Locally Augmented Refinement (POLAR), a novel training algorithm that applies a local search refinement pass to the best decoded tour before forming preference pairs, yielding much more informative pairwise margins. Second, a Progressive Layered Extraction (PLE) encoder routes each encoder layer through one shared expert and a set of task-specific experts via a gating mechanism, progressively separating common routing structure from constraint-specific encodings. Through extensive experiments on various VRP variants, we show that POLAR and PLE together elevate the current state-of-the-art among neural multi-task solvers. We reduce the average gap to reference solutions by 21.3% relative to the strongest published baseline on 16 in-distribution variants, and outperform prior neural methods on 27 out of 32 unseen variants. Ablation studies confirm the efficacy of each contribution, showing that both improve cross-problem generalization across multiple backbone model architectures.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[Model-Routing-and-MoE]] [[JARVIS Real Knowledge Index]]
