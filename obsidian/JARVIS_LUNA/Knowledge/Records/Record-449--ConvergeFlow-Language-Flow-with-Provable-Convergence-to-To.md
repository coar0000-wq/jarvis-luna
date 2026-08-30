---
title: "Record 449 · ConvergeFlow-Language-Flow-with-Provable-Convergence-to-Token-Embeddin"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-30T23:40:56.383088+00:00
tags: [{', '.join(tags)}]
---

# Record 449 · ConvergeFlow-Language-Flow-with-Provable-Convergence-to-Token-Embeddin

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.23551v1)

**제목:** ConvergeFlow: Language Flow with Provable Convergence to Token Embeddings

ConvergeFlow: Language Flow with Provable Convergence to Token Embeddings
Recent advances in continuous diffusion and flow-based language models (LMs) have achieved performance competitive with discrete LMs. However, existing continuous frameworks still rely on decoders supervised with cross entropy (CE) because the flow trajectories are not guaranteed to terminate at valid token embeddings. Motivated by this limitation, we introduce \textbf{ConvergeFlow}, an embedding-space flow-based LM, which constrains the data predictor to the convex hull of token embeddings and trains it solely with the mean squared error objective induced by flow matching. Under suitable regularity conditions, we prove that the resulting flow converges to valid token embeddings despite errors in the data predictor, enabling direct token prediction without a CE-supervised decoder. We further develop three sampling mechanisms for controlling the trade-off between the generative perplexity and entropy. Experiments on OpenWebText demonstrate that ConvergeFlow achieves performance competitive with existing continuous and discrete diffusion LMs. These findings demonstrate the potential of the flow-based paradigm for language modeling. Our code is available at https://github.com/Na-Li66/ConvergeFlow.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
