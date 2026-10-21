# Reviewed gallery: append-only execution

## Current release scope

The underlying executor supports one exact existing ACTIVE or DRAFT product, but the current workflow enforces `draft_review_only`: only an existing DRAFT can receive a reviewed append. ACTIVE products are limited to read-only plans/reconciliation until a separate exact public-change plan is approved. New work stays in DRAFT review; no existing ACTIVE product is rolled back to DRAFT. It does not create products, replace the hero, reorder/delete media, attach variant-specific images, change product text, publish, activate, or change prices/inventory. Existing `gallery_review.py` and the PR #40 importer fail-closed gate remain unchanged.

The repository contains no approved production upload ticket or newly approved image in this change. On 2026-10-21 the 10 ACTIVE products had 61 images; the 28 original information images were already present with identical decoded pixels despite different container hashes. Keep those images. The new DRAFT products 1073406 and 1033789 each had zero images. None of these observations authorizes an upload.

A text-only hero, uncertain supplier photo reuse, unsubstantiated before/after/efficacy text, mixed products, g/mL disagreement, or a comparison card mistaken for an exact two-pack image remains a review hold. Hero replacement needs a separate exact change plan; this append-only workflow cannot do it.

## Components

- `plan_active_product_gallery.py`: unchanged offline role/QA/reuse planning; 26 focused regression tests.
- `apply_reviewed_product_gallery.py`: one-product evidence validation, current Admin reads, immutable pre-write checkpoint, a single append mutation, and read-only reconciliation.
- `shopify-reviewed-gallery.yml`: manual dispatch on `main`; defaults to read-only preparation. Shares `daiso-daily-beauty-shopify` concurrency with the daily importer, without cancelling either run.
- Existing importer `scripts/daiso_daily_beauty_to_shopify.py`: keeps its existing gallery gate. This new executor does not set `gallery_status=approved`, bypass that gate, or treat generated `status=ok` as approval.

## Required review inputs

This repository is public. Never commit private contracts, credentials, personal information, or confidential evidence; Actions artifacts are not a substitute for a private evidence channel. Only use supporting material whose repository publication is explicitly permitted. A private-evidence workflow is outside this release.

Create `data/manual/gallery_upload/<ticket>/scope.json` and `manifest.json` only after genuine review. Repository review is required; the program checks recorded evidence consistency, not the truth of an arbitrary assertion or the reviewer's identity. Do not manufacture supporting documents, label readings, permissions, role rationales, or `pass` values.

The scope includes:

- `identity`: exact shop GID/domain, product GID, supplier `pd_no`, current title/handle/options, and every variant ID/SKU/selected option.
- `transport_shop`: the explicit credential endpoint, matching configured `SHOPIFY_STORE` before any credential is used. The API canonical shop domain remains separately bound in `identity`; no alias or redirect is guessed.
- `expected_status`: the observed ACTIVE or DRAFT status, preserved during execution.
- `execution_ticket`: a new explicit operation identifier; do not change it to evade an uncertain prior write.
- `authorized_at` / `expires_at`: zoned timestamps, maximum 24 hours apart.
- `asset_sha256s`: exact final asset hashes, unique and at most 20.
- `allowed_source_hosts`: subset of the hard-coded `cdn.shopify.com` / `raw.githubusercontent.com` allowlist. A new append requires a raw GitHub asset at an immutable 40-character commit path. CDN URLs remain valid for reading/reusing existing images, but cannot authorize a new append because a version query does not pin immutable bytes.

The manifest reuses the existing `gallery_review.py` schema and additionally binds `execution_identity`. It references real local source bytes, final output bytes, source URLs, and SHA256-bound review receipts. Rights receipts must bind source/output hashes, exact identity, supporting document bytes and reproduce/adapt/store-gallery permission. Label receipts require actual package-label evidence for the exact product, capacity and quantity. Asset receipts bind source/output hashes, role evidence, face/claim/residual-text/SKU QA, exact identity, and for new assets the final public asset URL and reviewed `alt_text`. Unverified data or booleans alone do not replace those records.

For reuse of an already attached image, optional `attached_media_id` and `attached_image_url` must bind to its matching decoded pixels. Container SHA alone is never a reason to re-upload. A broad comparison card is not an exact option photograph.

## Manual run order

1. Merge/deploy tested code first and complete the genuine review ticket. Coordinate main changes with an in-progress Core/Deep publisher; code changes can intentionally block an older run's publication.
2. Dispatch `shopify-reviewed-gallery.yml` on `main` with the ticket and `apply_images=false`. Review the resulting exact plan, missing roles, no-ops, holds and plan SHA256.
3. Apply only to an existing DRAFT after that plan and its scope are authorized. The workflow rejects ACTIVE/unknown status before authentication and records its operating policy in the result artifact. Scope status is then compared with freshly read actual status by the executor; declaring an ACTIVE product DRAFT cannot bypass this boundary. Dispatch the same ticket with `apply_images=true` and the exact `expected_plan_digest`. A new fresh read must produce the same digest. Only the observation clock is excluded; source/evidence, implementation bytes and protected product state remain bound.
4. Before the only mutation, the workflow uploads canonical `plan.json` and `journal.json` as an immutable checkpoint retained for 30 days. The executor independently verifies artifact ZIP digest, repository, workflow/run/attempt/code SHA, history and retention. Another checkpoint for the same operation forces reconciliation.
5. The executor re-fetches source bytes, repeats the current-state read, then appends once. It checks all old media IDs/order/URLs/pixels/alt, product status, prices, options/SKUs, variant-media links, inventory and publication records afterward. A concurrent external edit or processing delay yields `verification_pending`, never a success claim.
6. Record actual result separately from preparation/deployment. `verified` confirms the exact append/readback only. `gallery_complete`, `publication_allowed` and `legal_or_safety_approval` remain false even after a successful append.

No new credentials are created. Existing Admin token or existing app client credentials are used; any app token exchange is short-lived and not persisted. Missing read scopes, non-image/unready media, incomplete pagination, changed state, stale evidence or an inaccessible byte source hold execution.

## Uncertain result and restart

A timeout/error can occur after Shopify accepts an append. Never repeat that mutation blindly and never delete the journal to retry. The local state becomes `write_unknown`; the durable checkpoint survives a runner loss.

For a later read-only check, dispatch the same workflow with `apply_images=false`, the ticket, original plan digest, `reconcile_artifact_id`, and original checkpoint ZIP digest in `reconcile_artifact_digest` (64 lowercase hex characters). The workflow restores only the exact verified checkpoint and checks its intended shop/product before Admin reads. It skips new-plan preparation and all mutation steps. A completed original run is valid for restoration. If the checkpoint is unavailable/expired or the observed state differs, hold and investigate; do not invent a replacement approval.

The executor has no server-side compare-and-swap guarantee against a merchant editing simultaneously. The pre-write and post-write checks detect differences but cannot roll them back. They never mutate unrelated fields to force a match.

## Verification status

Focused mock/offline tests exercise rejected evidence, stale/drifting state, duplicate pixels, idempotency, forged/missing checkpoints, source fetch restrictions, unknown writes and protected-field changes. No production image has been uploaded by these tests. API schema lookup confirmed field definitions, but the connector's query-validation endpoint returned `validation skipped`; do not describe that response as a successful static query validation. A real read-only plan against the deployed code remains required before any authorized application.

Official API reference: [Shopify Admin GraphQL 2026-10 productUpdate](https://shopify.dev/docs/api/admin-graphql/2026-10/mutations/productUpdate), specifically adding new media to an existing product using its ID. Media processing is asynchronous; a mutation response alone is not completed readback.

Existing public product content changes would immediately affect its public page even without activation/publication changes. This release retains the general executor capability but does not authorize that operation in the current draft-review workflow. Existing products still receive read-only review and improvement plans; genuinely reviewed assets are required for any later exact authorized apply.
