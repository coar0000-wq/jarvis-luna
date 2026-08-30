---
title: "Record 461 · Bellman-Calibration-for-Marginalized-Importance-Weighting-in-Offline-R"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-30T23:40:56.385383+00:00
tags: [{', '.join(tags)}]
---

# Record 461 · Bellman-Calibration-for-Marginalized-Importance-Weighting-in-Offline-R

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.24858v1)

**제목:** Bellman Calibration for Marginalized Importance Weighting in Offline Reinforcement Learning

Bellman Calibration for Marginalized Importance Weighting in Offline Reinforcement Learning
Marginalized importance weighting evaluates a target policy by reweighting offline state-action samples with its discounted occupancy ratio, characterized by an adjoint Bellman equation. Existing minimax, primal-dual, and fitted fixed-point estimators can leave residual occupancy-balance violations because of function-class approximation, regularization, or incomplete optimization. These violations are difficult to diagnose and reduce because the objectives generally lack a direct supervised validation loss for hyperparameter tuning, model selection, and early stopping. We introduce isotonic Bellman calibration, a one-dimensional, model-agnostic post-processing method that reduces these violations while preserving the ranking information in any initial occupancy-ratio estimate. The method corrects the estimate's scale and shape by applying fitted occupancy-ratio evaluation (FORE) over a one-dimensional class of nondecreasing transformations. We characterize Bellman calibration as a conditional fixed-point property equivalent to occupancy-balance against every test function of the calibrated ratio. More generally, we derive a calibration-refinement bound showing that any fitted ratio with small calibration error performs nearly as well as the best post-processing based on its fitted values. For isotonic Bellman calibration, we establish finite-sample calibration guarantees and a KL oracle inequality relative to the best monotone transformation of the initial estimate. Consequently, isotonic Bellman calibration achieves small calibration error and KL risk within statistical error of the best monotone correction, with guarantees for downstream target-occupancy functionals, including policy-value estimation.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
