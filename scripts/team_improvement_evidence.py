"""Offline public-safe evidence projection. No writes, providers, replay or authority.

build(root, *, now=None, reviewed_sha256=None, max_age_days=14) returns a JSON
serializable dict. reviewed_sha256 is a TRUSTED caller-supplied review manifest,
not an input-file claim. Defaults pin strong pilot claims to the inspected
publication. Fresh schema-valid diagnostics remain usable after refresh with a
recomputed hash, without gaining pilot authority. Unknown paths are rejected.
Metadata generation/run clocks are not source capture or independent evaluation.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

TEAM_IDS = ('sourcing', 'institutions', 'market', 'listing', 'pricing', 'legal',
            'robotics', 'design', 'channels', 'knowledge', 'graph')
PHASES = ('monitoring', 'proposal', 'shadow_evaluated', 'applied', 'verified_gain', 'blocked')
DIAGNOSTIC = 'data/team_improvement.json'
STATUS = 'data/self_improve/status.json'
SOURCING = 'data/self_improve/sourcing_policy.json'
DESIGN = 'data/self_improve/design_policy.json'
BOARD = 'data/design_team.json'
TOPICS = 'data/self_improve/topic_keywords.json'
REVIEWED_SHA256 = {
    DIAGNOSTIC: '209d842b71cbfa3861802f4be391cfc74c4ed1f23bd9fe4331c429492ccf0c8c',
    STATUS: 'f4f7cd75797577e0eab14b58e8e80e890b638f8ac091ae6f89c029000db397c5',
    SOURCING: '510de1f08fa1721177bf22f34cb4fe96fdb2c1e8f8897f6eecc23c6b198d1777',
    DESIGN: '8a97d9f231a23d510d336d5c4267a5d7d253a99e496618483a216e3761debdbb',
    BOARD: 'f17aba279320f87fdf934da00084fee2f1539b1cb1ba708b2baf8df2a85d8b73',
    TOPICS: 'd1b17f320433c9fe0733c8871ad6e18259e5fda2d7d5a4e77f032ed2e139c330',
}
MAX_SOURCE_BYTES = 512_000
MAX_OUTPUT_BYTES = 40_000
METRICS = {tid: ('comparable_feedback_observations', 'observations', 'increase') for tid in TEAM_IDS}
METRICS.update(graph=('uncategorized_records', 'records', 'decrease'),
               sourcing=('useful_fetch_count', 'fetches', 'increase'),
               design=('relevant_reference_count', 'references', 'increase'))


def _clock(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('invalid_clock')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid_clock') from None
    if stamp.tzinfo is None:
        raise ValueError('invalid_clock')
    return stamp.astimezone(timezone.utc)


def _iso(value):
    return _clock(value).isoformat()


def _count(value):
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError('invalid_count')
    return value


def _ratio(value, n, d):
    if type(value) not in (int, float) or not math.isfinite(value) or d <= 0:
        raise ValueError('invalid_ratio')
    if abs(value - n / d) > 0.001:
        raise ValueError('inconsistent_ratio')


def _unique(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = val
    return result


def build(root, *, now=None, reviewed_sha256=None, max_age_days=14):
    """Read at most six fixed files; return 11 teams and compact summary.

    Missing capture clocks remain null. Freshness uses declared generation,
    policy-update, or run-start metadata only, never filesystem modification time.
    Historical observations may be retained with fresh=false and blocked status.
    No adapter here can assert verified_gain or confer mutation/business authority.
    """
    end = datetime.now(timezone.utc) if now is None else _clock(now)
    if type(max_age_days) is not int or not 1 <= max_age_days <= 14:
        raise ValueError('max_age_days must be between 1 and 14')
    explicit_manifest = reviewed_sha256 is not None
    manifest = dict(REVIEWED_SHA256 if reviewed_sha256 is None else reviewed_sha256)
    if set(manifest) - set(REVIEWED_SHA256):
        raise ValueError('unknown_source_path')
    for digest in manifest.values():
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid_review_digest')
    base = Path(root).resolve()
    docs, evidence, errors = {}, {}, {}
    for rel in REVIEWED_SHA256:
        try:
            if rel not in manifest:
                raise ValueError('unreviewed_source')
            target = base / rel
            # Reject symlinks/junctions in any component, even within the root.
            current = base
            for part in Path(rel).parts:
                current = current / part
                if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                    raise ValueError('linked_source')
            if not target.resolve().is_relative_to(base):
                raise ValueError('outside_root')
            with target.open('rb') as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                raise ValueError('source_too_large')
            digest = hashlib.sha256(raw).hexdigest()
            reviewed = digest == manifest[rel]
            if not reviewed and explicit_manifest:
                raise ValueError('source_hash_mismatch')
            doc = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))
            if not isinstance(doc, dict):
                raise ValueError('invalid_document')
            clock_field = ('adopted_at' if rel == SOURCING else
                           'updated_at' if rel in (DESIGN, TOPICS) else 'generated_at')
            stamp = _clock(doc.get(clock_field))
            if stamp > end:
                raise ValueError('future_source_clock')
            captured = doc.get('captured_at')
            if captured is not None:
                captured = _iso(captured)
                if _clock(captured) > end:
                    raise ValueError('future_capture_clock')
            evaluated = doc.get('evaluated_at')
            if evaluated is not None:
                evaluated = _iso(evaluated)
                if _clock(evaluated) > end:
                    raise ValueError('future_evaluation_clock')
            evidence[rel] = {
                'path': rel, 'sha256': digest, 'reviewed_exact_bytes': reviewed, 'captured_at': captured,
                'generated_at': stamp.isoformat() if clock_field == 'generated_at' else None,
                'policy_updated_at': stamp.isoformat() if clock_field == 'updated_at' else None,
                'applied_at': stamp.isoformat() if clock_field == 'adopted_at' else None,
                'evaluated_at': evaluated, 'metadata_clock_field': clock_field,
                'metadata_clock_at': stamp.isoformat(),
                'fresh': end - stamp <= timedelta(days=max_age_days),
                'capture_clock_verified': captured is not None,
            }
            docs[rel] = doc
        except (OSError, UnicodeError, ValueError, RecursionError):
            # Fixed public-safe reason only. Never exception text or source values.
            errors[rel] = 'source_missing_invalid_or_unreviewed'
    teams = {}
    for tid in TEAM_IDS:
        key, unit, direction = METRICS[tid]
        teams[tid] = {
            'id': tid, 'phase': 'proposal', 'status': 'awaiting_comparable_feedback',
            'metric': {'id': key, 'unit': unit, 'direction': direction, 'business_metric': False},
            'baseline': None, 'current': None, 'shadow': None, 'evidence': [],
            'evidence_strength': 'none',
            'proposal': {'goal': 'Collect comparable internal feedback before considering a bounded pilot.',
                         'scope': 'internal_measurement_only', 'business_draft': False},
            'blockers': ['no_comparable_before_after_feedback'],
            'autonomous_change_allowed': False, 'autonomous_change_scope': [],
            'authority': False, 'business_clearance': False, 'verified_gain': False,
        }

    def sources(tid, paths):
        team = teams[tid]
        team['evidence'] = [dict(evidence[p]) for p in paths if p in evidence]
        failed = [p for p in paths if p not in docs or
                  (p != DIAGNOSTIC and not evidence[p]['reviewed_exact_bytes'])]
        if failed or any(not evidence[p]['fresh'] for p in paths if p in evidence):
            team.update(phase='blocked', status='evidence_unavailable_or_stale')
            team['blockers'] = ['required_evidence_unavailable_or_stale']
        # Reviewed historical pilots can be shown only as historical below.
        return not failed

    def reject(tid):
        teams[tid].update(phase='blocked', status='unsupported_or_malformed_evidence',
                          baseline=None, current=None, shadow=None, evidence_strength='none',
                          autonomous_change_allowed=False, autonomous_change_scope=[],
                          blockers=['unsupported_or_malformed_evidence'])

    def point(n, d, rel, clock_field, clock_value):
        when = _clock(clock_value)
        if when > end:
            raise ValueError('future_observation')
        return {'value': _count(n), 'denominator': _count(d), 'source_path': rel,
                'source_sha256': evidence[rel]['sha256'], 'clock_field': clock_field,
                'clock_at': when.isoformat(), 'captured_at': evidence[rel]['captured_at'],
                'evaluated_at': evidence[rel]['evaluated_at'],
                'fresh': end - when <= timedelta(days=max_age_days)}

    diagnostic = {'meaning': 'action_text_monitoring_only', 'clear': None, 'stuck': None,
                  'reported_action_changes': None, 'source': None,
                  'not_performance_evidence': True}
    diagnostic_ok = False
    try:
        d = docs[DIAGNOSTIC]
        cards = d['teams']
        if not isinstance(cards, dict) or set(cards) != set(TEAM_IDS):
            raise ValueError('unknown_or_missing_team')
        summary = d['summary']
        if _count(summary['teams']) != 11:
            raise ValueError('coverage')
        for tid, card in cards.items():
            if not isinstance(card, dict) or card.get('state') not in ('양호', '개선', '일부개선', '정체', '후퇴'):
                raise ValueError('invalid_diagnostic')
            if card.get('open_kind') not in ('', 'auto_remediable', 'revalidate_only', 'human_approval_required', 'external_dependency'):
                raise ValueError('invalid_diagnostic')
        if (_count(summary['양호']) != sum(c['state'] == '양호' for c in cards.values()) or
            _count(summary['정체']) != sum(c['state'] == '정체' for c in cards.values()) or
            _count(summary['개선']) != sum(c['state'] in ('개선', '일부개선') for c in cards.values())):
            raise ValueError('inconsistent_diagnostic_counts')
        diagnostic.update(clear=_count(summary['양호']), stuck=_count(summary['정체']),
                          reported_action_changes=_count(summary['개선']), source=dict(evidence[DIAGNOSTIC]))
        diagnostic_ok = evidence[DIAGNOSTIC]['fresh']
        for tid, card in cards.items():
            sources(tid, [DIAGNOSTIC])
            if not diagnostic_ok:
                continue
            if card.get('state') == '양호':
                teams[tid].update(phase='monitoring', status='no_open_diagnostic_action')
            elif card.get('open_kind') in ('human_approval_required', 'external_dependency'):
                teams[tid].update(phase='blocked', status='comparable_feedback_or_dependency_pending')
                teams[tid]['blockers'].append('approval_or_external_dependency')
    except (KeyError, TypeError, ValueError):
        for tid in TEAM_IDS:
            reject(tid)
        diagnostic_ok = False

    if diagnostic_ok:
        if sources('graph', [DIAGNOSTIC, STATUS, TOPICS]):
            try:
                loop = docs[STATUS]['loops']['topics']
                ev = loop['evaluation']
                if loop['metric'] != 'uncategorized_rate' or ev['mode'] != 'production_classifier_replay':
                    raise ValueError('unsupported_metric')
                n = _count(loop['records'])
                before, after = _count(loop['uncategorized_before']), _count(loop['uncategorized_after_shadow'])
                if not 0 <= after <= before <= n or ev['evaluated_records'] != n:
                    raise ValueError('invalid_comparison')
                _ratio(loop['before'], before, n)
                _ratio(loop['after_shadow'], after, n)
                if docs[TOPICS].get('generator') != 'scripts/self_improve.py':
                    raise ValueError('unrelated_policy')
                team = teams['graph']
                team.update(phase='shadow_evaluated', status='rule_imitation_shadow_only',
                            baseline=point(before, n, STATUS, 'generated_at', docs[STATUS]['generated_at']),
                            shadow=point(after, n, STATUS, 'generated_at', docs[STATUS]['generated_at']),
                            evidence_strength='same_input_classifier_shadow_not_business_performance',
                            blockers=['no_independent_labels_or_business_outcomes', 'no_verified_gain'])
                team['evaluation_validation'] = 'reviewed_report_only_not_independently_reconstructed'
                team['source_input_digests_verified'] = False
                # This projector does not grant further topic changes from replay metadata.
            except (KeyError, TypeError, ValueError):
                reject('graph')
        if sources('sourcing', [DIAGNOSTIC, SOURCING]):
            try:
                policy = docs[SOURCING]
                if policy.get('generator') != 'scripts/self_improve.py' or policy.get('enabled') is not True:
                    raise ValueError('unrelated_policy')
                if policy.get('skip_full_expected_bucket') is not True or policy.get('open_buckets_first') is not True:
                    raise ValueError('unsupported_config')
                baseline, obs = policy['baseline'], policy['observations']
                if not isinstance(obs, list) or len(obs) != 1:
                    raise ValueError('unreviewed_observation_set')
                latest = obs[0]
                for row in (baseline, latest):
                    if _count(row['ok']) > _count(row['requested']):
                        raise ValueError('invalid_count')
                    _ratio(row['useful_rate'], row['ok'], row['requested'])
                if _clock(latest['started_at']) <= _clock(policy['adopted_at']):
                    raise ValueError('invalid_order')
                team = teams['sourcing']
                team.update(phase='applied', status='single_post_application_observation',
                            baseline=point(baseline['ok'], baseline['requested'], SOURCING, 'baseline.started_at', baseline['started_at']),
                            current=point(latest['ok'], latest['requested'], SOURCING, 'observations[0].started_at', latest['started_at']),
                            evidence_strength='single_observation_not_sustained_causal_proof',
                            blockers=['single_observation', 'no_sustained_causal_proof', 'no_verified_gain'])
                if not team['current']['fresh']:
                    team.update(phase='blocked', status='historical_pilot_not_current')
                    team['blockers'].append('stale_observation')
                # Historical configuration is verified, but no new mutation is authorized.
                team['existing_bounded_configuration'] = {'verified': True,
                    'scope': ['skip_full_expected_bucket', 'open_buckets_first'], 'new_changes_allowed': False}
            except (KeyError, TypeError, ValueError):
                reject('sourcing')
        if sources('design', [DIAGNOSTIC, DESIGN, BOARD]):
            try:
                config, board = docs[DESIGN], docs[BOARD]
                quality, applied = board['references']['quality'], board['references']['policy']
                if config.get('generator') != 'scripts/self_improve.py' or config.get('enabled') is not True:
                    raise ValueError('unrelated_policy')
                if config.get('feed_caps') != {'web.dev': 3} or applied.get('feed_caps') != config['feed_caps']:
                    raise ValueError('unsupported_config')
                if applied.get('applied') is not True or applied.get('policy_version') != config.get('version'):
                    raise ValueError('not_applied')
                n, rel = _count(quality['items']), _count(quality['relevant'])
                if rel > n:
                    raise ValueError('invalid_count')
                _ratio(quality['relevant_ratio'], rel, n)
                team = teams['design']
                team.update(phase='applied', status='reference_cap_applied_no_comparable_baseline',
                            current=point(rel, n, BOARD, 'generated_at', board['generated_at']),
                            evidence_strength='configuration_application_not_performance_gain',
                            blockers=['no_comparable_before_after', 'external_dependency', 'no_verified_gain'])
                team['existing_bounded_configuration'] = {'verified': True,
                    'scope': ['web.dev_reference_cap_3'], 'dropped_references': _count(applied['dropped']),
                    'new_changes_allowed': False}
            except (KeyError, TypeError, ValueError):
                reject('design')
    for tid in ('graph', 'sourcing', 'design'):
        team = teams[tid]
        if team['phase'] in ('shadow_evaluated', 'applied') and any(not e['fresh'] for e in team['evidence']):
            team.update(phase='blocked', status='historical_pilot_not_current')
            team['blockers'].append('stale_pilot_evidence')
        team['historical_observation_only'] = team['status'] == 'historical_pilot_not_current'
    counts = {phase: sum(t['phase'] == phase for t in teams.values()) for phase in PHASES}
    out = {'schema_version': 1, 'generated_at': end.isoformat(), 'mode': 'offline_read_only_projection',
           'source_allowlist': list(REVIEWED_SHA256), 'teams': teams, 'diagnostic_monitoring': diagnostic,
           'source_errors': [{'path': p, 'reason': e} for p, e in sorted(errors.items())],
           'summary': {'teams': 11, 'phase_counts': counts, 'verified_gains': 0,
                       'authority': False, 'business_clearance': False,
                       'label': f"11 teams: {counts['monitoring']} monitoring, {counts['proposal']} proposal, "
                                f"{counts['shadow_evaluated']} shadow, {counts['applied']} applied, "
                                f"0 verified gains, {counts['blocked']} blocked."},
           'limitations': ['Pilot figures are reviewed local reports, not independently reconstructed experiments.',
                           'Action disappearance is not measured gain.',
                           'Generation and run-start metadata are not capture or independent evaluation clocks.',
                           'No revenue, conversion, legal clearance, or business performance is inferred.']}
    if len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > MAX_OUTPUT_BYTES:
        raise ValueError('projection_too_large')
    return out
