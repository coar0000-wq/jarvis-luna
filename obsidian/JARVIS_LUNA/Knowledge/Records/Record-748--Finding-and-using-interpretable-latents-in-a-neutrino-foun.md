---
title: "Record 748 · Finding-and-using-interpretable-latents-in-a-neutrino-foundation-model"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-09-01T11:41:16.767329+00:00
tags: [{', '.join(tags)}]
---

# Record 748 · Finding-and-using-interpretable-latents-in-a-neutrino-foundation-model

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.26090v1)

**제목:** Finding and using interpretable latents in a neutrino foundation model with sparse autoencoders

Finding and using interpretable latents in a neutrino foundation model with sparse autoencoders
We present a first application of sparse-autoencoder-based mechanistic interpretability to particle physics. Studying a neutrino foundation model pretrained on IceCube data and fine-tuned for direction reconstruction, we identify a validated atlas of physical concepts in the model representation, using a strict validation protocol consisting of held-out tests, matched nuisance controls, and replication across independent dictionary trainings. Causal interventions show that the direction head barely draws on this atlas. Motivated by this underused information, we train an uncertainty head on the same event-level representation to predict the model's angular reconstruction error. Unlike the direction head, it depends causally on quality and brightness features from the atlas. At $20\%$ selection efficiency, this interpretable estimator improves the median angular resolution from $20.2^\circ$ to $3.2^\circ$. These results suggest that mechanistic interpretability can reveal learned latent physics encoded within a model's internal representation and help design downstream tasks that exploit it.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
