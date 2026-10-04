#!/usr/bin/env python3
"""Build a deterministic, allowlisted public site. Never copy the repository/data tree."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = '/jarvis-luna/'
STATIC_FILES = ('index.html', '.nojekyll', 'hero-bg.jpg', 'images/jarvis.png', 'images/shopify.png') + tuple(
    f'images/teams/{name}.png' for name in ('secretary','sourcing','listing','channels','institutions','market','pricing','legal','robotics','design','knowledge','graph'))
# A schema is an object field projection, [schema] for arrays, or {'*': schema}
# for explicitly permitted data maps. True permits a sanitized primitive only.
def fields(names): return {k: True for k in names.split()}
def obj(names='', **nested): return dict(fields(names), **nested)
NUM_MAP = {'*': True}
MATCH = obj('channel global_product similarity demand_weight match_score', matched_tokens=[True])
PRODUCT = obj('pd_no name name_en bucket price_krw rating review_count url image_url shopify_score score grade s_rule us_market_hits us_median_price_usd recommend_reason reason downgrade_reason rank cost_krw landed_cost_usd breakeven_usd suggested_price_usd margin_pct shopify_action copy_status listing_ready public_ready', tags=[True], ad_keywords=[True], match=MATCH, matched_global=MATCH, best_global_match=MATCH)
TRAINING = fields('status training_effective verdict validation_macro_f1 baseline_accuracy baseline_macro_f1 training_performed weights_updated records real_records model_type experts accuracy validation_accuracy final_loss gate_load_std tuning_promoted tuning_steps updated_at tuning_validation_accuracy tuning_validation_macro_f1 training_accuracy_on_corpus tuning_final_loss tuning_gate_load_std')
TEAM = fields('id name when summary action action_kind waiting waiting_kind notice status phase phase_label color glyph badge')
CHANNEL_ROW = fields('product name title brand rank us_rank price price_usd url image_url views trend keyword search_volume count score rating review_count source channel daiso_bucket ingredients_text countries_tags hashtag category sub badge why')
CHANNEL_STATUS = fields('status reason collected_at trust count source note error_code last_attempt_at last_successful_fetch_at last_data_changed_at new_count updated_count using_cached_data')
RUN = fields('started_at finished_at requested ok parse_failed http_error status failure_reason candidates_new candidates_updated candidate_count operating_product_count collector_completed discovery_enabled operating_updates_enabled')
CANDIDATE = obj('pd_no name bucket url image_url collected_at comparison_status approval_required may_replace may_publish', comparison_blockers=[True], score=PRODUCT, comparable_product=fields('pd_no name score grade'), replacement_proposal=fields('candidate_pd_no replace_pd_no bucket score_delta status approval_required operating_count_delta may_execute'))
COMPARISON = obj('schema_version generated_at purpose candidate_count proposal_count operating_product_count approval_required may_publish may_replace_operating_products scoring_note', items=[CANDIDATE], market_evidence=[fields('channel collected_at count trust')])
PRICE_ROW = fields('pd_no name qty quantity unit_price_usd price_usd cost_usd product_cost_usd shipping_usd shipping_per_unit_usd shipping_unit_usd shipping_total_usd landed_cost_usd net_profit_usd margin_pct breakeven_usd duty_usd tariff_usd weight_g weight_source')
OFFER = fields('qty quantity price_usd unit_price_usd discount_pct net_profit_usd margin_pct orders_for_500 orders_for_500usd revenue_for_500 shipping_usd landed_cost_usd free_shipping')
BENCHMARK = fields('min p25 median max n source')
# Operations is nested in the existing runtime payload, never a new public file.
# Display scalars only: no raw goals, proof objects, identities or authority.
PUBLIC_TEXT = object()
PUBLIC_FALSE = object()
def public_fields(names): return {k: PUBLIC_TEXT for k in names.split()}
def public_obj(names='', **nested): return dict(public_fields(names), **nested)
OPERATIONS = public_obj('schema_version generated_at status organization',
 engines=[public_fields('id name status detail')],
 counts=public_fields('tasks_total local_verified external_verified handoffs_accepted watchers_ready watchers_blocked events approval_waiting'),
 tasks=[public_fields('task_id team kind level state')],
 watchers=[public_fields('team status reason captured_at')],
 business=public_obj('ready total exempt sales_allowed', blockers=[PUBLIC_TEXT]),
 feedback=public_fields('status verified_observations training_performed'),
 action_cards=[dict(public_fields('action_id kind level status reason member_count payload_hash target_configured before after'), may_approve=PUBLIC_FALSE, may_execute=PUBLIC_FALSE)])

SCHEMAS = {
 'data/dashboard_runtime.json': obj('schema_version generated_at last_synced truth_note data_integrity_note', pipeline_health=fields('status optional_failure_count required_failure_count at generated_at execution_id'), teams=[TEAM], secretary=TEAM, team_summary=fields('corpus_records pipeline_done pipeline_total'), pipeline=[fields('id title status detail')], sources=obj('status record_count updated_at',source_counts=NUM_MAP), graph=obj('notes links dangling_links dangling_personal dangling_personal_note dangling_warn_threshold records sources topics last_generated',audit=fields('untagged_pct')), training=TRAINING,cumulative=obj('since runs_recorded',totals=NUM_MAP,prior_totals=NUM_MAP,added_this_run=NUM_MAP,current_snapshot=NUM_MAP),global_channels={'*':[CHANNEL_ROW]},global_channels_status={'*':CHANNEL_STATUS},exchange_rate=fields('rate as_of source updated_at'),commit_summary=fields('line agents_line'),agents_ops=fields('risk task_count at'),candidate_discovery=COMPARISON,operations=OPERATIONS),
 'data/knowledge/training_status.json': dict(TRAINING,source_labels=NUM_MAP),
 'data/knowledge/real_sources.json': obj('updated collected_at',sources={'*':obj('count collected_at status',items=[fields('title url source published_at')])}),
 'data/daiso_real/collection_status.json': obj('',last_run=RUN,last_attempt=RUN,last_success=RUN,last_candidate_success=RUN,totals=obj('products avg_price_krw price_krw_min price_krw_max with_rating',by_bucket=NUM_MAP,categories=NUM_MAP),fx=fields('usd_to_krw krw_to_usd as_of source fetched_at ok')),
 'data/daiso_real/shopify_demand_score.json': obj('generated_at total_products s_slot_limit s_slot_open priority_note global_demand_signals products_with_global_match',grade_summary=NUM_MAP,category_avg_score=NUM_MAP,top_recommendations=[PRODUCT],all_scored=[PRODUCT]),
 'data/daiso_real/shopify_s_recommendations.json': obj('generated_at source canonical rule count priority_note agent_ready_count registerable_count',recommendations=[PRODUCT]),
 'data/pricing_model.json': obj('generated_at',exchange_rate=fields('usd_to_krw as_of source'),market_benchmark=BENCHMARK,scenarios={'*':[PRICE_ROW]},duty_scenarios={'*':[PRICE_ROW]},offers=obj('free_shipping_min_qty bundle_vs_single 판단_근거',single=OFFER,bundle=OFFER),duty_mode_note=fields('선택_필요 ddu ddp 주의 기본값')),
 'data/market_team.json': obj('data_integrity_note',team=fields('name scope status purpose updated_at'),target_market=obj('primary segment price_band_source',price_band_usd=BENCHMARK),health=obj('signals_live signals_total signals_verified trust_graded trust_note s_count listing_ready_count last_score_run last_pricing_run',exchange_rate=True),s_grade_priority=[PRODUCT],keyword_board=[obj('seed s_product_count intent intent_basis trend search_volume trend_unavailable_reason us_example_count source',us_market_examples=[CHANNEL_ROW])],competitor_watch=[CHANNEL_ROW],weekly_actions=[True]),
 'data/monthly_revenue.json': obj('source last_updated currency',months=[fields('month year label revenue_usd net_revenue_usd gross_revenue_usd orders source status')],last_month=fields('month year label revenue_usd net_revenue_usd gross_revenue_usd orders source status')),
 'data/agents/ops_plan.json': obj('agent generated_at risk task_count note',tasks=[fields('priority title detail approve')]),
 'data/agents/collector_audit.json': obj('agent generated_at products_total severity',last_run=RUN,suggestions=[True]),
 'data/agents/score_explain.json': obj('agent generated_at s_count rule severity',items=[obj('pd_no name score why global channel',tokens=[True])],gaps=[True]),
 'data/daiso_real/candidate_comparison.json': COMPARISON,
}
UNSAFE = re.compile(r'(?i)(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|(?:authorization|api[_-]?key|password|access[_-]?token)\s*[:=]\s*\S+|[A-Z]:\\(?:Users|Windows)\\|/home/runner/|(?:localhost|127\.0\.0\.1):\d+)')


def safe_scalar(value):
    if isinstance(value, str):
        if UNSAFE.search(value): return '[private value omitted]'
        if value.lstrip().lower().startswith(('http:', 'https:', 'file:', 'obsidian:', 'javascript:', 'data:')):
            u = urlsplit(value.strip())
            if u.scheme not in {'http','https'} or u.username or u.password or u.hostname in {'localhost','127.0.0.1','::1'}:
                return None
        # Allowed display fields can still embed private billing/model details.
        # Retain commerce counts, but omit backend evaluation tokens/cost/usage.
        value = re.sub(r'\s*·\s*(?:Jev|TypeSafe)\s*판정\s*\d+건(?:\([^)]*\))?', '', value)
        value = re.sub(r'\bdata/(?:manual|typesafe_call_log)/[^\s<>)]+', '[내부 원본 자료]', value)
        return value
    if value is None or isinstance(value, (bool,int,float)): return value
    return None


# Free-form public operation labels can still carry private values. Never retain
# contact information, backend model/billing details or private filesystem paths.
OPERATIONS_PRIVATE = re.compile(
    r'(?i)(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|'
    r'(?:\+\d{1,3}[ .-]?(?:\d[ .()-]?){7,14}\d|\b(?:0\d{1,2}|\d{3})[- .]\d{3,4}[- .]\d{4}\b)|'
    r'(?:/Users/|/home/|/var/|[A-Z]:[\\/]|\\\\)[^\s]+|'
    r'\b(?:billing|api[_ -]?key|authorization|password|access[_ -]?token|'
    r'identity|nonce|private[_ -]?path|backend|model[_ -]?(?:name|id))\b|'
    r'\b(?:sk-proj-|sk-|ghp_|github_pat_|Bearer\s+)\S+|'
    r'\b(?:gpt-[\w.-]+|claude-[\w.-]+|gemini-[\w.-]+|Jev|TypeSafe)\b|'
    r'\b\d{1,6}\s+[^,\n]{1,60}\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr)\b)')


def safe_operation_scalar(value):
    if isinstance(value, str) and re.search(r'(?i)\b(?:https?|file|data|javascript|obsidian):', value): return None
    value = safe_scalar(value)
    if isinstance(value, str):
        if OPERATIONS_PRIVATE.search(value): return '[private value omitted]'
        # No links or file targets are needed in this read-only summary.
        if urlsplit(value.strip()).scheme in {'http', 'https', 'file', 'data', 'javascript', 'obsidian'}: return None
        return value.replace('—', ' · ')
    return value


def project(value, schema):
    if schema is PUBLIC_FALSE: return False
    if schema is PUBLIC_TEXT: return safe_operation_scalar(value)
    if schema is True: return safe_scalar(value)
    if isinstance(schema, list): return [project(v,schema[0]) for v in value] if isinstance(value,list) else []
    if not isinstance(value,dict): return {}
    if '*' in schema: return {str(k):project(v,schema['*']) for k,v in sorted(value.items()) if safe_scalar(str(k))==str(k)}
    return {k:project(value[k],s) for k,s in schema.items() if k in value}


def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def checked_source(root, relative):
    p = root / relative
    for item in (p, *p.parents):
        if item == root.parent: break
        if item.is_symlink(): raise ValueError(f'public source symlink forbidden: {relative}')
    if not p.is_file() or not p.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'public source missing/outside root: {relative}')
    return p


def build(root, output, commit=None):
    root, output = Path(root).resolve(), Path(output).absolute()
    # Refuse destructive output paths. Only a separate child named dist is accepted.
    if output.name != 'dist' or output.parent not in {root, root.parent} or output == root or output.is_symlink():
        raise ValueError('output must be a separate, non-symlink dist directory')
    if commit is None:
        commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}',commit): raise ValueError('full commit SHA required')
    payload = {f:checked_source(root,f).read_bytes() for f in STATIC_FILES}
    for f,schema in SCHEMAS.items():
        payload[f] = encoded(project(json.loads(checked_source(root,f).read_text(encoding='utf-8')),schema))
    file_hashes = {f:digest(data) for f,data in sorted(payload.items())}
    site_hash = digest(encoded(file_hashes))
    deployment = {'schema_version':1,'commit':commit,'base_path':BASE_PATH,'site_hash':site_hash,'files':file_hashes,'public_files_only':True}
    payload['deployment.json'] = encoded(deployment)
    if output.exists(): shutil.rmtree(output)
    for name,data in payload.items():
        p=output/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
    return deployment


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--output',type=Path,default=ROOT/'dist');parser.add_argument('--commit')
    a=parser.parse_args();m=build(a.root,a.output,a.commit)
    print(f"PUBLIC_SITE_BUILT commit={m['commit']} files={len(m['files'])} site_hash={m['site_hash']}")
    return 0

if __name__=='__main__': raise SystemExit(main())
