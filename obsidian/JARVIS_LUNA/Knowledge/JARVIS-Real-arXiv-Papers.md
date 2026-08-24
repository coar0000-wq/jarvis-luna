---
title: "JARVIS Real arXiv Papers"
source: "arXiv API"
status: ok
collected_at: 2026-08-24T23:45:18.910664+00:00
tags: [jarvis, real-data, knowledge]
---
# JARVIS Real arXiv Papers

> 상태: **ok**

## 연결된 지식

- [[JARVIS Real Knowledge Index]]

## 수집 항목

### Primal Acceleration of Newton's Method
- 원문: [https://arxiv.org/abs/2608.21359v1](https://arxiv.org/abs/2608.21359v1)
- published: 2026-08-21T17:59:37Z
- authors: Nikita Doikov
- summary: We develop a new direct accelerated Newton method for minimizing convex functions with Lipschitz continuous Hessian. The algorithm uses only primal variables and performs just one linear solve per iteration. With a simple predetermined choice of parameters, it achieves the global convergence rate of $O(1/k^3)$ in terms of the functional residual. To the best of our knowledge, this is the first second-order method for this problem class attaining this rate while relying solely on one linear system solve per iteration (without solving auxiliary nonlinear regularized subproblems, such as cubic regularization, performing nonlinear parameter searches, or using dual extragradient corrections). Our method can be implemented in a Hessian-free way, using an inexact linear system solver, while preserving the fast global rate. We further extend our construction to arbitrary geometry through Bregman divergence, and to composite optimization problems.

### VIALS: A Benchmark for Visual Interpretation of Artifacts in the Life Sciences
- 원문: [https://arxiv.org/abs/2608.21357v1](https://arxiv.org/abs/2608.21357v1)
- published: 2026-08-21T17:59:26Z
- authors: Elaine Lau, Thanuka Udumulla, Lee Izhaki-Tavor, Francisco Guzmán, Nicholas Magazine, Jonas Mueller
- summary: In professional life sciences workflows, scientists routinely interpret visual artifacts (gel blots, microscopy images, plasmid maps, flow cytometry plots, molecular structures, ...) to inform research decisions. We introduce VIALS, a visual question-answering benchmark with 161 such interpretation tasks, spanning the types of artifacts examined throughout experimental workflows in the biotech industry (rather than polished figures from publications and textbooks). While frontier vision-language models can now fluently describe natural images, we find that they are unable to accurately interpret these scientific images, reflecting limitations in domain knowledge and domain-specific visual reasoning capabilities. In contrast, scientists with relevant domain expertise find these visual interpretation tasks straightforward. AI that cannot similarly interpret such images will have limited utility in professional life sciences workflows, where such artifacts are central to how scientists reason, communicate, and make decisions.

### AI with Authority, from Application to Silicon
- 원문: [https://arxiv.org/abs/2608.21356v1](https://arxiv.org/abs/2608.21356v1)
- published: 2026-08-21T17:59:16Z
- authors: Jason Hickey
- summary: For sixty years, machine verification has been a major cost overhead, affordable only for exceptional artifacts. Here we report that generative AI inverts this relationship: at AI speed, machine verification is not only economical but essential to productivity --- it is the incorruptible referee that lets one person safely direct autonomous machine work at scale. In five weeks, one researcher on consumer AI subscriptions directed a small fleet of AI agents from application code, through a verified compiler and executive, to a RISC-V processor taped out on a community silicon shuttle; no proof passed through human review, and no RTL was written by a human. The working discipline --- the Salt method --- rests on a proof kernel no hallucinated proof can pass: mathematical claims travel between agents as kernel-checked artifacts, and human attention is reserved for statements, designs, and rulings. Verification is stated link by link, from the Lean 4 kernel to SAT-checked equivalence at the silicon boundary. We publish the complete accounting: theorem provenance, a pre-registered token meter, floor-bounded human time, and an error ledger whose catch numbering runs to #256 --- a monotone counter over the mathematics campaign's append-only flags ledger, maintained 2026-07-07 to 2026-07-20 (one number, #79, was never assigned; later catches are recorded un-numbered) --- against zero incorrect proofs reaching the record.

### PerturbRx: Learning Treatment-Conditioned Latent Transitions for Patient Drug Response Prediction
- 원문: [https://arxiv.org/abs/2608.21349v1](https://arxiv.org/abs/2608.21349v1)
- published: 2026-08-21T17:54:48Z
- authors: Yoshitaka Inoue, Minoh Jeong, Alfred Hero, Rui Kuang, Augustin Luna
- summary: Scarce data and tumor heterogeneity limit patient-level cancer treatment-response prediction. Existing approaches predict response from pretreatment molecular profiles and drug representations, without explicitly modeling the molecular changes expected under treatment. We propose PerturbRx, a treatment-conditioned representation learning framework that learns intervention-induced latent transitions and uses them as patient-drug response features. PerturbRx trains a drug- and dose-conditioned transition predictor from context-matched but cell-unpaired control and treated single-cell populations, then freezes and transfers the predictor to pretreatment patient profiles without requiring post-treatment measurements. The transition is combined with patient and drug representations to predict response. Across TCGA and patient-derived xenograft benchmarks, PerturbRx achieves the strongest aggregate predictive performance among the evaluated methods. These results support perturbation-pretrained latent transitions as useful representations for patient-level drug-response prediction.

### Truthful Calibration Measures for Sequential Prediction
- 원문: [https://arxiv.org/abs/2608.21348v1](https://arxiv.org/abs/2608.21348v1)
- published: 2026-08-21T17:54:05Z
- authors: Anagha Gokul, Jason Hartline, Lunjia Hu, Jonathan Ullman, Yifan Wu
- summary: Calibration requires probabilistic reports to be conditionally unbiased and reliably interpretable as probabilities. A calibration measure assigns numerical error to miscalibrated reports. Haghtalab et al. (2024) proposed an approximately truthful calibration measure for online prediction, leaving open whether exact truthfulness is compatible with completeness and soundness. We resolve this question negatively for sequential binary prediction: exact truthfulness is incompatible with completeness and soundness, even for independent outcomes. We then show that this impossibility is specific to exact truthfulness. We give two general reductions from a base calibration measure, producing additively and multiplicatively approximately truthful calibration measures, respectively. Applying the multiplicative reduction, for every $0 < \varepsilon < 1$ we construct a sound and complete calibration measure that is $(1+\exp(-T^{(1-\varepsilon)/2}/2))$-multiplicatively truthful. This improves the approximate-truthfulness guarantee of Haghtalab et al. (2024).

### Asymmetric Capacity Allocation in Self-Refinement Pipelines
- 원문: [https://arxiv.org/abs/2608.21345v1](https://arxiv.org/abs/2608.21345v1)
- published: 2026-08-21T17:52:17Z
- authors: Zhuoyi Yang, Ian G. Harris, Salar Hashemitaheri, Cassie Huang, Yuangang Li, Hyunwoo Oh, Paul Dourish, Tony Givargis, Mohsen Imani, Li Zhang
- summary: Self-refinement, typically structured as generation, critique, and revision, is a widely adopted paradigm for improving LLM generation and serves as a core mechanism in many LLM agents. While the three stages involve different cognitive demands, most existing approaches conveniently treat the model size as an implementation detail rather than a subject of study, which may lead to a waste of resources. Little work has systematically examined how model size affects each stage or whether effective self-refinement requires equally capable models for generation, critique, and revision. We present the first stage-wise model size study of the self-refinement pipeline on 5 benchmarks from different domains using 6 model sizes of Qwen3 and 4 model sizes of Gemma 3. We conclude that larger generators and refiners generally improve the pipeline, whereas an undersized refiner can even harm performance. Second, performance is highly insensitive to the size of the critic, although including even a small critic consistently outperforms omitting critique altogether. Our findings demonstrate that model capacity should not be allocated uniformly across self-refinement pipelines. Instead, different stages exhibit distinct size scaling characteristics, providing practical guidance for designing more computationally efficient multi-stage language model systems.

### TurboBias 2.0: Streaming Context-Biasing for Production-Efficient ASR Systems
- 원문: [https://arxiv.org/abs/2608.21343v1](https://arxiv.org/abs/2608.21343v1)
- published: 2026-08-21T17:50:00Z
- authors: Vladimir Bataev, Lilit Grigoryan, Andrei Andrusenko, Nikolay Karpov, Vitaly Lavrukhin, Boris Ginsburg
- summary: Contextualization is essential for production automatic speech recognition (ASR) systems, where user-provided phrases must be recognized accurately under strict latency constraints. Although many context-biasing methods improve recognition accuracy, they often do not address the practical requirements of modern production ASR systems: streaming inference, efficient batched decoding, user-specific context lists, and low runtime overhead. We propose TurboBias 2.0, a production-oriented framework for efficient phrase boosting in Transducer-based ASR systems. The framework extends GPU-accelerated TurboBias with a case-insensitive boosting graph and per-stream batched decoding, allowing each utterance in a batch to use an independent context-biasing configuration. This enables personalized context biasing for multiple simultaneous users without sharing or mixing their context lists. The proposed framework supports both offline and streaming inference and can be used with greedy and beam-search decoding. Experiments show that TurboBias 2.0 improves contextual phrase recognition while preserving low latency and high throughput.

### Across-Design Uncertainty in Short Pricing Panels: Evidence from Simulated Price Trajectories
- 원문: [https://arxiv.org/abs/2608.21334v1](https://arxiv.org/abs/2608.21334v1)
- published: 2026-08-21T17:40:31Z
- authors: Pedro Cadahia Delgado
- summary: Short observational pricing panels can contain many observations while offering only a small number of distinct price movements. This paper studies the inferential consequences of that distinction in a synthetic data-generating process calibrated to a sparse pricing regime. We separate uncertainty conditional on a realised price trajectory from variation in estimation error across alternative trajectories generated by the same pricing process. In the baseline simulations, the latter component accounts for 97.6% of the variance of estimation error for the gradient-boosted specification. Within-panel resampling procedures use the information of one realised trajectory and do not identify this across-design component. Three results organise the analysis. First, across-design dispersion is well described by the empirical relation sigma_hat approx 0.182 V^(-0.271), where V equals moves times magnitude squared. Second, adding regions sharing a common price path reduces outcome noise but does not create independent price trajectories; conversely, averaging across units with independent design-specific errors reduces dispersion at the standard square root rate. Third, a Paule-Mandel variance component estimated across independently priced units substantially increases empirical coverage in homogeneous simulations, from 0.469 to 0.931. The broader implication is a shift toward designing data-generating processes that create independent identifying variation rather than relying solely on fixed passive panels.

### Anatomy-Informed Neural Networks: Encoding Anatomic Priors in Loss and Architecture, with an SE(3) Formulation of Guidewire-Induced Aortoiliac Deformation
- 원문: [https://arxiv.org/abs/2608.21332v1](https://arxiv.org/abs/2608.21332v1)
- published: 2026-08-21T17:38:42Z
- authors: David P. Stonko
- summary: Deep-learning models of anatomy can be numerically plausible yet anatomically impossible, and they generalize poorly when data are scarce. We introduce Anatomy-Informed Neural Networks (AINN), in which soft anatomic priors enter as penalty terms in the loss (e.g., a branching penalty that treats a renal transplant artery off the iliac instead of the aorta as unexpected rather than impossible), in direct analogy to a physics-informed neural network, and hard anatomic priors (e.g., continuity of the vessel) are built into the architecture and state representation, making such invalid predictions impossible by construction wherever the prior admits architectural enforcement. We develop it on a clinical test case with limited data: how the aortoiliac tree deforms when a stiff wire is introduced endoluminally. This is important to contemporary aortic surgery and will matter to autonomous endovascular navigation. We lift the vessel centerline and the wire path from R^3 to curves of frames in the Lie group SE(3), and couple a Cosserat-rod wire to a tortuosity-modulated, anatomically anchored vessel through a unilateral lumen-contact inequality. The prediction is a constrained minimizer of the coupled elastic energy, with contact forces as its Lagrange multipliers. Supervision is a Wasserstein-2 optimal-transport loss between the predicted projection through the C-arm geometry and the observed angiogram, so a 2D angiogram can train a 3D prediction. The kinematics, loss and projection are verified against known ground truth; the mechanics solver only against its own optimality conditions, and predicted displacement is not yet mesh-converged. Here, no network is trained. Future work will transfer this in silico model to real CT scans and test whether it improves predictive accuracy and reduces the training data required.

### Time-Aware Tranformer-Based Prediction Model for AECOPD
- 원문: [https://arxiv.org/abs/2608.21324v1](https://arxiv.org/abs/2608.21324v1)
- published: 2026-08-21T17:31:23Z
- authors: Weihao Qu, Ling Zheng, Dongyang Wang, Jiacun Wang, Haowen Pan
- summary: The rapid symptom change of Acute exacerbation of chronic obstructive pulmonary disease (AECOPD) makes it critical to have time-sensitive prediction models. However, most current machine learning models studying AECOPD use clinical and laboratory data, which will inevitably cause latency. To ensure timely detection of AECOPD and minimize latency, this paper focuses on home monitoring scenarios where only respiratory data from daily-use ventilators is available. We introduce a Time-Aware transformer-based AECOPD prediction model, which generates meaningful patient representations using the Time-Aware transformer to capture the symptoms and their temporal progression in ventilator data. Our experimental results demonstrate that our Time-Aware transformer-based approach outperforms traditional methods in multiple classification tasks, highlighting its potential to enhance AECOPD prediction accuracy.

