---
title: "Record 047 · Asymmetric-Capacity-Allocation-in-Self-Refinement-Pipelines"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-25T22:19:51.253952+00:00
tags: [{', '.join(tags)}]
---

# Record 047 · Asymmetric-Capacity-Allocation-in-Self-Refinement-Pipelines

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.21345v1)

**제목:** Asymmetric Capacity Allocation in Self-Refinement Pipelines

Asymmetric Capacity Allocation in Self-Refinement Pipelines
Self-refinement, typically structured as generation, critique, and revision, is a widely adopted paradigm for improving LLM generation and serves as a core mechanism in many LLM agents. While the three stages involve different cognitive demands, most existing approaches conveniently treat the model size as an implementation detail rather than a subject of study, which may lead to a waste of resources. Little work has systematically examined how model size affects each stage or whether effective self-refinement requires equally capable models for generation, critique, and revision. We present the first stage-wise model size study of the self-refinement pipeline on 5 benchmarks from different domains using 6 model sizes of Qwen3 and 4 model sizes of Gemma 3. We conclude that larger generators and refiners generally improve the pipeline, whereas an undersized refiner can even harm performance. Second, performance is highly insensitive to the size of the critic, although including even a small critic consistently outperforms omitting critique altogether. Our findings demonstrate that model capacity should not be allocated uniformly across self-refinement pipelines. Instead, different stages exhibit distinct size scaling characteristics, providing practical guidance for designing more computationally efficient multi-stage language model systems.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[AI-Image-Generation]] [[Machine-Learning-Research]] [[AI-Agents]] [[JARVIS Real Knowledge Index]]
