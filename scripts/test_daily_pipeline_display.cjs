const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const first = scripts.find(script => script.includes('function formatProductSize('));
const formatter = first?.match(/function formatProductSize\([\s\S]*?\n}/)?.[0];
const navigation = first?.slice(first.indexOf('function syncNavigation(){'));
const pipeline = scripts.find(script => script.includes('async function renderDailyPipeline()'))
  ?.replace('\nrenderDailyPipeline();\nsetInterval(renderDailyPipeline,300000);', '');
const history = scripts.find(script => script.includes('shopify-daily-summary'));
const displayHelpers = history?.slice(0, history.indexOf('(async function(){'));
assert(formatter && navigation && pipeline && history, 'Expected dashboard scripts are present');

// Minimal DOM fixture checks the native-button contract;
// actual Enter/Space behavior requires separate browser QA.
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.className = '';
    this.style = {}; this.attrs = {}; this.events = {}; this._text = '';
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        const on = force === undefined ? !names.has(name) : force;
        if (on) names.add(name); else names.delete(name);
        this.className = [...names].join(' '); return on;
      },
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(value) { assert.equal(value, ''); this.textContent = ''; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertBefore(child, other) { child.parentNode = this; this.children.splice(this.children.indexOf(other), 0, child); }
  remove() { this.parentNode.children = this.parentNode.children.filter(child => child !== this); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
  querySelector(selector) {
    const name = selector.slice(1);
    return this.children.find(child => child.classList?.contains(name)) || null;
  }
  click() {
    const event = {target: this, stopped: false, stopPropagation() { this.stopped = true; }};
    for (let node = this; node && !event.stopped; node = node.parentNode) {
      for (const callback of node.events?.click || []) callback(event);
    }
  }
}
function context({hash = '', items = [], observations = [], recommendations = [], canonical = true} = {}) {
  const ids = {}, host = new Element('section');
  for (const id of ['dp-grid', 'dp-kpis', 'dp-when', 'shopify-daily-summary', 'shopify-daily-list']) {
    ids[id] = new Element('div'); host.appendChild(ids[id]);
  }
  const nav = ['#daily-pipeline', '#knowledge-graph', '#daiso', '#teams'].map(href => {
    const link = new Element('a'); link.setAttribute('href', href); return link;
  });
  const events = {}, window = {location: {hash}, addEventListener(name, callback) { (events[name] ||= []).push(callback); }};
  const document = {
    getElementById: id => ids[id], createElement: tag => new Element(tag),
    createTextNode: text => ({textContent: String(text)}),
    querySelectorAll: selector => { assert.equal(selector, 'nav a'); return nav; },
  };
  const data = {items}, observed = {items: observations}, sources = {canonical, recommendations};
  const ctx = vm.createContext({document, window, URL, console, setInterval() {},
    getJSON: async path => {
      if (ctx.fail) throw Error('network unavailable');
      if (path.includes('recommendations')) return sources;
      if (path.includes('observations')) return observed;
      return data;
    }});
  vm.runInContext(formatter, ctx);
  vm.runInContext(displayHelpers, ctx);
  return {ctx, ids, host, nav, window, events, data, observed, sources};
}
function state(card) { return card.querySelector('.dp-steps').children.map(step => step.className.replace('dp-step ', '')); }
function row(values) { return {pd_no: '1074979', category: 'makeup', date: '2026-10-19', title: 'Fixture product', status: 'DRAFT', ...values}; }

(async () => {
  const helpers = context().ctx;
  const missing = ['listing_gate_product_missing_or_ambiguous'];
  const fallback = row({draft_reasons: [...missing, 'ranking_fallback_draft_only']});
  const emptyCounts = helpers.canonicalCounts({canonical: true, recommendations: []});
  assert.match(helpers.registrationRouteText(fallback, emptyCounts), /승인 대체 DRAFT 이력/);
  assert.match(helpers.reasonText(missing, fallback, emptyCounts), /현재 정규 S 공개 게이트 대상 아님/);
  for (const pd_no of [undefined, null, '', ' ', {}, 'abc', 1074979]) {
    assert.match(helpers.reasonText(missing, {...fallback, pd_no}, emptyCounts), /미확인 또는 식별 모호/);
  }
  assert.match(helpers.reasonText(missing, fallback, null), /미확인 또는 식별 모호/);
  assert.match(helpers.reasonText(missing, row({}), emptyCounts), /미확인 또는 식별 모호/);
  const duplicateCounts = helpers.canonicalCounts({canonical: true, recommendations: [{pd_no:'1074979'}, {pd_no:'1074979'}]});
  assert.match(helpers.reasonText(missing, fallback, duplicateCounts), /상품번호 중복/);
  const singleCounts = helpers.canonicalCounts({canonical: true, recommendations: [{pd_no:'1074979'}]});
  assert.doesNotMatch(helpers.reasonText(missing, fallback, singleCounts), /대상 아님/);
  assert.match(helpers.registrationRouteText(row({}), singleCounts), /현재 정규 S 후보/);
  for (const pd_no of [1074979, ['1074979'], null, ' ']) {
    assert.doesNotMatch(helpers.registrationRouteText(row({pd_no}), singleCounts), /현재 정규 S 후보/);
  }
  for (const invalid of [null, {}, {canonical:false,recommendations:[]}, {canonical:true,recommendations:[{}]}]) {
    assert.equal(helpers.canonicalCounts(invalid), null);
  }
  assert.equal(helpers.draftRoute(row({draft_reasons:['owner_category_fallback_draft_only']})), '바디 카테고리 대체');
  assert.equal(helpers.draftRoute(row({grade:'RANK'})), '', 'A grade alone does not establish an approved fallback history');
  assert.match(html, /카피 선행조건: 제품별 제조사 안전자료가 미확인이면 AI 입력과 카피 생성도 보류/);
  assert.match(html, /정규 S 준비 현황과 승인된 대체 DRAFT 생성 이력은 별도 경로/);
  const f = context().ctx.formatProductSize;
  for (const size of [null, undefined, {}, [], '', {unit: 10}, {base: 'ml'},
    {unit: '10', base: 'ml'}, {unit: NaN, base: 'ml'}, {unit: Infinity, base: 'ml'},
    {unit: 0, base: 'ml'}, {unit: -1, base: 'g'}, {unit: 10, base: null},
    {unit: 10, base: ''}, {unit: 10, base: '  '}, {unit: 10, base: 'ml', count: 0},
    {unit: 10, base: 'ml', count: -1}, {unit: 10, base: 'ml', count: 1.5}]) {
    assert.equal(f(size), '용량 표기 없음');
    assert.equal(f(size, '표기 없음'), '표기 없음');
  }
  assert.equal(f({unit: 225, base: 'ml', count: 1}), '225ml');
  assert.equal(f({unit: 2, base: 'ml', count: 6}), '2ml x 6');
  assert.equal(f({unit: 0.5, base: ' g '}), '0.5g');

  // Initial deep link, ordinary hashes, browser Back/Forward hash changes, and bfcache.
  const navigationFixture = context({hash: '#teams'});
  const {ctx: navCtx, nav, window, events} = navigationFixture;
  vm.runInContext(navigation, navCtx);
  const active = () => nav.filter(a => a.classList.contains('active')).map(a => a.getAttribute('href'));
  assert.deepEqual(active(), ['#teams']);
  const changeHash = hash => { window.location.hash = hash; events.hashchange.forEach(fn => fn()); };
  changeHash('#daiso'); assert.deepEqual(active(), ['#daiso']);
  changeHash('#knowledge-graph'); assert.deepEqual(active(), ['#knowledge-graph']);
  changeHash('#daiso'); assert.deepEqual(active(), ['#daiso']); // Back
  changeHash('#knowledge-graph'); assert.deepEqual(active(), ['#knowledge-graph']); // Forward
  changeHash('#operations-system'); assert.deepEqual(active(), []);
  changeHash(''); assert.deepEqual(active(), ['#daily-pipeline']);
  changeHash('#top'); assert.deepEqual(active(), ['#daily-pipeline']);
  window.location.hash = '#teams'; events.pageshow.forEach(fn => fn());
  assert.deepEqual(active(), ['#teams']);
  for (const link of nav) assert.equal(link.getAttribute('aria-current'), link.classList.contains('active') ? 'location' : null);
  assert(!navigation.includes('scrollTo') && !navigation.includes('scrollIntoView'), 'Native anchor navigation is not overridden');

  // Keep sequencing fail-closed: ACTIVE and existing images are never legal evidence.
  const fixture = context();
  vm.runInContext(pipeline, fixture.ctx);
  const cases = [
    [{grade: '-', images: 11}, ['wait', 'queued', 'queued', 'queued', 'queued']],
    [{selection_recorded: true, images: 11}, ['done', 'wait', 'queued', 'queued', 'queued']],
    [{source: 'manual_owner_image_localization_example', images: 11}, ['done', 'wait', 'queued', 'queued', 'queued']],
    [{grade: 'S', images: 11}, ['done', 'wait', 'queued', 'queued', 'queued']],
    [{grade: 'RANK', single_usd: 24.99, single_margin_pct: 12, draft_reasons: ['ingredients_missing']}, ['done', 'bad', 'queued', 'queued', 'queued']],
    [{grade: 'RANK', single_usd: 24.99, single_margin_pct: 31.2, draft_reasons: ['ingredients_missing']}, ['done', 'done', 'bad', 'queued', 'queued']],
    [{source: 'owner_body_shower_category_fallback', single_usd: 18.99, single_margin_pct: -5, draft_reasons: ['inci_unresolved:1']}, ['done', 'bad', 'queued', 'queued', 'queued']],
    [{source: 'owner_body_shower_category_fallback', single_usd: 18.99, single_margin_pct: 30, draft_reasons: ['inci_unresolved:1']}, ['done', 'done', 'bad', 'queued', 'queued']],
    [{status: 'ACTIVE', single_usd: 20, single_margin_pct: 10, images: 2}, ['done', 'bad', 'queued', 'queued', 'queued']],
    [{status: 'ACTIVE', single_usd: 20, single_margin_pct: 35, images: 2}, ['done', 'done', 'wait', 'queued', 'queued']],
  ];
  for (const [values, expected] of cases) {
    fixture.data.items = [row(values)]; await fixture.ctx.renderDailyPipeline();
    assert.deepEqual(state(fixture.ids['dp-grid'].children[1]), expected);
  }
  const observation = {pd_no: '1074979', source: 'manual_connector_readback', observed_at: '2026-10-19T02:28:00Z', status: 'ACTIVE', media_count: 4, online_store_visible: true};
  for (const invalid of [{source: 'unverified'}, {observed_at: null}, {observed_at: 'invalid'},
    {status: 'UNKNOWN'}, {media_count: -1}, {media_count: 1.5}, {media_count: '4'},
    {online_store_visible: 'true'}, {pd_no: 'different-product'}]) {
    fixture.observed.items = [{...observation, ...invalid}];
    await fixture.ctx.renderDailyPipeline();
    assert.deepEqual(state(fixture.ids['dp-grid'].children[1]), ['done', 'done', 'wait', 'queued', 'queued']);
  }
  fixture.observed.items = [observation];
  await fixture.ctx.renderDailyPipeline();
  assert.deepEqual(state(fixture.ids['dp-grid'].children[1]), ['done', 'done', 'wait', 'done', 'done']);
  fixture.data.items[0].draft_reasons = ['ingredients_missing'];
  await fixture.ctx.renderDailyPipeline();
  assert.deepEqual(state(fixture.ids['dp-grid'].children[1]), ['done', 'done', 'bad', 'done', 'done']);
  assert(fixture.ids['dp-grid'].textContent.includes('자동 실시간 조회 아님'));
  assert(fixture.ids['dp-grid'].textContent.includes('고시·INCI·안전성 승인과 별개'));
  fixture.observed.items = [{...observation, media_count: 0, online_store_visible: false}];
  await fixture.ctx.renderDailyPipeline();
  assert.deepEqual(state(fixture.ids['dp-grid'].children[1]), ['done', 'done', 'bad', 'wait', 'wait']);

  // Exercise both capacity renderers against the published {} representation.
  fixture.data.items = [row({size: {}, single_usd: 16.64, single_margin_pct: 40})];
  await fixture.ctx.renderDailyPipeline();
  await vm.runInContext(history, fixture.ctx);
  assert(fixture.ids['shopify-daily-list'].textContent.includes('용량 표기 없음'));
  assert(fixture.ids['dp-grid'].textContent.includes('표기 없음'));
  assert(!/NaN|undefined/.test(fixture.ids['shopify-daily-list'].textContent + fixture.ids['dp-grid'].textContent));

  fixture.data.items = [fallback];
  await fixture.ctx.renderDailyPipeline();
  assert.match(fixture.ids['dp-grid'].textContent, /승인 대체 DRAFT 이력/);
  assert.match(fixture.ids['dp-grid'].textContent, /현재 정규 S 공개 게이트 대상 아님/);
  assert.match(fixture.ids['dp-grid'].textContent, /listing_gate_product_missing_or_ambiguous/, 'Original reason code is retained');
  await vm.runInContext(history, fixture.ctx);
  assert.match(fixture.ids['shopify-daily-list'].textContent, /현재 정규 S 공개 게이트 대상 아님/);
  fixture.sources.canonical = false;
  await fixture.ctx.renderDailyPipeline();
  assert.doesNotMatch(fixture.ids['dp-grid'].textContent, /현재 정규 S 공개 게이트 대상 아님/);
  fixture.sources.canonical = true;
  const card = fixture.ids['dp-grid'].children[1];
  const toggle = card.querySelector('.dp-toggle'), detail = card.querySelector('.dp-detail');
  assert.equal(toggle.tagName, 'BUTTON'); assert.equal(toggle.type, 'button');
  assert.equal(toggle.getAttribute('aria-controls'), detail.id);
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  for (let i = 0; i < 4; i++) {
    toggle.click();
    assert.equal(toggle.getAttribute('aria-expanded'), String(i % 2 === 0));
    assert.equal(card.classList.contains('open'), i % 2 === 0);
  }
  card.click(); assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  const sourceLink = card.querySelector('.dp-links').children[0];
  sourceLink.click(); assert.equal(toggle.getAttribute('aria-expanded'), 'true', 'Product links do not toggle the card');
  await fixture.ctx.renderDailyPipeline();
  assert.equal(fixture.ids['dp-grid'].children.length, 3);
  assert.equal(fixture.ids['dp-kpis'].children.length, 4);
  assert.equal(fixture.host.children.filter(e => e.className === 'dp-legend').length, 1);
  fixture.ctx.fail = true; await fixture.ctx.renderDailyPipeline();
  assert.equal(fixture.ids['dp-grid'].children.length, 0);
  assert.equal(fixture.ids['dp-kpis'].children.length, 0);
  assert.equal(fixture.host.children.filter(e => e.className === 'dp-legend').length, 0);
  fixture.ctx.fail = false; await fixture.ctx.renderDailyPipeline();
  assert.equal(fixture.ids['dp-grid'].children.length, 3);
  console.log('Dashboard display: size, URL history, native-button contract, 10 fail-closed pipeline cases, readback validation, repeated toggles and error recovery passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
