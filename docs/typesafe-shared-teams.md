# Shared Jev team support

Jev is a typed advisory evaluator, not a chat model or an authority to publish.
`evaluate_team_typesafe.py` batches 11 observed team roles plus the secretary into
one request: evidence-readiness score 0–3 and next-action choice
`local | source_check | human_review`. Counts/status/freshness and evidence
presence are allowlisted; scraped bodies, notes, URLs, credentials and private
business identifiers are excluded. These summaries cannot establish factual
accuracy or legal clearance.

## Existing-free-credit boundary

- The issuing organization was checked in the authenticated provider console.
  The key was issued in that same organization. Free monthly credit, auto-recharge
  Off and no payment method were observed. No new funds, subscriptions or terms.
- `TYPESAFE_BILLING_PROOF_JSON` is a key-hash/org-bound operator observation,
  **not a signed billing receipt or provider-enforced free-only request**. It
  expires within 24 hours and rejects unknown/unsafe billing state. Rounding
  reserves are subtracted from the displayed balance.
- Main-only Deep/Copy consumers use `TYPESAFE_SHARED_API_KEY`. The retired
  unscoped `TYPESAFE_API_KEY` repository secret is removed after replacement, so
  old code/reruns cannot silently bypass the new adapter.
- Both consumers use serialized `main-publish` concurrency and the same ledger.
  All subprocesses share one workflow ID including run ID and attempt.
  Limit: 40 attempted dispatches, 60,000 conservatively charged input tokens,
  $0.00252 per workflow; cumulative project allocation $1.00 per verified key.
- The Aside account helper uses the same validator/cache under a **separate**
  preallocated $0.05 local allowance, shared across its daily callers. This is not
  a distributed lock with CI. Combined allocations $1.05 stay below the observed
  existing free balance; provider balance is independently rechecked.

## Durable receipts and stops

Cache lookup precedes inference. The cache key includes complete relevant state,
questions/model and explicit policy versions; meaningful source-capture times
remain. `jev-1.14.0` is the explicitly selected text model. The concrete response
model must match this pin and is retained. The new model-policy version is
`jarvis-jev-1.14-text-v1`; historical versions, counters, stops and receipts are
never reset or rewritten by this upgrade. CI cache TTL is 24 hours, maximum 24 hours.

The adapter reserves UTF-8 wire bytes + 2,048 before dispatch and retains
`max(reservation, reported usage)` afterward. This is a conservative estimate,
**not a tokenizer or provider billing guarantee**. Overshoot is detected after
response and stops further calls. Output pricing is free at the reference input
rate $0.042/million tokens.

Every consumer uploads its ledger receipt even after failure when the runner can
still execute final steps. Next startup restores and validates prior receipts,
including earlier attempts of a rerun, before any request. The newest receipt
must preserve every older receipt's account/workflow counters, stops, limits,
versions and call history. A missing receipt, disconnected chain, wrong account,
unsafe archive or inaccessible history removes the staged proof and uses local
fallback. A killed runner without a receipt therefore cannot reset the budget
and silently resume. Local locking and GitHub concurrency do not control other
repositories, arbitrary clients or provider-side activity.

Workflow exhaustion stops only that workflow. Credit/auth/protocol/ambiguous
failures, account exhaustion and overshoot persist globally. No automatic retries,
ledger resets or stop clearing. Rotation/reconciliation requires explicit review.

## Outputs and gates

`data/typesafe_team_advisory.json` and `data/typesafe_shared_state.json` are private
operating outputs, captured through the normal publication boundary and excluded
from the public site. Dashboard cards carry private advisory fields without
changing canonical statuses, source freshness, grades, prices, stock or approvals.
Listing/legal/human/canonical-ID/payload-signature gates remain authoritative.
Local fallback is labeled local, never fabricated as Jev or a fresh API call.

Dry-run (no request and no output mutation):
```bash
python scripts/evaluate_team_typesafe.py --dry-run
```
Offline shared, team, receipt and wiring tests are mandatory in preflight and Pages.

## Jev 1.14 text adoption — 2026-10-19

The [official models reference](https://docs.typesafe.ai/models) accepts
`jev-1.14.0`; at review time `jev-latest` still points to 1.13 and `jev-preview`
to 1.14. Pinning avoids an accidental alias migration. The
[release announcement](https://typesafe.ai/blog/jev-1-14) highlights multilingual
improvements, but local Korean accuracy is not proven by configuration or mocks.

Only existing text Choice/Score/Noul advice is enabled. Image assets, Box and
long context remain disabled: neither Danger-Zone header is sent, assets are not
accepted by the shared payload contract, and Box remains unsupported. The
existing bounded input, credit proof, stop/receipt chain and canonical gates
remain mandatory. No SDK installation is needed for this direct HTTP client.

Input pricing remains $0.042/M tokens and output is free in the reference. This
is not evidence of an account's remaining free allowance. No live request was
made for this configuration change. A successful future authorized request must
record its actual response model; old 1.13 receipts remain historical evidence.
All 11 team roles receive the release briefing through the existing learning and
feed builders. A briefing is not proof of model execution or improved accuracy.
