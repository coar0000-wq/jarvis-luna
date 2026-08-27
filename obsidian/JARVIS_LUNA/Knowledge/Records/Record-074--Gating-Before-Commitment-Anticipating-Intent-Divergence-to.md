---
title: "Record 074 · Gating-Before-Commitment-Anticipating-Intent-Divergence-to-Prevent-Pos"
type: knowledge-graph
status: generated-from-real-data
updated_at: 2026-08-27T09:50:54.002192+00:00
tags: [{', '.join(tags)}]
---

# Record 074 · Gating-Before-Commitment-Anticipating-Intent-Divergence-to-Prevent-Pos

> 실제 수집 레코드입니다. 원문: [arxiv.org](https://arxiv.org/abs/2608.26074v1)

**제목:** Gating Before Commitment: Anticipating Intent Divergence to Prevent Post-Interaction Decision Failures in Autonomous Driving

Gating Before Commitment: Anticipating Intent Divergence to Prevent Post-Interaction Decision Failures in Autonomous Driving
Intent misinterpretation during vehicle interactions causes recurring planning failures. We study a decision layer in which a language-guided intent module reads structured descriptors, computes a smoothed intent-geometry divergence score, and gates the planned maneuver before commitment, upstream of a corridor envelope. On a replayed off-road departure and four crash clips under a frozen, disclosed implementation, gating is the only layer that repairs the plan: on the main case it fires 72 ms after the drift onset but 161 ms before the corridor exit, keeping the trajectory in the corridor in all ten replays. The first calibration draws nine false triggers in 5.9 minutes, each from scoring uncertainty as half a conflict; a preregistered redesign treating uncertainty as abstention cuts this to 0.341 per minute. Two ablations bound the model's contribution: the full score detects fastest on four of five failures under the deployed eligibility, three of five against the unvetoed rule (000871 by one cycle; 000228 by a pre-onset fire on an uncertain stretch that five clips cannot classify as signal or coincidence; dropping the confidence term costs two detections), while on in-domain tracks at equal false positives the geometric rule more than triples its detection. The evidence supports the gating mechanism; the model's demonstrated roles are the fastest detection on these failures and an uncertainty veto on the geometric rule.

**출처:** Source · arXiv

## Connected nodes

[[Source--arXiv]] [[Machine-Learning-Research]] [[JARVIS Real Knowledge Index]]
