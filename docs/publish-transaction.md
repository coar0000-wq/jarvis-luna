# Safe publication transaction

`publish_transaction.py` captures an immutable delta against the workflow checkout HEAD. It does not commit, reset, clean, or stage the caller checkout. Production publication uses a detached temporary Git worktree at freshly fetched `origin/main` and a normal `HEAD:main` push, never a force push. Only named data/Obsidian paths are eligible.

```sh
python scripts/publish_transaction.py \
  --paths "$PUBLISH_PATHS" --message "$PUBLISH_MESSAGE" \
  --regenerate-dashboard true --audit true
```

Optional flags: `--max-attempts 1..3`, `--dry-run`, `--collector-report PATH`, `--execution-id RUN:ATTEMPT`. Dry runs still rebuild and validate in isolation, but never push or change caller bytes. There are no arbitrary command/test-hook CLI options. Current collector evidence is captured as immutable bytes and restored to regenerated runtime through the verified `collector_result.py attach-runtime` API.

## Merge policy

`config/publish_policy.json` defines ID fields, derived outputs, commerce inputs, runtime commands, candidate-protected outputs and baseline files.

- Distinct source-product/record additions merge by ID. Independent keyed accumulated records are preserved. Explicit append-only scalar arrays and append-only Markdown tails can preserve both additions.
- Competing edits to one source identity, unknown scalar/array semantics, binary/model conflicts and note rewrites fail closed. This is the declared same-ID conflict policy; no source value is silently chosen by file ownership.
- Valid timezone-aware concurrent metadata timestamps can retain the later observation. Merged container counts are recomputed. Metadata timestamps never confer process/fetch success.
- Local derivatives are discarded and rebuilt from final sources, not selected with `--ours`. Final known commerce regeneration remains local-only with TypeSafe/Gemini disabled and model keys removed from subprocess environment. Runtime/ops/team alignment is rebuilt after source changes even when caller regeneration preference is false.
- A main change to producer code, policy or workflows aborts the transaction and requires a fresh collection on the new revision. The guard includes root-level Python producers, `requirements/` locks, root requirements/constraints files and supported root dependency manifests. It does not validate newly changed dependencies with the earlier environment or graft outputs produced under a different program onto new code.
- Missing required paths and exact-path staging failures are hard failures. Newly generated undeclared artifacts are hard failures.

## Explicit removals

Source identity/field removals, cumulative scalar ID/history removals and file deletion require `data/publish_deletions.json` entries containing exact `path`, SHA-256 of the immutable baseline bytes, nontrivial `reason`, and `policy_ref`. Identity removals require exact `ids`; file removal requires `delete_file: true`. A changed remote identity/file cannot be deleted under an old baseline authorization. Source pipelines which intentionally prune records must produce this evidence before calling publication; no generic deletion waiver exists.

## Transient execution snapshots

The policy lists exact volatile containers, not a blanket exemption for JSON dictionaries. Daiso `collection_status.last_run`, `last_attempt`, current `prefetch_policy`, `crawl_state.last_run`, and specific Core/Deep collector and release-quality report files are per-run snapshots. Their transient fields and per-run result lists may change without a source deletion manifest. Two competing run snapshots are atomic conflicts and are never combined into a fictional hybrid execution. `crawl_state.failed` can clear a recovered failure only when remote failure evidence is unchanged; a new independent remote failure is preserved, and a competing update blocks deletion.

`last_success`, `last_candidate_success`, accepted candidate `items`, operating product identities, visited-ID history and arbitrary dictionaries remain outside those exemptions. Entire report-file deletion still requires an explicit file deletion manifest. The latest-success evidence therefore cannot disappear just because the current attempt changes schema or becomes `no_change`.

## Validation and retries

Both `check_release_quality.py --phase candidate` and `--phase final` run against the actual isolated final state and a base data snapshot. `--audit false` can omit full team-report audit for narrow observation publication but cannot omit either release gate. Every push rejection starts a new fetch, fresh worktree, immutable delta application, regeneration and both release checks, at most three attempts. Exhaustion is explicit failure and last-good remote remains intact.

Candidate-only publication recomputes only candidate comparison and runtime/ops/team metadata. Operating products, scoring, pricing, gates, shortlist, action queue and export bytes are protected by exact pre/post checks. No candidate is promoted, approved, sent to a model, registered or published to Shopify by this mechanism.

## Isolated verification

`python scripts/test_publish_transaction.py` creates only temporary local bare remotes. It injects independent additions, same-ID conflicts, malformed JSON, naive timestamps, unknown binary conflict, explicit deletion with wrong hashes, quality/staging failures, push races, retry exhaustion and dry-run behavior. It also covers zero-to-candidate and candidate-to-no-change Daiso snapshots, failure recovery, preservation of cumulative records, root-producer/dependency changes, and mandatory candidate/final quality checks with `audit=false`. Tests verify remote preservation and the caller dirty checkout remains unchanged. No failure injection, test commit or test push targets operating main.

The production script deliberately blocks source shapes without an explicit safe merge rule instead of claiming universal loss-free merges. Heavy full worktree checkout/regeneration is intended for Linux Actions; desktop smoke tests should use isolated fixed fixtures rather than the 84k-note live corpus. No dependency installation, subscription changes, API spending or credential disclosure is performed by this script.
