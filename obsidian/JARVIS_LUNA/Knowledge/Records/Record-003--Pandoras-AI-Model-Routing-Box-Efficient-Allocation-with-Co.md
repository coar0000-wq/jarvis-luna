---
title: "Record 003 · Pandoras-AI-Model-Routing-Box-Efficient-Allocation-with-Costly-Value-E"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-23T10:49:36.652812+00:00
tags: [{', '.join(tags)}]
---

# Record 003 · Pandoras-AI-Model-Routing-Box-Efficient-Allocation-with-Costly-Value-E

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.20316v1)

**제목:** Pandora's AI Model Routing Box: Efficient Allocation with Costly Value Estimation

Pandora's AI Model Routing Box: Efficient Allocation with Costly Value Estimation
Heterogeneous AI systems composed of multiple models, architectures, harnesses, or inference-time settings can improve quality and efficiency by routing queries to the specialist who can answer most effectively at the lowest cost. Routing requires estimating each specialist's expected return, but this value estimation has a cost. Cheap estimators (e.g., embedding-based predictors) are fast but noisy, while accurate estimators (e.g., fine-tuned models with access to retrieval results or partial reasoning traces) are expensive. We formalize this tradeoff as an instance of Pandora's Box, the classical problem of optimal search with costly inspection. Under a Gaussian signal model, the resulting policies have closed-form value-of-information expressions that determine, for each specialist and input, whether refining the value estimate is worth its cost. We call the centralized policy Pandora's Router. We extend this to a decentralized setting, Pandora's Bidder, where specialists independently decide whether to invest in self-assessment before accepting an offered price to claim a query. Experiments across three domains---a standard multi-LLM benchmark, retrieval-augmented specialists, and LLMs with variable inference-time reasoning---show that Pandora's Router matches the routing quality of exhaustive estimation, while querying the expensive estimator far less often. In the decentralized setting, value-of-information reasoning improves allocative efficiency when competing estimates are accurate; when competing estimates are noisy, however, it can increase the strategic specialist's utility at the expense of others.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[Model-Routing-and-MoE]] [[JARVIS Real Knowledge Index]]
