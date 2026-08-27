---
title: "Record 082 · A-Visual-Dependence-Aware-Framework-for-Multimodal-Unsupervised-Contin"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-27T22:17:12.906756+00:00
tags: [{', '.join(tags)}]
---

# Record 082 · A-Visual-Dependence-Aware-Framework-for-Multimodal-Unsupervised-Contin

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.26095v1)

**제목:** A Visual Dependence-Aware Framework for Multimodal Unsupervised Continual Post-Training

A Visual Dependence-Aware Framework for Multimodal Unsupervised Continual Post-Training
In this paper, we explore a novel task of Multimodal Unsupervised Continual Post-Training (MU-CPT), enabling deployed MLLMs to continually evolve from streaming unlabeled data. Existing unsupervised post-training methods for MLLMs typically optimize target tokens uniformly, overlooking their heterogeneous visual dependence (VD). However, we reveal that token-level VD is crucial for MU-CPT. Specifically, its structural distortion serves as an indicator of cross-modal catastrophic forgetting, and its inherent heterogeneity acts as a compass to guide new-task learning. Leveraging this property, we propose a Visual Dependence-Aware (VDA) framework with two main components. First, Visually Constrained Optimal Transport (VC-OT) formulates the VD structural distortion of old-task VD during new-task learning as an optimal transport problem to mitigate cross-modal forgetting. By designing a region-aware ground cost and a dependence-stratified transport penalty, it prevents global shifts in visual focus while strictly prohibiting visual reliance from degenerating into language bias. Second, Visually Modulated Adaptation (VMA) exploits VD heterogeneity to emphasize visually grounded new-task learning, promoting new-task plasticity. Together, our method simultaneously maintains old-task stability and new-task plasticity during challenging MU-CPT. Extensive experiments under our MU-CPT setting validate the effectiveness of VDA.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
