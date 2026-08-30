---
title: "Record 439 · SPO-Stream-Aligned-Policy-Optimization-for-Asynchronous-Agentic-RL"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-30T04:27:22.177345+00:00
tags: [{', '.join(tags)}]
---

# Record 439 · SPO-Stream-Aligned-Policy-Optimization-for-Asynchronous-Agentic-RL

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.24870v1)

**제목:** SPO++: Stream-Aligned Policy Optimization for Asynchronous Agentic RL

SPO++: Stream-Aligned Policy Optimization for Asynchronous Agentic RL
Group-relative reinforcement learning waits for sibling rollouts of the same prompt, which is costly for long and variable tool-use trajectories. Single-stream Policy Optimization (SPO) removes this dependency with a persistent prompt-level value estimate, but its recipe whitens one advantage per trajectory before optimizing a token-mean actor loss. We show that trajectory centering generally does not center the token-weighted quantity consumed by the actor, and fix the mismatch by standardizing terminal-outcome advantages under the action-token measure. We additionally organize prompt evidence by the policy event that generated it rather than learner receipt order. Across matched runs on ALFWorld at two model scales and on Math-TIR, SPO++ improves online learning efficiency over SPO. A paired ablation identifies action-token-measure normalization as the strongest tested component.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[AI-Agents]] [[JARVIS Real Knowledge Index]]
