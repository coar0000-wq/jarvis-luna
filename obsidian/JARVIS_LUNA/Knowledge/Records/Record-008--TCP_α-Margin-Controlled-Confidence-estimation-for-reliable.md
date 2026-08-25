---
title: "Record 008 · TCP_α-Margin-Controlled-Confidence-estimation-for-reliable-Music-Infor"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-25T12:34:45.638969+00:00
tags: [{', '.join(tags)}]
---

# Record 008 · TCP_α-Margin-Controlled-Confidence-estimation-for-reliable-Music-Infor

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.20326v1)

**제목:** $TCP_α$: Margin-Controlled Confidence estimation for reliable Music Information Retrieval

$TCP_α$: Margin-Controlled Confidence estimation for reliable Music Information Retrieval
Deep neural networks are often overconfident, assigning high confidence even to incorrect predictions. Consequently, users lack a reliable signal for deciding when a prediction can be trusted. Post-hoc confidence estimation addresses this by training a lightweight auxiliary head over a frozen classifier. Existing targets, however, suffer from inherent ambiguity: they assign overlapping confidence values to correct and incorrect predictions, while errors near the decision boundary receive confidence scores indistinguishable from correct predictions. In this work, we propose $TCP_α$, a novel confidence target that resolves these limitations by introducing a margin-controlled penalty for misclassified samples. We prove that $TCP_α$ guarantees complete separation between the target values of correct and incorrect predictions, with a separation margin that is independent of the number of classes and increases monotonically with the penalty parameter. Since accurate classifiers naturally produce very few errors, learning these targets results in a severely imbalanced regression problem. We therefore present a systematic study of training strategies for learning under this imbalance and identify an effective training configuration through extensive ablation studies. We evaluate the proposed approach on rāga identification, investigate its robustness under domain shift, and further validate it on frame-wise ornamentation detection without modifying the selected configuration. Across all settings, $TCP_α$ consistently outperforms existing confidence targets for failure prediction. Rejecting only the least-confident 8\% of predictions improves the base model's macro-F1 from 0.89 to 0.98, while fine-tuning the confidence head with only 5\% labeled samples from a new corpus effectively restores performance under domain shift.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
