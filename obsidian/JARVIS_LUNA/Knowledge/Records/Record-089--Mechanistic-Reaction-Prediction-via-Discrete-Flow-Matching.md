---
title: "Record 089 · Mechanistic-Reaction-Prediction-via-Discrete-Flow-Matching-on-Graph-St"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-28T02:15:47.957256+00:00
tags: [{', '.join(tags)}]
---

# Record 089 · Mechanistic-Reaction-Prediction-via-Discrete-Flow-Matching-on-Graph-St

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.27429v1)

**제목:** Mechanistic Reaction Prediction via Discrete Flow Matching on Graph-Structured Electron Occupation

Mechanistic Reaction Prediction via Discrete Flow Matching on Graph-Structured Electron Occupation
Chemical reactions are fundamentally transformations in electron space, yet most machine learning approaches model them either through \textit{de novo} generation of product molecules or through heuristic graph edits that operate directly on molecular topology. We introduce MAELLE (\textbf{M}ech\textbf{A}nistic \textbf{E}dit f\textbf{L}ow-matching on e\textbf{L}ectron r\textbf{E}arrangements), which instead models reactions as discrete flow matching over electron occupation vectors. Concretely, we formulate the reactant-to-product mapping as a Continuous-time Markov Chain (CTMC) over the graph-structured integer-valued electron occupation space defined on all bonding, non-bonding, and hydrogen sites. To construct the intermediate edit trajectories, we generalize the discrete flow matching mixture path to discrete electron rearrangements using Optimal Transport, yielding a sequence of mechanistically interpretable edit moves without requiring elementary step annotations. MAELLE achieves competitive performance on the USPTO-480K benchmark compared with leading reaction prediction models. Beyond in-distribution accuracy, we evaluate robustness across two out-of-distribution settings - structural complexity and reaction type - and find that MAELLE maintains strong performance where existing methods degrade. Finally, because the learned flow operates over the full electron redistribution, MAELLE naturally recovers mechanistic trajectories that align with known chemistry and can predict side products of a reaction.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Shopify-Commerce]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
