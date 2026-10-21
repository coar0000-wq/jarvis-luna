# Offline US human sales and wording review

This is a local review tool, not a collector or Shopify writer. It does not
change products (including ACTIVE products), prices, Markets, shipping, gates,
team feeds, approvals, or publication state. A wording draft does not itself
produce visits or sales. Nothing runs automatically.

## Existing paths and the narrow integration

- `scripts/ai_shopping_copy.py`: reuse its pure, escaped identity FAQ generator.
  No product type, size, directions, or warnings are inferred or supplied here.
- `scripts/build_listing_copy_local.py`: existing canonical listing/gate writer;
  intentionally not called. This review is not an importer row or an alternate
  path around its prerequisites.
- `scripts/build_team_feeds.py`: includes source collection; intentionally not
  called. Channel wording here is a review proposal, not channel publication.
- `data/us_claim_rules.json`: the existing conservative banned-expression list
  is applied to wording; missing/malformed rules block wording only. Passing this
  list is not a safety, rights, label, or legal approval.
- Existing checkout-price evidence remains separate. Neither its checkout
  success nor this metric contract establishes business approval.

Only three new files are needed: the module, its synthetic tests, and this note.
There is no scheduled job, new data fixture, network dependency, or live data
adapter. The standalone test command to register in preflight is:

```sh
python -m unittest discover -s scripts -p 'test_us_human_sales_review.py' -v
```

## Local inputs and invocation

Keep real evidence and generated reviews outside every public checkout. Never
commit customer, order, visitor, session identifiers, private query responses,
or real store measurements as fixtures. Tests use only `example.test`, synthetic
GIDs, and synthetic counts. This CLI refuses output inside its own checkout or
another detected Git checkout (including worktrees), does not overwrite any
existing file, and does not scan for evidence. An empty sandbox `.git` guard is
not a checkout; a `.git` file/symlink or directory containing HEAD/config is.
Input/output paths containing symlinks are rejected. New output files use 0600
permissions on POSIX. Shell redirection of stdout is outside these checks; the
operator must still choose private storage rather than a publicly served folder.

```sh
python scripts/us_human_sales_review.py \
  --shop-gid gid://shopify/Shop/1 --canonical-domain example.test \
  --audit /private/local/audit-envelope.json \
  --audit-source /private/local/aggregate-snapshot.json \
  --product /private/local/product-envelope.json \
  --product-source /private/local/product-snapshot.json \
  --output /private/local/new-review.json
```

These paths and identities are illustrative, not actual store information.
Either audit or product input may be omitted independently. With no arguments,
the CLI prints a safe unavailable review to stdout and writes no files.
Omitting the independent expected shop identity blocks admission. No default
store, period, product, source, or output is inferred. Structural file/JSON or
output failures exit 2 without echoing private source content; admitted files
with unavailable sections produce a review containing the specific reason.

## Envelope and source provenance

Both envelopes have these common fields:

```json
{
  "schema_version": 1,
  "shop": {"shop_gid": "gid://shopify/Shop/1", "canonical_domain": "example.test"},
  "observed_at": "2026-10-21T20:00:00+09:00",
  "source": {
    "kind": "local_snapshot",
    "ref": "synthetic:original:query-response-reference",
    "raw_sha256": "SHA-256 of the exact local source file bytes"
  }
}
```

The hash placeholder above must be replaced by 64 lowercase hex characters.
`shop_gid` and the bare lowercase canonical hostname must match the independent
CLI arguments exactly; redirects and aliases are not guessed. Observation time
must include an offset and cannot be in the future; the report also exposes its
KST equivalent as `observed_at_kst`. The source file must contain
the same `shop` and exact `observed_at` string. A hash match proves only that
these local bytes were used, not that Shopify authenticated their contents.

A local aggregate snapshot is a documented normalized input, not an asserted
standard Shopify export format. A human must preserve the actual original
query reference and its dimensions, coverage, period, and units during
normalization. If original bytes are unavailable and all that remains is a
tool-response transcription, explicitly use:

```json
{
  "source": {"kind": "source_transcription", "ref": "synthetic:tool-response-reference"},
  "transcribed_payload": {"shop": {}, "observed_at": "...", "queries": {}}
}
```

This is a fragment: fill in the same required envelope and payload fields as
the snapshot contract below. Omit `raw_sha256` and the corresponding `--*-source`
argument. The report labels this `source_transcription`, with no source hash and
`source_bytes_matched: false`. It may report the explicit transcribed counts;
it never calls them independently verified. Missing original references block
both input kinds. Arbitrary `verified`, `complete`, `business_approval`, or
publication flags in any input cannot grant authority.

Every output retains `verified: false`. Source references are not echoed to
avoid leaking private query URLs or tokens. The input reference and output hash
(when present) let the local reviewer find the evidence.

## US-human aggregate contract

The audit envelope and source payload both include the exact same `period`:

```json
{
  "start": "2026-10-20T00:00:00+09:00",
  "end": "2026-10-21T00:00:00+09:00",
  "timezone": "Asia/Seoul"
}
```

Only `start`, `end`, and `timezone` are allowed period keys. Extra metadata,
including customer records, is rejected rather than copied into the report.
Period is start-inclusive/end-exclusive. Both offsets must be KST (+09:00),
start must precede end, and end cannot exceed observation time. Every query
must describe that same store and period; do not combine disjoint exports.

The source payload also contains `queries`, keyed by these six metric names:

- `sessions`, `add_to_cart_sessions`, `checkout_sessions`, `converted_sessions`:
  unit `sessions`; the latter three count distinct sessions meeting that event
- `pageviews`: unit `pageviews`
- `product_views`: unit `product_views`

Each query has the following shape (synthetic example):

```json
{
  "status": "ok", "coverage": "complete", "unit": "sessions",
  "shop": {"shop_gid": "gid://shopify/Shop/1", "canonical_domain": "example.test"},
  "period": {
    "start": "2026-10-20T00:00:00+09:00",
    "end": "2026-10-21T00:00:00+09:00", "timezone": "Asia/Seoul"
  },
  "rows": [
    {"country": "US", "traffic": "human", "value": 10},
    {"country": "US", "traffic": "bot", "value": 500},
    {"country": "KR", "traffic": "human", "value": 700}
  ]
}
```

All six shown query keys are required and no others are admitted. Each query's
`shop` and `period` must exactly match the source/envelope scope. A different or
missing per-query scope makes that metric unavailable, including conversion's
numerator; globally matching metadata cannot override a mismatching query.
Only the explicit US/human value is reported. Bot, unknown-traffic, KR, and all
other countries are excluded, regardless of larger counts. No IP location or
human/bot classification is invented. Country values are uppercase two-letter
codes or `UNKNOWN`; aliases such as `USA`, `United States`, and `us` are rejected,
so a duplicate synonym cannot inflate or override the US row. Rows contain only
country, traffic (`human`, `bot`, `unknown`), and nonnegative integer value;
booleans, NaN, fractional/negative counts, duplicate scopes, and extra row fields
are rejected. This contract accepts aggregates only, not personal records.

Missing query, failed status, unknown/partial coverage, wrong unit, or absent
explicit US/human row means `unavailable`, value `null`, and a reason. A missing
US row is never interpreted as zero, even if coverage was declared complete.
Failed product views stay unavailable; pageviews are never substituted. Orders
cannot substitute for converted sessions. Event-session counts greater than
sessions are invalid. No conversion rate is emitted when either required
metric is unavailable; a zero denominator specifically returns `null` with
`zero_us_human_sessions`. Otherwise the rate is converted sessions / sessions,
a fraction rather than a percentage. Zero conversions over positive sessions
can correctly yield zero. None of these arithmetic checks authenticates sales.

## Product identity and English review copy

The product envelope adds `product_gid` and `english_identity_reviewed: true`.
Its source payload adds a `product` object containing matching `id`, source-listed
English `title`, and observed `status` (`ACTIVE`, `DRAFT`, or `ARCHIVED`). The
English title is required to be plain ASCII, 1–70 characters, and explicitly
reviewed; no translation, truncation, or marketing enrichment is invented.
It must be the title actually observed in the source. A proposed English
translation of a Korean supplier title must not be relabeled as an observed
source title; keep that translation in a separate review document. An explicit
English-review flag does not authenticate a translation or source facts.
Snapshot identity is not ingredient, efficacy, quantity, or safety evidence.

This deliberately narrow path has no quantity/efficacy/label adjudicator. Titles
containing recognized quantity units, efficacy wording, or shipping/rights
claims are held rather than silently stripped or repeated in SEO/FAQ text.
Only the three product fields above and the three source fields (`shop`,
`observed_at`, `product`) are admitted. Product warnings, net contents, conflicts,
holds, or additional review context require separate review and block wording.
Never remove known warnings or conflicts during normalization to fit this
schema. Preserve that context so the tool returns a hold. In particular, a
known conflicting-size product remains held even when its short title itself
has no size. Korean-source products awaiting translation are not reported as
copy-complete by this tool. Source replay must report each actual product result
rather than extending a passing identity-only example to the whole catalog.

The generator proposes a search title/description, one exact-title search phrase,
a neutral channel caption, and the existing identity FAQ. Search phrases have no
search-volume or ranking claim. Customer-facing text contains no internal
publication instructions; missing safety/rights/label/shipping information is
kept in the review's application holds. Conflicting or unconfirmed net contents
are not inferred from another field. Approval still requires reviewing the title
itself and the actual label; a name containing a claim does not validate it.

All outputs have `non_executable: true`, `review_only: true`,
`business_approval: false`, `eligible_for_shopify_import: false`, and
`publication_allowed: false`, including ACTIVE products and inputs asking for
true approval flags. No Shopify save, public edit, or settings change is made.
