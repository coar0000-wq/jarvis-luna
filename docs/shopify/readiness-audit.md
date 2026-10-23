# Shopify read-only readiness audit

This is a NEW reconstruction after the execution workspace lost the prior local
candidate. Historical checks are not evidence for these bytes. No old raw Admin
snapshot has been recovered, so synthetic fixtures are not live snapshot replays.

## Evidence and economics

`shopify_readiness_audit.project(snapshot, now=...)` is a pure private projection.
Input: `variants` with unique `variant_id` and `facts`; each observation has
`value`, `source`, and timezone-aware `captured_at`. Missing, stale, future,
invalid or sourceless evidence is unknown. Zero item cost and packed weight are
unknown; a confirmed zero shipping charge or other known cost can be meaningful.

For same-order KRW amounts the policy scenario merchandise floor is:

    ceil((cost + seller_shipping + other_known_costs + 3000) / (1 - 0.02)
         - customer_shipping_collected)

Customer-collected shipping is revenue, seller fulfillment is cost, and the
assumed fee applies to their combined order revenue exactly once. The 2% shared
`payment_fees` policy is an assumption, never a verified processor fee. Unknown
costs are not invented; actual fee/contribution remain null and full profit is
unverified. Native USD Admin prices are never converted with an invented FX rate.

Admin item weight zero never establishes measured packed weight. Untracked
inventory is not stockout. Tracked quantity zero is only an observation; with no
policy/availability evidence purchase availability remains unknown.

Raw hold text and its original `source_updated_at` are retained privately. Known
'DRAFT ONLY' versus ACTIVE and zero-placeholder versus positive native price
claims create review findings only. They never clear holds or prove public
publication. A fresh fetch does not refresh the hold's source update timestamp.

Human CVR requires converted human sessions / human sessions, with matching
cohort and period, integer counts and 0 <= converted <= sessions. Zero human
sessions yields null. Orders per human session is a separate metric and may
exceed one. Bot observations cannot supply the human denominator.

Caller-declared authenticated channel observations remain caller-only reports;
Catalog/Google/GSC eligibility stays unknown. Existing ProductGroup/Offer,
canonical, robots and sitemap observations do not prove channel acceptance or
indexing and do not require duplicate SEO markup. Proposed/applied/verified/
measured records stay separate; a generated timestamp completes no stage.

## Reader and existing integration

The dedicated reader permits fixed GraphQL queries only, pinned to the explicitly
configured host (`coarfamily.myshopify.com` or the canonical host) and exact
shop identity. The response must name canonical `rb3zh1-i1.myshopify.com`; the
request never automatically changes host or follows an alias/redirect. It uses existing transport helpers,
never a mutation-client superclass. Root products and every variant connection
must terminate without repeated cursors or duplicate identities. Root updatedAt
is required and every variant page must match it; a second complete metadata
pass detects catalog drift. This is not a transactional snapshot. The offline
normalizer also requires complete=true. Existing write
product/inventory scopes include their corresponding read scopes; no new grant
is requested. Missing scope proof blocks collection. Optional field denial is
unknown rather than zero; required identity/pagination errors block collection.

`inspect_readiness` delegates recommendation eligibility to the unchanged shared
`current_s_eligibility.assess_current` contract. It adds no competing 48-hour or
72-hour S policy. Missing canonical source documents remain unknown.

The existing AEO inspection passes its existing token and explicit configured
host. Its public report is committed to Git and printed in the Actions job
summary. Therefore only a fixed allowlisted status and missing-evidence reason
may leave the readiness hook. `write_report` repeats that allowlist before
serialization. Full `project` facts include costs, inventory, holds and provenance
and must never be auto-committed, published to Pages or uploaded as artifacts.
Artifacts are not assumed private. Detailed evidence may only be retained in a
separately reviewed local output. Exception messages and arbitrary exception
class names are not published. APPLY remains blocked.

## Verification limits

Focused local tests are separate from full CI. Synthetic fixture checks do not
verify a live pinned-API execution. Runtime deployment, approved remote upload,
remote CI and readback remain separate work. No Shopify mutation is authorized.
