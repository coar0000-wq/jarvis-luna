---
title: "Record 062 · ReWorld-An-Interactive-World-Model-with-Long-Horizon-Memory"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-25T02:16:00.896306+00:00
tags: [{', '.join(tags)}]
---

# Record 062 · ReWorld-An-Interactive-World-Model-with-Long-Horizon-Memory

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.23565v1)

**제목:** ReWorld: An Interactive World Model with Long-Horizon Memory

ReWorld: An Interactive World Model with Long-Horizon Memory
An interactive world model must follow the user's actions, remember the places it has shown, and stream in real time. The tension is structural: control wants a short horizon, memory wants an unbounded one. ReWorld separates the two during training and bounds them at inference. Mixed per-head attention windows confine most heads to the recent past while a small set of global heads attends over the entire history, and random head routing keeps either capability from binding to particular heads; random chunk dropping makes sparse histories in-distribution. At inference the whole past lives under a fixed budget: a bounded KV cache backed by a pose-indexed landmark bank, from which the model retrieves the landmarks nearest the current pose. A metric-scale-aligned data engine places eight sources -- Unreal-rendered fly-throughs, game roaming, and real-world footage -- on one physical action scale, so the same key press moves the camera the same distance in every source, and palindrome trajectories supply the revisit evidence that memory training needs. Distribution-matching distillation confined to a LoRA adapter then compresses sampling to four steps: one backbone serves both a high-fidelity multi-step mode and a real-time interactive one, streaming 704x1280 video across photorealistic, game-style, and stylized worlds. Under a three-axis protocol covering action following, long-horizon recall, and video quality, against six recent interactive world models it attains the best control fidelity ($11.95^\circ$ rotation error and the best camera-motion consistency) and the best generation quality; and on minute-long out-and-back rollouts ($64$\,s, $384$ latents), its fixed 12-chunk cache still regenerates the starting view -- at rollout lengths where a sliding window has long evicted the evidence and full-KV attention runs out of memory.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[Model-Routing-and-MoE]] [[JARVIS Real Knowledge Index]]
