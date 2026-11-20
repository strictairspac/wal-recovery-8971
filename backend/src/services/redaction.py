"""Redaction helpers shared by the WAL engine, read APIs and purge worker.

A purged sampling point is never physically deleted from a log prefix: the log
is scrubbed in place so LSN positions (and therefore every stored crash point)
stay unchanged.  Writes to a purged key become opaque ``redacted`` markers and
the key is removed from every ledger the model exposes.
"""
import copy
import hashlib
import json


def scrub_records(records, keys):
    """Replace writes to ``keys`` with position-preserving redacted markers."""
    keys = set(keys)
    if not keys:
        return copy.deepcopy(list(records))
    cleaned = []
    for item in records:
        row = copy.deepcopy(item)
        if isinstance(row, dict) and row.get('op') == 'write' and row.get('key') in keys:
            row = {'op': 'write', 'tx': row.get('tx'), 'redacted': True}
        cleaned.append(row)
    return cleaned


def scrub_initial(initial, keys):
    keys = set(keys)
    return {k: v for k, v in (initial or {}).items() if k not in keys}


def scrub_log_set(serialized, keys):
    """Scrub a serialized LogSet dict (as produced by utils.serialize.record)."""
    keys = set(keys)
    if not keys:
        return copy.deepcopy(serialized)
    out = copy.deepcopy(serialized)
    if isinstance(out.get('initial'), dict):
        out['initial'] = scrub_initial(out['initial'], keys)
    if isinstance(out.get('records'), list):
        out['records'] = scrub_records(out['records'], keys)
    out['redacted_points'] = sorted(set(out.get('redacted_points') or []) | keys)
    return out


def scrub_snapshot(snapshot, keys):
    """Scrub a frozen Recovery snapshot: the queued log set plus metadata."""
    keys = set(keys)
    if not isinstance(snapshot, dict) or not keys:
        return copy.deepcopy(snapshot)
    out = copy.deepcopy(snapshot)
    if isinstance(out.get('log_set'), dict):
        out['log_set'] = scrub_log_set(out['log_set'], keys)
    out['redacted_points'] = sorted(set(out.get('redacted_points') or []) | keys)
    return out


def scrub_result(result, keys):
    """Remove every reading of ``keys`` from a stored recovery report."""
    keys = set(keys)
    if not isinstance(result, dict) or not keys:
        return copy.deepcopy(result)
    removed = count_references(result, keys)
    previous_result_sha = result.get('result_sha256')
    out = copy.deepcopy(result)
    for field in ('durable_checkpoint', 'after_redo', 'recovered', 'oracle'):
        if isinstance(out.get(field), dict):
            out[field] = {k: v for k, v in out[field].items() if k not in keys}
    if isinstance(out.get('trace'), list):
        out['trace'] = [row for row in out['trace'] if not (isinstance(row, dict) and row.get('key') in keys)]
        out['redo_count'] = len([row for row in out['trace'] if row.get('phase') == 'redo'])
        out['undo_count'] = len([row for row in out['trace'] if row.get('phase') == 'undo_loser'])
    if isinstance(out.get('recovered'), dict) and isinstance(out.get('oracle'), dict):
        out['invariant_passed'] = out['recovered'] == out['oracle']
        out['result_sha256'] = hashlib.sha256(json.dumps(out['recovered'], sort_keys=True).encode()).hexdigest()
    out['redacted_points'] = sorted(set(out.get('redacted_points') or []) | keys)
    if removed:
        # The stored hashes covered the readings that were just removed.
        out['input_sha256'] = None
        out['result_sha256_before_redaction'] = previous_result_sha
        out['hashes_invalidated'] = True
    return out


def count_references(value, keys):
    """Count ledger/record references to any of ``keys`` inside a JSON value."""
    keys = set(keys)
    if isinstance(value, dict):
        return sum((1 if k in keys else 0) + count_references(v, keys) for k, v in value.items())
    if isinstance(value, list):
        return sum(count_references(v, keys) for v in value)
    return 1 if value in keys else 0
