# Persistent source recovery

## Ownership and authority

The existing secretary, eleven team leads and specialist capabilities own recovery. This adds fixed procedures, not JARVIS agents. REGISTRY, SOURCES and the execution POLICY_HASH remain unchanged. Recovery output never authorizes Shopify drafts, stock, sales, ads, payments, messages or publishing. Authenticated exact-payload L4 approval and all legal gates remain mandatory.

## Four distinct Daiso scopes

`daiso_pipeline_health.py` evaluates candidate discovery, operating captures, active-shortlist prices and complete workflow/publication independently. A discovery result, cached price observation, local dashboard rebuild, or older successful workflow cannot repair a failed publication. Original failed workflow history stays visible. Receipt payload flags do not verify themselves; authenticated GitHub run/attempt/job/step and exact artifact-byte evidence are validated out of band.

## Durable bounded actuation

`run_source_procedures.py` uses an external checkpoint plus `SourceProcedureStore`:

1. Load the exact checkpoint. Missing, conflicting or regressed continuity blocks execution. Routine runs cannot initialize or reset a store.
2. Fingerprint owned facts, fixed producer bytes and blocker codes. Generated/read timestamps do not create another failure episode.
3. Persist the claim and updated checkpoint before executing an owned, fixed procedure.
4. At most one network procedure per invocation; one attempt per team/invocation, two per unchanged episode, two-hour cooldown, 128 episodes and a 256-attempt lifetime budget per team.
5. Re-read the actual owned source and validate its byte hash, genuine capture clock, freshness and required scope. Exit zero is not proof of source health. Procedure verification never becomes execution-receipt or business authority.
6. Persist completion/checkpoint. Interrupted claims are reconciled by reads without replay, refunds, budget reset or invented original exit success.

Institutions without dated matching rows, legacy knowledge without genuine item clocks, and native graph sync without verified path/permission/heartbeat remain owner prerequisites. Auth, quota and robots stops are not automatically released.

## Shortlist observer

The observer remains read-only for the operating inputs. Its durable v2 reservation ledger has a 12-request/run limit, 24 requests per rolling 24 hours, 660-second admission deadline, 30-second HTTP envelope and 30-second safety margin. Robots delays are at least 30 seconds; longer delays must fit the deadline. Fresh captures have a 24-hour TTL. Failed/inflight member retries have a two-hour cooldown. Reservations precede HTTP; received results are saved before another read or sleep.

`--force` only reevaluates metadata. It bypasses no freshness, cooldown, stops, robots, request limits, deadlines or rollback checks. Existing capture clocks and lifetime history remain intact. Evidenced legacy checkpoints migrate without counter reset or fabricated timestamps.

## Failed-run continuity

Daiso, Core and Deep share `main-publish` concurrency. They restore authenticated main-run safety artifacts before actuation. The four-file source bundle is exact, hash-bound and lineage-checked. Operations state and immutable report bytes have a separate strictly validated restore path.

After verified continuity, safety artifacts are retained even if subsequent collection or publication fails. An unverified baseline must never be uploaded as a newer safety checkpoint. Pending restore markers block execution. Missing latest post-activation artifacts, conflicting histories, unresolved execution claims or unprovable evidence fail closed rather than erase stops or replay work. A runner lost before an authenticated checkpoint cannot be claimed recovered without the missing evidence.

Tracked Git snapshots are the durable record. Artifacts bridge failed publication: source safety retention is 14 days; compressed operations safety retention is 3 days. Artifacts are not a substitute for permanent Git history.

## Publication safety

Workflow, Gemini, MoE and Gosi diagnostic replacements retain exact HEAD/prior/current bytes and use the shared publication lock. Removal manifests bind both base and replacement SHA-256 values. Product facts, identities, source clocks and capture history are not diagnostic exemptions.

Immutable diagnostic snapshots preserve existing flat files; new files spill into deterministic two-hex SHA shards, bounded at 128 entries each and 256 shards. There is no pruning or reformatting. Capacity exhaustion is an explicit hold, never a budget/stop reset. Publication checks source-safety nonregression before and after offline generators.

## Honest reporting

The public operations board exposes only fixed-team status and limits. Credentials, raw goals, private paths and execution material are omitted; authority booleans are always false. Disappearing diagnostics are not recovery proof. Required source or legal evidence stays blocked until genuinely supplied and verified.

## Selection is not business clearance

The retained shortlist is a candidate selection and price-observation scope, not an authorization to create or publish a Shopify draft. An existing selected unit survives a legal hold without changing its IDs or original `added_at`. `eligible_pd_nos` and per-unit `business_ready` reflect the current listing gate separately; `business_authority` is always false. New rule-selected units still require the existing gate and evidence rules. Manual selection confirms selection only, never L4 execution.

If no selected member is currently eligible, the publisher invokes the exporter's explicit `--blocked-noop` path. It creates no new draft CSV, refreshes no old draft bytes and grants no clearance. The ordinary exporter still fails without this option. Architecture validation accepts retained drafts only when all four fixed CSVs are byte-identical to their committed Git baseline, remain within selected scope, and all normal draft/unpublished/stock-zero/deny checks pass. The current Action queue must contain no draft actions in this state. Legal, product-identity and authenticated exact-payload human approval holds remain blocked.

Channel validation during publication uses `--cached-only`. Fixed source-recovery procedures keep their separate bounded live-reader path. Cached validation never makes HTTP requests, writes source facts, advances capture clocks, registers a connector or releases an existing stop.

## Offline integration verification, 2026-10-05

- Concurrent main history and unpublished local read/report work retain 147 exact receipts/claims and 149 trusted operations files. Remote numbered events remain primary; the complete exact local chain and explicit projection map are retained under `docs/audits/operations_reconciliation`. This is not represented as a linear extension of unpublished local event IDs.
- Available base/local/remote cumulative run rows are unioned without pruning. Future display windows do not remove audit rows; an 8 MiB capacity hold requires an owned archive instead of reset.
- Windows stress fixtures demonstrated intermittent `PermissionError` (errno 13, winerror 5) during native ledger persistence. Production TypeSafe remains unchanged and fail-closed. Result-bearing assertions and an injected persistence-denial test prove reservations stay charged, the global stop persists, and no mock evaluation is replayed or refunded.
- Source-only repair commits and Daiso manual runs with auxiliary refresh disabled carry `[source-recovery-offline]`. Only the model/business listing-copy push job is skipped for that explicit marker; normal pushes and explicit listing-copy requests retain existing behavior. No credentials, model defaults, billing proof or standing routines are changed.
- Gosi S-grade seeding adds identity-only unverified observation targets, preserves existing evidence and creates no capture clocks or legal clearance.
