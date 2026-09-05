---
title: "Record 2318 · TraceML-An-Empirical-Analysis-of-Human-Agent-Planning-in-Machine-Learn"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-09-05T11:25:01.705219+00:00
tags: [record, real-data]
---

# Record 2318 · TraceML-An-Empirical-Analysis-of-Human-Agent-Planning-in-Machine-Learn

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.26086v1)

**제목:** TraceML: An Empirical Analysis of Human-Agent Planning in Machine Learning Development

TraceML: An Empirical Analysis of Human-Agent Planning in Machine Learning Development
Large language models write correct code for isolated problems but remain far weaker at autonomous machine-learning development, where an agent must revise data pipelines, models, and validation over hours of feedback, and on most competitions still finishes below strong human competitors. Outcome-based benchmarks record this gap but not its cause, because they grade the final submission and discard the development process behind it. We introduce TraceML, which pairs human and agent work on the same competitions under one version-level schema: 4,465 human Kaggle trajectories across 134 competitions, seven of which are also worked by two agent scaffolds, giving 430 paired human and 207 agent trajectories. Every code version carries its score, its timestamp, and labels for the action taken, its intent, the edit size, and the score effect. Read this way, the gap becomes concrete. Experts alternate data work, validation, model changes, and ensembling, and return to approaches they had set aside. Each agent scaffold instead collapses into a narrow loop: Codex spends its steps re-weighting ensembles and tuning submissions, MLEvolve mutates its model in place, and neither pivots at the human rate nor reopens abandoned work. A short planning prompt distilled from human practice moves the behaviors it names toward the human profile and lifts scores, but the effort profile stays agent-shaped: instruction closes only the part of the gap that reduces to instructions. We release the corpus, the schema, the labelers, and the extraction pipeline at https://huggingface.co/datasets/jerryyan/TraceML.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-에이전트]] [[LLM언어모델]] [[모델-라우팅MoE]] [[머신러닝-연구]] [[데이터분석]] [[JARVIS Real Knowledge Index]]
