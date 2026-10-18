const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../index.html'), 'utf8');
const start = html.indexOf('  function stepState(it){');
const end = html.indexOf('  var live=0, draft=0, none=0;', start);
assert(start >= 0 && end > start);
const ctx = vm.createContext({sSet: {known: 1}});
vm.runInContext(html.slice(start, end), ctx);
const state = row => Array.from(ctx.stepState(row));
assert.deepEqual(state({grade:'-', images:11, status:'DRAFT'}), ['wait','queued','queued','queued','queued']);
assert.deepEqual(state({grade:'-', source:'manual_owner_image_localization_example', images:11, status:'DRAFT'}), ['done','wait','queued','queued','queued']);
assert.deepEqual(state({grade:'S', images:11, status:'DRAFT'}), ['done','wait','queued','queued','queued']);
// 2026-10-18 owner: price = cost + shipping + card fees with at least 30% margin; below 30% is a price error.
assert.deepEqual(state({grade:'RANK', single_usd:24.99, single_margin_pct:12, images:0,
  draft_reasons:['ingredients_missing','no_usable_product_images']}), ['done','bad','queued','queued','queued']);
assert.deepEqual(state({grade:'RANK', single_usd:24.99, single_margin_pct:31.2, images:0,
  draft_reasons:['ingredients_missing','no_usable_product_images']}), ['done','done','bad','queued','queued']);
assert.deepEqual(state({source:'owner_body_shower_category_fallback', single_usd:18.99,
  single_margin_pct:-5, draft_reasons:['inci_unresolved:1']}), ['done','bad','queued','queued','queued']);
assert.deepEqual(state({source:'owner_body_shower_category_fallback', single_usd:18.99,
  single_margin_pct:30, draft_reasons:['inci_unresolved:1']}), ['done','done','bad','queued','queued']);
assert.deepEqual(state({status:'ACTIVE', single_usd:20, single_margin_pct:10, images:2}),
  ['done','bad','queued','queued','queued']);
assert.deepEqual(state({status:'ACTIVE', single_usd:20, single_margin_pct:35, images:2}),
  ['done','done','done','done','done']);
console.log('Sequential pipeline display: 9 cases passed');
