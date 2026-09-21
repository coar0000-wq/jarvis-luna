---
title: "Record 778f36f541 · The-Other-Half-of-the-Memory-Wall-Serving-35B-MoEs-from-SSD-with-Train"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-09-21T22:01:01.134843+00:00
tags: [record, real-data]
---

# Record 778f36f541 · The-Other-Half-of-the-Memory-Wall-Serving-35B-MoEs-from-SSD-with-Train

> 실제 수집 레코드입니다. 원문: [doi.org](https://doi.org/10.48550/arxiv.2609.18063)

**제목:** The Other Half of the Memory Wall: Serving 35B MoEs from SSD with Trained Routing Prediction

The Other Half of the Memory Wall: Serving 35B MoEs from SSD with Trained Routing Prediction
Mixture-of-experts (MoE) inference on consumer hardware is bounded by weight memory: a 35B-class model is 19.5GB at 4-bit, and sparsity shrinks the compute per token, not the bytes that must be held. Naive offloading to SSD does not help on its own, because layer N+1's experts must be chosen before layer N's output exists, so the reads cannot start early enough to hide behind compute. We present E

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[모델-라우팅MoE]] [[JARVIS Real Knowledge Index]]
