# Actions source outcomes and release quality

## Required versus optional

Core requires local `build_product_master.py --inject-s`, current canonical runtime generation, current-run evidence aggregation and release quality. External YouTube is optional: its RSS path is currently robots-blocked and explicitly records skipped/degraded with no network attempt. If a permitted future RSS path is enabled, its instrumented HTTP-200/Atom validation can report real source-fetch and new/updated counts; tests only mock that path. An outage is not a successful fetch. The old `obsidian_realtime_sync.py` is not called: inspection found synthetic Phase26 claims written to the runner home directory, not repository synchronization. Repository graph processing remains in Deep's real-record pipeline.

The old Core `google_search_data_collection.py` is explicitly skipped. Its `build()` returns eight hardcoded growth values and rewrites only the execution timestamp. It is not real Google Trends fetching. Existing dataset bytes are retained but the current result identifies them as unverified cache. Existing Google News/public channel collection outside that synthetic Core call is untouched.

Deep keeps external RSS/search/manual enrichment/advisory optional while canonical corpus/graph, local model evaluations, post-exclusion master/score/pricing, legal/listing/export protections and final runtime/architecture validation remain required. Its 57 substantive results are 17 required and 40 optional. Normal baseline rejection retains prior weights; a model evaluation process error blocks publication of any partial model writes. Real Knowledge Sync also schedules only baseline-evaluated tuning, not direct pre-evaluation training. No model routing credentials or promotion thresholds are changed.

## Actual outcome evidence

`collector_result.py run --name NAME --required|--optional --output PATH [--artifact PATH ...] -- COMMAND` records subprocess exit code, attempt/completion times and observed artifact hashes. JSON artifacts reject HTML/invalid JSON, including blocked responses. Raw and semantic hashes are separate; recursive run/capture timestamps do not count as content change. Zero new/updated counts are emitted only for a validated unchanged artifact; unknown counts stay null.

Process success does not establish source-fetch success. For uninstrumented Deep collectors `last_successful_fetch_at` stays null with `fetch_verification=not_instrumented`. The Core YouTube adapter, selected by `--fetch-evidence PATH`, writes current-execution source evidence with HTTP/Atom validation, queried/succeeded/failed feed counts, bounded current timestamp, parsed/new/updated counts and an exact output-file SHA binding. Partial valid-feed failure is degraded; no valid feed fails, blocked HTML is not Atom, and robots denial is skipped without network or a successful-fetch timestamp. Known product/video identity arrays can produce actual local new/updated counts against observed before/after snapshots without asserting a source fetch. `--skip-reason` explicitly records not-attempted work while preserving source bytes.

`aggregate --results DIRECTORY --report PATH --expected NAME:required|optional ... [--runtime PATH]` checks schema, name, required flag, exit/status agreement and current `GITHUB_RUN_ID:GITHUB_RUN_ATTEMPT` identity. Missing expected result files, including a process killed before writing evidence, fail closed. Required failure blocks publication. Accounted optional failure/explicit unverified skip yields `degraded`; GitHub's conclusion can remain success because it has no degraded conclusion. `pipeline_health` in runtime records the same current outcome and counts. Summary reports operational status explicitly.

`attach-runtime --report PATH --runtime PATH [--execution-id ID]` reapplies immutable current outcome evidence after final merged-state runtime regeneration. The helper does not refresh runtime timestamps or change commerce/approval data.

## Quality gates

`check_release_quality.py --phase candidate|final --report PATH [--root ROOT] [--baseline ROOT] [--collector-report PATH --execution-id ID]` is offline and uses no model/API. Its policy is JSON-compatible YAML (`config/quality_policy.yml`), requiring no additional parser for production.

Required data must parse and pass typed nonempty/unique product identity, canonical registry/source joins, master-score joins/ranges/grade counts, pricing identity and quantity/fee/profit/unit/margin arithmetic, sourced FX range/freshness (maximum four days; legacy provider labels must match actual collection-status rate/date/provider/official endpoint and bounded successful observation time), runtime source count and separate candidate safety checks. When current collector evidence is supplied its failure flags and runtime `pipeline_health` must agree. Existing `validate_commerce_architecture.py --require-ops-runtime` still validates full commerce/legal/payload-approval/heartbeat protections.

Candidate and final phases run identical integrity rules against different snapshots. The final publisher must supply its immutable remote baseline. Every removed operating `pd_no` is delegated to `daiso.product_change_ledger.validate_removal_evidence(root, baseline, removed_ids)`, which validates actual baseline/after snapshots, archived originals, policy/threshold provenance and offer arithmetic. A bare `verified=true` assertion or a count ratio never approves deletion. Missing or invalid ledger evidence blocks rather than guessing that the loss was policy. Candidates remain comparison-only and never update grades, approval, operating quantity or Shopify publication flags.

Deep's previous API scan of failed steps happened after publication and swallowed API errors. It is removed. Each unconditional substantive stage writes a current result before publication; the aggregate and quality gate run with `always()` and the publication explicitly requires both outcomes to be success. Conditional browser setup remains normal hard-failing workflow control and cannot publish on failure.

## Testing

`test_collector_result.py` and `test_release_quality.py` use isolated temporary fixtures. They inject nonzero exits, missing results/artifacts, invalid JSON/HTML, stale execution evidence, optional failures, master/ID/score/FX/pricing/count corruption, unknown operating losses and runtime status disagreement. No live Deep run, source mutation, model/API call or operating main failure injection is needed.
