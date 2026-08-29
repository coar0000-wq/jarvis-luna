---
title: "Record 420 · Provably-adaptive-sampling-with-uniform-and-remasking-discrete-diffusi"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-29T21:52:54.488436+00:00
tags: [{', '.join(tags)}]
---

# Record 420 · Provably-adaptive-sampling-with-uniform-and-remasking-discrete-diffusi

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.23554v1)

**제목:** Provably adaptive sampling with uniform and remasking discrete diffusion models

Provably adaptive sampling with uniform and remasking discrete diffusion models
Discrete diffusion models offer a promising alternative to autoregressive generation by enabling parallel updates, but their sampling efficiency can depend strongly on the choice of the forward process and the sampler. For the uniform forward process, existing lower bounds for the standard $τ$-leaping sampler scale linearly with the ambient dimension $d$, raising the question of whether this dependence is intrinsic to the forward process. We answer this question in the negative. We consider a first-order sampler based on the leave-one-out denoiser for uniform and remasking processes whose coordinate updates can be performed in parallel. In both cases, the sampler can correct denoising mistakes during the sampling process, which becomes necessary when many coordinates are updated together. Our main result establishes an adaptive sampling guarantee: up to logarithmic factors, $N = O(\mathrm{DTC}(X_0) / \varepsilon)$ discretization steps suffice to achieve sampling error $O(\varepsilon_{\mathrm{score}}+\varepsilon)$, where $\varepsilon_{\mathrm{score}}$ is the error in score estimation. Thus, the sampling complexity is governed by the intrinsic dependence structure of the target distribution, as measured by its dual total correlation $\mathrm{DTC}(X_0)$, rather than directly by the ambient dimension $d$. Our analysis proceeds through a Bayes-optimal auxiliary sampler that separates discretization error from score-estimation error. We also derive an exact information-theoretic representation of the discretization error in terms of the mutual information between different coordinates of the forward process at different times. This representation applies to general forward processes and, in the uniform and remasking cases, can be controlled by $\mathrm{DTC}(X_0)$. Numerical experiments on structured synthetic distributions illustrate the predicted dimension-adaptive behavior.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
