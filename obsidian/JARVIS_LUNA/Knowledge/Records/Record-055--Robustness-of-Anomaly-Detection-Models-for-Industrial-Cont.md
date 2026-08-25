---
title: "Record 055 · Robustness-of-Anomaly-Detection-Models-for-Industrial-Control-Systems-"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-25T07:09:56.808018+00:00
tags: [{', '.join(tags)}]
---

# Record 055 · Robustness-of-Anomaly-Detection-Models-for-Industrial-Control-Systems-

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.23547v1)

**제목:** Robustness of Anomaly Detection Models for Industrial Control Systems under Training-Time Data Contamination

Robustness of Anomaly Detection Models for Industrial Control Systems under Training-Time Data Contamination
Machine-learning-based anomaly detection is increasingly used in industrial control systems (ICS), yet most studies assume that detector training data is trustworthy. In practice, training data may be corrupted through compromised logs, labeling errors, manipulated historian records, or unsafe retraining processes. This paper evaluates the robustness of offline ICS anomaly-detection pipelines on the Secure Water Treatment (SWaT) benchmark under training-time contamination. We assess 11 heterogeneous anomaly detectors under three contamination strategies: random injection, similarity-targeted injection, and feature-noise injection. The first two insert attack samples into the nominal training pool, while the third adds bounded Gaussian noise to selected normal training samples. These attacks are contamination-based rather than gradient-driven poisoning methods. Contamination budgets from 1% to 10% are evaluated using clean validation and test sets under a unified offline protocol. The results show that robustness is strongly model-dependent and cannot be predicted from clean-data performance alone. Injection-based contamination causes the greatest degradation, particularly for local-density and distance-based detectors, whereas feature-noise contamination has a comparatively limited effect. PCA, SVM, HBOS, and IForest remain relatively stable, while the tuned neural detectors demonstrate intermediate robustness. Overall, the findings highlight the importance of training-data integrity in ML-enabled ICS monitoring, subject to the evaluated dataset, models, and threat assumptions.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
