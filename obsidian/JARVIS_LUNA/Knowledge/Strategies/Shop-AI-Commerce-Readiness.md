---
type: strategy
status: evidence-bound-experiment
updated: 2026-10-20
tags: [shopify, shop, ai-shopping, reviews, evidence]
---
# Shop and AI-shopping readiness

Related: [[../Topics/Shopify-Commerce]]

This is an authored strategy and verification protocol. It is not a finding about Shopify's proprietary ranking algorithm, a promise of top placement, evidence of customer demand, or product/legal clearance.

## REA-style evidence boundary

Use the separation adopted by the local REA tooling: **observed fact, derived interpretation, hypothesis, residual unknown**. An observation must retain its source, capture time, scope and verification result. Static analysis of local software does not establish Shop ranking weights, live review acceptance, checkout eligibility or sales causality. No reverse-engineering of a Shop ranking system is claimed here.

| Question | Required authority | Not sufficient |
| --- | --- | --- |
| Is a setting enabled? | Saved account GUI state and readback | A plan, a clicked button, or general documentation |
| Is a product eligible in a channel? | Channel/product approval evidence for the exact market | Assignment to a channel, ACTIVE status elsewhere, or an owner declaration |
| Can an AI surface finish checkout? | Exact channel's supported checkout route and merchant eligibility | Product discovery, a referral link, or a rendered payment form |
| Did the change improve sales? | Dated comparable customer measurements with own tests separated | Review counts, similarity, missing data coerced to zero, or a fresh report timestamp |

## Verified feature distinctions

Official documentation inspected on 2026-10-17 supports the following feature constraints. It does **not** prove that any merchant account is configured or approved.

### Reviews

- Shop's **Reviews from Partner apps / Display** setting governs display of accepted partner reviews in Shop. It is not the Shop-to-Judge.me import switch.
- Judge.me's Shop integration has a separate inbound Shop-review sync setting. Its Shop integration and Etsy integration are documented as free-plan features.
- Shop eligibility requires activated Shopify Payments and other store/product conditions. South Korea is not listed as a supported Shopify Payments business country. Do not change or misstate a merchant's actual country to satisfy eligibility.
- Partner reviews must meet Shop's authenticity and identity/order/product requirements. An imported review is not automatically an eligible Shop review.
- Etsy integration is **Etsy to Judge.me**, requires the owner's Etsy authorization and correct product mapping, and is not bidirectional review synchronization. Etsy-synced reviews are excluded from Judge.me-to-Shop display acceptance. Do not relabel or re-import them to evade that restriction.
- Shop's own review collection and the setting for reviews on purchases outside Shop are separate from partner-review display and Judge.me synchronization.

Sources:
- https://judge.me/help/en/articles/8362827-syncing-reviews-with-shop-app
- https://judge.me/integrations/judgeme-and-shop
- https://judge.me/help/en/articles/10713924-syncing-reviews-from-etsy
- https://help.shopify.com/en/manual/online-sales-channels/shop/product-reviews/sync-partner-apps
- https://help.shopify.com/en/manual/online-sales-channels/shop/product-reviews/manage
- https://help.shopify.com/en/manual/online-sales-channels/shop/eligibility/requirements
- https://help.shopify.com/en/manual/payments/shopify-payments/supported-countries

### AI channels and checkout

- ChatGPT discovery/referral and native in-channel direct checkout are different capabilities. Shopify's documented ChatGPT route sends shoppers to the store checkout; do not claim a nonexistent direct-checkout toggle.
- Google's direct checkout requires a US-based store and US customers, plus channel/catalog/policy eligibility and applicable terms. A US market alone does not make a non-US business a US-based store.
- Copilot direct checkout has US-customer and eligibility conditions. A third-party payment provider is not automatically disqualified, but actual provider/merchant support still needs verification.
- Shopify Catalog also evaluates account standing, activity and policy history over time. Its specific ineligibility message about legitimate, well-managed orders is not a missing enable switch. Do not manufacture customer orders, chargebacks, fulfillment records or sales history to bypass this gate. No fixed acceptance threshold or deadline is established by this note.
- The automatic **manage for me** option can enroll future channels or reactivate capabilities. It is not a substitute for evaluating each requested change, product gate, payment condition and billing boundary.
- Do not accept new billing terms, subscribe, purchase credits, or enable paid advertising while implementing this protocol. Do not infer a metered API is free from a model alias or a key label.

Sources:
- https://help.shopify.com/en/manual/shopify-catalog/requirements
- https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/agentic-home
- https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/chatgpt
- https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/google
- https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/microsoft

## Listing experiment: three semantic slots and FAQ

Generate three **evidence-bound slots**, not three mandatory claims:

1. **Recommendation target:** a modest shopping target supported by exact product identity, form or size. Do not infer skin suitability, pregnancy suitability, allergies, age suitability or efficacy from a name or INCI list.
2. **Usage scenario:** use verified, specifically sourced directions where available. A shopping-format description must not be presented as manufacturer application instructions.
3. **Not-recommended conditions:** use specifically sourced, admitted warnings. If no such evidence is available, leave this slot empty and retain an omission reason; do not invent contraindications.

FAQ answers may summarize admitted identity, type, net contents, directions or warnings. Unknown price, inventory, shipping, returns, review counts, authentic-review status and safety/FDA approval must not become affirmative FAQ answers. Every nested generated field is subject to the same prohibited-claim checks. HTML is escaped and rendered idempotently into new listing descriptions using the accuracy reviewer's admitted paragraph/strong subset. Existing manual/model text is preserved, but its former `ok` or reviewed metadata is not reused as factual approval: current source-accuracy checks run again and can retain it as `review_required`. Prerequisite-blocked records stay empty.

The optional model is not an authority for these facts. The deterministic local sections do not require another model request. New prose does not change `agent_ready`, `ready`, `public_ready`, manufacturer-safety substantiation, labels, inventory, duplicate prevention or execution authority.

## Store guidance and structured data

- Inspect the live theme and existing Product/Offer markup before adding anything. Prefer Shopify's current product/variant data for name, price and currency. Do not create duplicate or contradictory Product objects. A live check of both current public catalog products on 2026-10-17 found an existing ProductGroup, two Product variants and two USD Offers on each page, so no duplicate schema was added.
- Untracked inventory is not independently verified physical stock. Do not invent availability quantities or use unknown inventory as a verified stock claim.
- The merchant's latest approved policy on 2026-10-17 is **estimated delivery 5–7 days; no voluntary returns**, with statutory consumer rights preserved. The shipping text was saved in Shopify's policy GUI; the existing automated no-returns rules were retained. This supersedes the earlier 5–10-day/30-day-return draft. The estimate is not a guaranteed arrival date. Do not silently convert days to business days, invent free returns, or assert an independently measured carrier service level. Use the current published policy and its conditions before adding MerchantReturnPolicy/shipping schema.
- Use the actual policy and checkout URLs. Shipping quotes depend on the destination; do not convert a KRW configured charge into a supposedly measured USD delivered total.
- Shopify now documents a native `templates/llms.txt.liquid` root route. This special template has a restricted Liquid context: only `request` and `agents` are available, not `shop`, `product` or `collections`. A normal theme asset or a page still is not proof of a root response. The source counterpart is `docs/shopify/llms.txt.liquid`.
- Deployment verification is dated 2026-10-17, not a current-state claim for 2026-10-20. The merchant-specific summary was deployed and its actual public `/llms.txt` response was compared with the reviewed source after resolving the documented `agents` fields. It includes the approved 5–7-day estimate and no-voluntary-returns policy, without private contact details, generated reviews, stock quantities or channel-approval claims. The canonical Shopify-managed `/agents.md` is linked rather than replaced. On 2026-10-17, the browser reported the served document type as `text/markdown`; no `text/plain` response is claimed, and the complete raw HTTP header has not been captured. An llms guide is advisory text, not channel approval or an instruction that overrides shopper consent.
- Native template references: https://shopify.dev/docs/storefronts/themes/architecture/templates/llms-txt-liquid and https://shopify.dev/docs/storefronts/themes/architecture/templates/agents-md-liquid. Public deployment checked: https://coarfamily.myshopify.com/llms.txt.
- Publish only genuine review data; never generate ratings, fabricated reviews or unsupported social-proof/authorized-distributor claims.

## Prioritized measurement plan

1. Resolve observable eligibility/setup obstacles before attributing zero sales to copy.
2. Confirm exact product identity, packaging/volume, current price/currency, lawful claims, retained safety/label evidence, image rights and product-only media, real stock and market eligibility.
3. Verify saved review and AI-channel settings separately. Record accepted/rejected/unknown, market scope, observation time and the exact feature affected.
4. Introduce grounded semantic sections as a bounded copy experiment. Track impressions, product views, cart, checkout and completed orders with a declared window and comparable baseline. Missing metrics remain UNKNOWN.
5. Separate own setup/QA visits and carts from customer-demand interpretation. Never subtract an invented attribution count or call a setup test an improvement.
6. Treat better findability or conversion as a hypothesis until customer evidence supports it. No rank, exposure or sales guarantee follows from this note.

## Residual unknowns to retain

- Exact current merchant and product approvals for each Shop/AI surface.
- Which genuine, order-bound partner reviews pass Shop acceptance.
- Account-specific Copilot/direct-checkout/payment compatibility and any required terms.
- Published-policy conditions for delivery estimates and returns.
- Organic impressions, assisted conversions and the effect of the copy experiment.
- Proprietary ranking weights and causal effects, which are not established by local code inspection.
