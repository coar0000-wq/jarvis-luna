# Exact two-DRAFT copy review planner

The offline planner remains read-only. The companion executor and manual workflow
now implement the separately authorized application path described below. They
are local code only until merged and deployed; no production ticket is included.
The daily importer and gallery executor are unchanged. Do not report local tests
as a completed store correction or production execution.

## Bound scope

Shop `gid://shopify/Shop/82748997889`, supplier `1073406` -> product
`gid://shopify/Product/9705391259905`, supplier `1033789` -> product
`gid://shopify/Product/9705431761153`. Both must currently be DRAFT, have the exact
supplier tag and recorded variant IDs/SKUs, and have either the reviewed old title
or the exact new title. Unknown content causes a hold.

`data/manual/draft_copy/verified_fields.json` records the exact reviewed substitutions
and official supplier image URLs/hashes. It does not include/publish image bytes.
The official English THE LAB product name is visible on its tube. LG's supplier
notice supports the two weight conditions and `(주)엘지생활건강` legal entity. Other
manufacturer/INCI/efficacy content is not added by this narrowly scoped patch.

Rights, actual-stock physical label, INCI and safety approvals remain false.
Source hash equality establishes which bytes were reviewed, not legal authority
or proof that the actual stock matches the supplier's photograph.

## Inputs and command

A full, fresh (<=300 seconds) snapshot must use the existing gallery snapshot
schema and also include `product.descriptionHtml`. The normal gallery reader
currently omits that field, so its output alone is intentionally rejected. A
companion authenticated reader collects the body and protected state consistently,
with complete pagination and before/after consistency checks. The earlier small
connector product JSONs are useful observations but are not complete protected
snapshots; do not fill absent fields with guesses or mark them complete.

```
python scripts/plan_draft_product_copy.py \
  --snapshot /private/fresh-complete-snapshot.json \
  --pd-no 1033789 \
  --evidence-root /private/draft-product-assets-20261022 \
  --output /private/1033789-copy-plan.json
```

Repeat read-only preparation for 1073406. The evidence root contains the exact
`sources/` filenames specified in the policy. Missing, symlinked, out-of-root or
hash-mismatched sources hold preparation. A plan-validation failure before output
writing leaves an existing output file unchanged. Output I/O failure is different:
replacement may already have occurred before directory fsync fails. The output
state is then uncertain; neither unchanged output nor successful durable saving
may be assumed. Inspect the bytes/digest and rerun read-only preparation. File
presence alone is never a successful current plan or fresh approval.

Only literal, uniquely matched old text is replaced. Existing sections, cautions,
ingredients and richer content remain byte-for-byte outside the exact replacements.
Already corrected text is a no-op. Missing/duplicated/conflicting clauses hold
instead of replacing the full body with a shorter generic template.

## Bounded execution scope and exact plan approval

After code merge/deploy verification and real fresh read-only plans, the companion
executor requires an explicit bounded ticket containing: exact shop ID plus verified
canonical/transport domain, the two product IDs, code commit, each plan digest,
exact before/after title/body, protected-state digest, execution ID and expiry.
The approval must authorize only these exact title/body changes on existing DRAFTs.
Never treat these offline plans, raw source images, or a passing test as that ticket.

The companion executor uses a durable write-ahead checkpoint, fresh pre-write
revalidation, one-attempt tracking, uncertain-write reconciliation and full
protected-field readback. No blanket retry after timeout; no claim of a server-side
compare-and-swap. The offline planner still has `apply_allowed=false`; only the
separate execute command with an exact digest and verified checkpoint can write.

`verify_readback` is a pure helper used by the companion executor: it checks exact planned copy
and every other captured field, excluding only observation and update timestamps.
It does not fetch state, authorize execution, accept a legal agreement or approve
product safety. Current status, handle, options, variant prices/SKUs/inventory,
media and channel publications are protected.

## Local checks

```
PYTHONPATH=scripts python -m unittest scripts/test_plan_draft_product_copy.py -v
PYTHONPATH=scripts python -m unittest scripts/test_apply_reviewed_product_gallery.py scripts/test_reviewed_gallery_workflow.py
```

All fixtures are synthetic; source hashes in synthetic tests are explicitly mocked.
The actual source files were separately SHA256-verified against the review record.
The planner intentionally does not translate or invent INCI, infer image rights,
claim clinical/safety approval, or make a two-pack photo from a one-product image.


## Implemented executor and workflow

`apply_reviewed_draft_copy.py` provides prepare, execute (dry-run by default),
reconcile, and reconcile-artifact. Its consistent live reader adds descriptionHtml,
vendor and productType around the existing complete paginated gallery snapshot,
checking body/title/updatedAt before and after. Official schema discovery confirmed
the new query and productUpdate fields on 2026-10-22; the code-validation endpoint
returned "validation skipped", so static API validation is not claimed.

The manual workflow is `.github/workflows/shopify-reviewed-draft-copy.yml`. It is
main-only, shares importer concurrency without cancellation, and defaults to
apply_copy=false. No schedule or production approval ticket is included. It runs
network-disabled tests, fetches original evidence into RUNNER_TEMP (never publishes
image binaries), prepares the exact plan, checks its requested digest, uploads an
immutable 30-day checkpoint, then permits one title/body mutation. Results retain
false image/label/INCI/safety flags. Result JSONs are retained even after failure.

The scope file lives at data/manual/draft_copy/tickets/<ticket>/scope.json and must
contain schema_version=1, pd_no, exact product_id and shop_id, verified canonical_shop
and transport_shop, expected_status=DRAFT, execution_ticket, authorized_at,
expires_at (at most 24 hours later), and allowed_fields=["title","descriptionHtml"].
These are recorded authorization facts, not fields to fabricate. A single user
approval can cover both named corrections; the workflow executes one product per
run, using one scope/plan per product and reporting partial outcomes separately.
No atomic two-product transaction or automatic rollback is promised.

After merge/CI verification: dispatch read-only with review_ticket. Review the
actual plan. For an authorized exact application, dispatch the same ticket with
apply_copy=true and expected_plan_digest. The code/policy/source/protected state
must match. The operation-specific immutable artifact is independently verified
against GitHub metadata, ZIP hash, exact bytes, run/attempt/commit/workflow and prior
artifact history. Prior checkpoint -> reconciliation required, never blind retry.

A lost runner or write_unknown is recovered with apply_copy=false plus the original
reconcile_artifact_id, reconcile_artifact_digest and expected_plan_digest. Recovery
verifies the original checkpoint and reads only. Missing/expired evidence or state
drift holds. A new execution ticket must never be used to evade an uncertain write.

Readback checks every captured protected field and the exact planned copy. If the
remote request is accepted but local journal saving fails, journal_saved=false is
reported; a verified readback means verified remote copy, not a durable local save.
A checkpoint always exists before writes, and restoration never writes. Any I/O
failure after replacement can leave new bytes in place; no automatic retry follows.

Additional local checks:

```
PYTHONPATH=scripts python -m unittest scripts/test_apply_reviewed_draft_copy.py scripts/test_reviewed_draft_copy_workflow.py
```
