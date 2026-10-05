"""Offline fixed-procedure state, never a dispatcher or receipt verifier.

Contract: SourceProcedureStore(directory, config) uses a separate local state/lock.
Trusted caller may fresh_init(trusted_caller=True) ONLY on a provably fresh install.
Otherwise load(expected=checkpoint) is mandatory. Parent must durably retain each
checkpoint alongside its runner checkpoint; missing checkpoints must not reset.
plan/claim accept exact source_recovery fields (source_team, failure_fingerprint,
fixedprocedure_id) and stable invocation_id. claim durably commits before dispatch.
finish requires actual output bytes and trusted validator for source-health proof.
load marks interrupted claims reconciliation_required. reconcile never replays or
refunds budgets. Stale locks never expire or get deleted. Receipt verification is
separate. Fixed config is IDs only; no commands, URLs, modules or task parameters.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TEAMS = ('sourcing', 'institutions', 'market', 'listing', 'pricing', 'legal',
         'robotics', 'design', 'channels', 'knowledge', 'graph')
FIXED_IDS = frozenset(('daiso_shortlist_observe', 'dashboard_revalidate',
 'design_source_observe', 'robotics_source_observe', 'channel_candidate_probe',
 'institution_source_observe', 'knowledge_source_reconcile'))
DEFAULT_CONFIG = {
 'sourcing': ('daiso_shortlist_observe',), 'pricing': ('daiso_shortlist_observe',),
 'institutions': ('institution_source_observe',), 'robotics': ('robotics_source_observe',),
 'design': ('design_source_observe',), 'channels': ('channel_candidate_probe',),
 'knowledge': ('knowledge_source_reconcile',),
 **{t: ('dashboard_revalidate',) for t in ('market', 'listing', 'legal', 'graph')}}
MIN_COOLDOWN_SECONDS = 7200
MAX_EPISODES = 128
MAX_EPISODE_ATTEMPTS = 2
_HASH = re.compile(r'^[0-9a-f]{64}$')
_TOKEN = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')


def canonical(value):
    def check(v):
        if isinstance(v, dict):
            if any(not isinstance(k, str) for k in v): raise ValueError('invalid JSON key')
            for x in v.values(): check(x)
        elif isinstance(v, (list, tuple)):
            for x in v: check(x)
        elif not (v is None or type(v) in (str, bool, int, float)): raise ValueError('not JSON')
        if isinstance(v, float) and not math.isfinite(v): raise ValueError('nonfinite JSON')
    check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _hash(value):
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def failure_fingerprint(failure):
    """Strict stable actual source facts. generated_at/observed_at are forbidden."""
    if not isinstance(failure, dict) or set(failure) != {'source_identity', 'source_hash', 'blocker_codes'}:
        raise ValueError('strict stable failure fields required')
    if not isinstance(failure['source_identity'], str) or not failure['source_identity'] or len(failure['source_identity']) > 256: raise ValueError('source identity required')
    if failure['source_hash'] is not None and not _hash(failure['source_hash']): raise ValueError('invalid source hash')
    codes = failure['blocker_codes']
    if not isinstance(codes, list) or not codes or len(codes) > 64 or any(not isinstance(c, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', c) for c in codes): raise ValueError('invalid blocker codes')
    return digest({**failure, 'blocker_codes': sorted(set(codes))})


def _time(value=None):
    dt = datetime.now(timezone.utc) if value is None else value
    if isinstance(dt, str): dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    if not isinstance(dt, datetime) or dt.tzinfo is None: raise ValueError('aware time required')
    return dt.astimezone(timezone.utc)


def _seal(table):
    table['table_hash'] = digest({k:v for k,v in table.items() if k != 'table_hash'})


class SourceProcedureStore:
    """Caller-owned local directory; no ExecutionStore or source-data writes.

    force is accepted but cannot bypass any limit. Config may only reduce fixed
    owned IDs. Trusted validators are caller code, never task-provided flags.
    """
    filename = 'source-procedure-state.json'
    lockname = 'source-procedure-state.lock'

    def __init__(self, directory, config=None):
        self.directory = Path(directory).absolute()
        self.config = copy.deepcopy(DEFAULT_CONFIG if config is None else config)
        if not isinstance(self.config, dict) or set(self.config) != set(TEAMS): raise ValueError('exact 11 teams required')
        for team, ids in self.config.items():
            if not isinstance(ids, (list, tuple)) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or any(i not in DEFAULT_CONFIG[team] for i in ids): raise ValueError('fixed owned IDs only')
            self.config[team] = list(ids)
        self.config_hash = digest(self.config)
        self._expected = None

    def _path(self, name):
        for p in (self.directory, *self.directory.parents, self.directory / name):
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()): raise ValueError('redirected state path')
        return self.directory / name

    @contextmanager
    def _lock(self):
        self._path(self.lockname); self.directory.mkdir(parents=True, exist_ok=True)
        lock = self._path(self.lockname); token = os.urandom(32).hex().encode()
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        identity = os.fstat(fd)
        def owned():
            try:
                stat = lock.stat()
                if (stat.st_dev, stat.st_ino) != (identity.st_dev, identity.st_ino) or lock.read_bytes() != token: raise ValueError('lock lost')
            except OSError as exc: raise ValueError('lock lost') from exc
        try:
            os.write(fd, token); os.fsync(fd)
            yield owned
        finally:
            os.close(fd)
            owned()  # Do not delete a replacement lock, even on error.
            lock.unlink()

    def _write(self, table, owned):
        owned(); _seal(table); self._validate(table)
        dest = self._path(self.filename)
        fd, name = tempfile.mkstemp(prefix='.source-procedure-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write((canonical(table) + '\n').encode()); stream.flush(); os.fsync(stream.fileno())
            owned(); self._path(self.filename); os.replace(name, dest)
            if os.name != 'nt':
                d = os.open(self.directory, os.O_RDONLY)
                try: os.fsync(d)
                finally: os.close(d)
        finally:
            if os.path.exists(name): os.unlink(name)
        self._expected = self._checkpoint(table)

    def _checkpoint(self, table):
        return {'revision':table['revision'], 'table_hash':table['table_hash'], 'lifetime':{t:table['teams'][t]['lifetime'] for t in TEAMS}}

    def checkpoint(self):
        if self._expected is None: raise ValueError('continuity not loaded')
        return copy.deepcopy(self._expected)

    def _read(self, expected=None):
        expected = self._expected if expected is None else expected
        if not isinstance(expected, dict) or set(expected) != {'revision','table_hash','lifetime'}: raise ValueError('trusted continuity checkpoint required')
        try: table = json.loads(self._path(self.filename).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc: raise ValueError('expected state missing/malformed') from exc
        try: self._validate(table)
        except (KeyError, TypeError, AttributeError, OverflowError) as exc: raise ValueError('malformed table') from exc
        if self._checkpoint(table) != expected: raise ValueError('checkpoint hash/regression mismatch')
        return table

    def _validate(self, table):
        if not isinstance(table, dict) or set(table) != {'schema_version','revision','config_hash','teams','table_hash'}: raise ValueError('malformed table')
        if type(table['schema_version']) is not int or table['schema_version'] != 1 or type(table['revision']) is not int or table['revision'] < 0: raise ValueError('invalid counter')
        if table['config_hash'] != self.config_hash or not _hash(table['table_hash']) or table['table_hash'] != digest({k:v for k,v in table.items() if k != 'table_hash'}): raise ValueError('table/config hash mismatch')
        if not isinstance(table['teams'], dict) or set(table['teams']) != set(TEAMS): raise ValueError('invalid teams')
        total = 0
        for team, row in table['teams'].items():
            if not isinstance(row, dict) or set(row) != {'lifetime','budget','stopped','episodes','last_claimed_at'}: raise ValueError('invalid team state')
            if type(row['lifetime']) is not int or type(row['budget']) is not int or not 0 <= row['lifetime'] <= row['budget'] <= 256 or type(row['stopped']) is not bool: raise ValueError('invalid lifetime')
            if not isinstance(row['episodes'], list) or len(row['episodes']) > MAX_EPISODES: raise ValueError('history overflow')
            attempts = []; prev = None
            for number, episode in enumerate(row['episodes'], 1):
                if not isinstance(episode, dict) or set(episode) != {'episode','failure_fingerprint','attempts'} or type(episode['episode']) is not int or episode['episode'] != number or not _hash(episode['failure_fingerprint']): raise ValueError('invalid episode')
                if episode['failure_fingerprint'] == prev: raise ValueError('unchanged failure reset')
                prev = episode['failure_fingerprint']
                if not isinstance(episode['attempts'], list) or not 1 <= len(episode['attempts']) <= MAX_EPISODE_ATTEMPTS: raise ValueError('invalid episode budget')
                for a in episode['attempts']:
                    if not isinstance(a, dict) or set(a) != {'claim_id','key','fixedprocedure_id','invocation_id','claimed_at','status','ended_at','outcome'} or a['fixedprocedure_id'] not in self.config[team]: raise ValueError('invalid attempt')
                    binding = {'source_team':team,'failure_fingerprint':prev,'fixedprocedure_id':a['fixedprocedure_id']}
                    if not isinstance(a['invocation_id'], str) or not _TOKEN.fullmatch(a['invocation_id']) or a['key'] != digest(binding) or a['claim_id'] != digest({'key':a['key'],'sequence':len(attempts)+1,'invocation_id':a['invocation_id']}): raise ValueError('invalid claim binding')
                    stamp = _time(a['claimed_at'])
                    if attempts and (stamp - _time(attempts[-1]['claimed_at'])).total_seconds() < MIN_COOLDOWN_SECONDS: raise ValueError('cooldown regression')
                    if any(p['invocation_id'] == a['invocation_id'] for p in attempts): raise ValueError('invocation ceiling')
                    if a['status'] not in ('CLAIMED','reconciliation_required','FINISHED','RECONCILED'): raise ValueError('invalid status')
                    if a['status'] in ('CLAIMED','reconciliation_required'):
                        if a['ended_at'] is not None or a['outcome'] is not None: raise ValueError('unfinished outcome')
                    else:
                        if _time(a['ended_at']) < stamp: raise ValueError('outcome clock regression')
                        self._validate_outcome(a['outcome'])
                        proof = a['outcome']['source_proof']
                        if proof and (proof['source_team'] != team or not stamp <= _time(proof['observed_at']) <= _time(a['ended_at'])): raise ValueError('proof binding mismatch')
                    attempts.append(a)
            if row['lifetime'] != len(attempts) or row['last_claimed_at'] != (attempts[-1]['claimed_at'] if attempts else None): raise ValueError('lifetime/history regression')
            if sum(a['status'] in ('CLAIMED','reconciliation_required') for a in attempts) > 1: raise ValueError('pending ceiling')
            total += row['lifetime']
        if table['revision'] < total: raise ValueError('counter regression')

    @staticmethod
    def _validate_outcome(o):
        if not isinstance(o, dict) or set(o) != {'exit_code','output_sha256','source_proof','actual_source_validated','source_healthy','receipt_verified','authority'}: raise ValueError('strict outcome required')
        if o['exit_code'] is not None and type(o['exit_code']) is not int: raise ValueError('invalid exit code')
        if o['output_sha256'] is not None and not _hash(o['output_sha256']): raise ValueError('invalid output hash')
        if type(o['actual_source_validated']) is not bool or type(o['source_healthy']) is not bool or o['receipt_verified'] is not False or o['authority'] is not False: raise ValueError('invalid authority')
        if o['source_healthy'] != (o['exit_code'] == 0 and o['actual_source_validated'] and _hash(o['output_sha256'])): raise ValueError('unproved health')
        if o['actual_source_validated']: SourceProcedureStore._proof(o['source_proof'])
        elif o['source_proof'] is not None: raise ValueError('unvalidated proof')

    @staticmethod
    def _proof(proof):
        fields = {'source_team','source_hash','captured_at','observed_at','observation_kind','required_scope_complete'}
        if not isinstance(proof, dict) or set(proof) != fields or proof['source_team'] not in TEAMS or not _hash(proof['source_hash']) or proof['required_scope_complete'] is not True: raise ValueError('actual source proof required')
        observed = _time(proof['observed_at'])
        if proof['observation_kind'] == 'local_derived_read':
            if proof['captured_at'] is not None and _time(proof['captured_at']) > observed: raise ValueError('future capture')
        elif proof['observation_kind'] == 'actual_source_capture':
            if proof['captured_at'] is None or _time(proof['captured_at']) > observed: raise ValueError('actual capture required')
        else: raise ValueError('unknown observation kind')

    def fresh_init(self, *, trusted_caller=False, lifetime_budget=256):
        if trusted_caller is not True or type(lifetime_budget) is not int or not 0 <= lifetime_budget <= 256: raise ValueError('trusted fresh initialization required')
        with self._lock() as owned:
            if self._path(self.filename).exists() or self._expected is not None: raise ValueError('existing state cannot reset')
            table = {'schema_version':1,'revision':0,'config_hash':self.config_hash,'teams':{t:{'lifetime':0,'budget':lifetime_budget,'stopped':False,'episodes':[],'last_claimed_at':None} for t in TEAMS}}
            self._write(table, owned)
        return self.checkpoint()

    def load(self, *, expected):
        with self._lock() as owned:
            table = self._read(expected); changed = False
            for row in table['teams'].values():
                for e in row['episodes']:
                    for a in e['attempts']:
                        if a['status'] == 'CLAIMED': a['status'] = 'reconciliation_required'; changed = True
            if changed:
                table['revision'] += 1; self._write(table, owned)
            else: self._expected = self._checkpoint(table)
        return self.public_projection()

    def _binding(self, binding, invocation_id):
        if not isinstance(binding, dict) or set(binding) != {'source_team','failure_fingerprint','fixedprocedure_id'}: raise ValueError('strict source_recovery fields required')
        team = binding['source_team']; procedure = binding['fixedprocedure_id']
        if not isinstance(team, str) or team not in TEAMS or not isinstance(procedure, str) or procedure not in self.config[team] or not _hash(binding['failure_fingerprint']): raise ValueError('fixed binding required')
        if not isinstance(invocation_id, str) or not _TOKEN.fullmatch(invocation_id): raise ValueError('stable invocation ID required')
        return team

    def _plan(self, table, binding, invocation_id, now):
        team = self._binding(binding, invocation_id); row = table['teams'][team]
        history = row['episodes']; episode = history[-1] if history and history[-1]['failure_fingerprint'] == binding['failure_fingerprint'] else None
        attempts = [a for e in history for a in e['attempts']]; reasons = []
        if row['stopped']: reasons.append('lifetime_stop')
        if row['lifetime'] >= row['budget']: reasons.append('lifetime_budget')
        if any(a['status'] in ('CLAIMED','reconciliation_required') for a in attempts): reasons.append('reconciliation_required')
        if any(a['invocation_id'] == invocation_id for a in attempts): reasons.append('invocation_limit')
        if episode and len(episode['attempts']) >= MAX_EPISODE_ATTEMPTS: reasons.append('episode_limit')
        if episode is None and len(history) >= MAX_EPISODES: reasons.append('history_overflow')
        if row['last_claimed_at'] and (now - _time(row['last_claimed_at'])).total_seconds() < MIN_COOLDOWN_SECONDS: reasons.append('cooldown')
        return {'allowed':not reasons,'reasons':reasons,'key':digest(binding),'authority':False}

    def plan(self, source_recovery, invocation_id, *, now=None, force=False):
        return self._plan(self._read(), source_recovery, invocation_id, _time(now))

    def claim(self, source_recovery, invocation_id, *, now=None, force=False):
        stamp = _time(now)
        with self._lock() as owned:
            table = self._read(); decision = self._plan(table, source_recovery, invocation_id, stamp)
            if not decision['allowed']: return decision
            team = source_recovery['source_team']; row = table['teams'][team]
            if not row['episodes'] or row['episodes'][-1]['failure_fingerprint'] != source_recovery['failure_fingerprint']:
                row['episodes'].append({'episode':len(row['episodes'])+1,'failure_fingerprint':source_recovery['failure_fingerprint'],'attempts':[]})
            claim_id = digest({'key':decision['key'],'sequence':row['lifetime']+1,'invocation_id':invocation_id})
            a = {'claim_id':claim_id,'key':decision['key'],'fixedprocedure_id':source_recovery['fixedprocedure_id'],'invocation_id':invocation_id,'claimed_at':stamp.isoformat(),'status':'CLAIMED','ended_at':None,'outcome':None}
            row['episodes'][-1]['attempts'].append(a); row['lifetime'] += 1; row['last_claimed_at'] = stamp.isoformat(); table['revision'] += 1
            self._write(table, owned)
        return {'allowed':True,'claim':copy.deepcopy(a),'checkpoint':self.checkpoint(),'authority':False}

    def _find(self, table, claim_id):
        for team, row in table['teams'].items():
            for e in row['episodes']:
                for a in e['attempts']:
                    if a['claim_id'] == claim_id: return team, row, a
        raise ValueError('unknown claim')

    def _outcome(self, team, a, exit_code, output, source_proof, validator, stamp):
        if exit_code is not None and type(exit_code) is not int: raise ValueError('invalid exit code')
        if output is not None and not isinstance(output, bytes): raise ValueError('actual output bytes required')
        validated = False; proof = None
        if source_proof is not None:
            self._proof(source_proof)
            if source_proof['source_team'] != team or not _time(a['claimed_at']) <= _time(source_proof['observed_at']) <= stamp: raise ValueError('proof binding/time mismatch')
            if not callable(validator): raise ValueError('trusted validator required')
            validated = validator(copy.deepcopy(a), copy.deepcopy(source_proof), output) is True
            if validated: proof = copy.deepcopy(source_proof)
        output_hash = hashlib.sha256(output).hexdigest() if output is not None else None
        return {'exit_code':exit_code,'output_sha256':output_hash,'source_proof':proof,'actual_source_validated':validated,'source_healthy':exit_code == 0 and validated and output_hash is not None,'receipt_verified':False,'authority':False}

    def finish(self, claim_id, *, exit_code, output=None, source_proof=None, validator=None, now=None):
        stamp = _time(now)
        with self._lock() as owned:
            table = self._read(); team, row, a = self._find(table, claim_id)
            if a['status'] != 'CLAIMED': raise ValueError('claim not live; reconciliation required')
            if stamp < _time(a['claimed_at']): raise ValueError('clock regression')
            a['outcome'] = self._outcome(team, a, exit_code, output, source_proof, validator, stamp)
            a['ended_at'] = stamp.isoformat(); a['status'] = 'FINISHED'; table['revision'] += 1; self._write(table, owned)
        return copy.deepcopy(a)

    def reconcile(self, claim_id, *, trusted_caller=False, exit_code=None, output=None, source_proof=None, validator=None, stop=False, now=None):
        if trusted_caller is not True or type(stop) is not bool: raise ValueError('trusted reconciliation required')
        stamp = _time(now)
        with self._lock() as owned:
            table = self._read(); team, row, a = self._find(table, claim_id)
            if a['status'] not in ('CLAIMED','reconciliation_required'): raise ValueError('already final; no replay')
            if stamp < _time(a['claimed_at']): raise ValueError('clock regression')
            a['outcome'] = self._outcome(team, a, exit_code, output, source_proof, validator, stamp)
            a['ended_at'] = stamp.isoformat(); a['status'] = 'RECONCILED'; row['stopped'] = row['stopped'] or stop
            table['revision'] += 1; self._write(table, owned)
        return copy.deepcopy(a)

    def public_projection(self):
        table = self._read()
        return {'schema_version':1,'revision':table['revision'],'authority':False,'business_clearance':False,'receipt_verified':False,
         'teams':{t:{'lifetime':r['lifetime'],'budget':r['budget'],'stopped':r['stopped'],'episodes':len(r['episodes']),
          'reconciliation_required':any(a['status'] in ('CLAIMED','reconciliation_required') for e in r['episodes'] for a in e['attempts'])} for t,r in table['teams'].items()}}
