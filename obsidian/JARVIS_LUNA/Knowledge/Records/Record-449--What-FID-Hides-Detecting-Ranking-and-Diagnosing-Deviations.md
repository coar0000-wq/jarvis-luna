---
title: "Record 449 · What-FID-Hides-Detecting-Ranking-and-Diagnosing-Deviations-in-Generati"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-30T11:56:13.067377+00:00
tags: [{', '.join(tags)}]
---

# Record 449 · What-FID-Hides-Detecting-Ranking-and-Diagnosing-Deviations-in-Generati

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.24881v1)

**제목:** What FID Hides: Detecting, Ranking, and Diagnosing Deviations in Generative Evaluation

What FID Hides: Detecting, Ranking, and Diagnosing Deviations in Generative Evaluation
Generative models are commonly ranked by Fréchet Inception Distance (FID) and Kernel Inception Distance (KID), yet FID's first-two-moment summary can miss distributional differences, and a reported scalar gap alone is not a calibrated test against sampling variation. FID's moment restriction has concrete consequences: on ImageNet, visually unrecognizable images optimized only to match the reference Inception mean and covariance obtain FID $24.7$ versus $58.6$ for held-out real images (lower is better). Moreover, FID and KID are scalar discrepancies that are unchanged when the two samples are exchanged and therefore do not encode the direction of a dispersion change: under-dispersion, as can occur in mode collapse, versus over-dispersion. We introduce \textbf{ZID} (\emph{Z-resolved Integrated Diagnostic}), which combines six standardized location- and dispersion-sensitive arms from a rank graph (RISE) and Gaussian kernels (GPK at two bandwidths). Rather than asking one scalar to serve incompatible roles, ZID reports three linked outputs: an index for ranking departure magnitude, a permutation $p$-value for testing distributional equality, and a signed dispersion readout for diagnosis. In controlled experiments, ZID detects a broad range of departures, and its score tracks increasing severity along the corresponding sweeps, including cases in which FID is flat or reversed. On DiT-XL/2 and SiT-XL/2 guidance sweeps, ZID detects departure from real data, and its signed readout labels the high-guidance diversity collapse as under-dispersion.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
