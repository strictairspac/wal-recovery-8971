"""Sampling-point retention and the resumable purge state machine.

Lifecycle of a sampling point:

    active --(purge accepted)--> purging --(all steps committed)--> purged

Reads hide a point as soon as its purge is accepted (``purging``), so old
reports and exports stop exposing it before the background scrub finishes.
The scrub itself is split into ordered, independently committed units so an
interrupted run resumes at the first unit that was not committed.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from src.constants.enums import PURGE_STEPS
from src.models.entities import CrashCase, LogSet, PurgeJob, Recovery, SamplePoint
from src.services.redaction import scrub_log_set, scrub_result, scrub_snapshot
from src.utils.serialize import record

HIDDEN_STATUSES = ('purging', 'purged')
DEFAULT_RETENTION_DAYS = 365


def today():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_points_for_log_set(db, log_set, retention_days=DEFAULT_RETENTION_DAYS):
    for key in log_set.initial:
        if not db.scalar(select(SamplePoint.id).where(SamplePoint.log_set_id == log_set.id, SamplePoint.key == key)):
            db.add(SamplePoint(log_set_id=log_set.id, key=key, retain_until=today() + timedelta(days=retention_days)))


def backfill_points(db, retention_days=DEFAULT_RETENTION_DAYS):
    """Register lifecycle rows for log sets that predate the retention feature."""
    for log_set in db.scalars(select(LogSet).order_by(LogSet.id)):
        purged = set(log_set.redacted_points or [])
        for key in set(log_set.initial or {}) | purged:
            if db.scalar(select(SamplePoint.id).where(SamplePoint.log_set_id == log_set.id, SamplePoint.key == key)):
                continue
            if key in purged:
                db.add(SamplePoint(log_set_id=log_set.id, key=key, retain_until=today(), status='purged'))
            else:
                db.add(SamplePoint(log_set_id=log_set.id, key=key, retain_until=today() + timedelta(days=retention_days)))


def list_points(db, log_set_id=None):
    query = select(SamplePoint).order_by(SamplePoint.log_set_id, SamplePoint.id)
    if log_set_id is not None:
        query = query.where(SamplePoint.log_set_id == log_set_id)
    now = today()
    out = []
    for point in db.scalars(query):
        row = record(point)
        row['expired'] = point.retain_until <= now
        row['in_ledger'] = point.status == 'active'
        out.append(row)
    return out


def hidden_map(db, log_set_id=None):
    """Keys hidden from every read, keyed by log set id."""
    query = select(SamplePoint).where(SamplePoint.status.in_(HIDDEN_STATUSES))
    if log_set_id is not None:
        query = query.where(SamplePoint.log_set_id == log_set_id)
    out = {}
    for point in db.scalars(query):
        out.setdefault(point.log_set_id, set()).add(point.key)
    return out


def hidden_keys(db, log_set_id):
    return hidden_map(db, log_set_id).get(log_set_id, set())


def recovery_log_set_id(db, recovery, case_cache):
    case = case_cache.get(recovery.crash_case_id)
    if case is None:
        case = db.get(CrashCase, recovery.crash_case_id)
        case_cache[recovery.crash_case_id] = case
    return case.log_set_id if case else None


def scrub_recovery(db, obj, hidden=None, case_cache=None):
    """Return this recovery's serialized report with purged readings removed.

    Applied on every read *and* before the worker persists a result, so a
    recovery that finishes after the purge was accepted can never write the
    point back into a stored report.
    """
    out = record(obj)
    if hidden is None:
        case_cache = case_cache if case_cache is not None else {}
        log_set_id = recovery_log_set_id(db, obj, case_cache)
        hidden = hidden_keys(db, log_set_id) if log_set_id is not None else set()
    if not hidden:
        return out
    out['snapshot'] = scrub_snapshot(out.get('snapshot'), hidden)
    out['result'] = scrub_result(out.get('result'), hidden)
    # Old reports and downloads must not expose the purged point at all, not even
    # by name; cleanup progress is reported through /purges instead.
    out['snapshot'].pop('redacted_points', None)
    out['snapshot'].get('log_set', {}).pop('redacted_points', None) if isinstance(out['snapshot'].get('log_set'), dict) else None
    if isinstance(out.get('result'), dict):
        out['result'].pop('redacted_points', None)
    return out


def log_set_view(db, obj, hidden):
    out = record(obj)
    out.setdefault('redacted_points', [])
    if hidden:
        out = scrub_log_set(out, hidden)
    return out


def accept_purge(db, log_set_id, key):
    logs = db.get(LogSet, log_set_id)
    if logs is None:
        raise HTTPException(404, '日志集不存在')
    point = db.scalar(
        select(SamplePoint)
        .where(SamplePoint.log_set_id == log_set_id, SamplePoint.key == key)
        .with_for_update()
    )
    if point is None:
        raise HTTPException(404, '采样点不存在')
    if point.status == 'purged':
        raise HTTPException(409, '该采样点已清理完成')
    existing = db.scalar(
        select(PurgeJob)
        .where(PurgeJob.log_set_id == log_set_id, PurgeJob.point_key == key, PurgeJob.status.in_(('queued', 'running')))
        .order_by(PurgeJob.id.desc())
    )
    if existing is not None:
        return existing
    # Hide first, scrub later: reads stop exposing the point at acceptance time.
    point.status = 'purging'
    job = PurgeJob(log_set_id=log_set_id, point_key=key, status='queued', steps_done=[], message='已受理，等待清理')
    db.add(job)
    db.flush()
    return job


def get_purge(db, ident):
    job = db.get(PurgeJob, ident)
    if job is None:
        raise HTTPException(404, '清理任务不存在')
    return job


def list_purges(db):
    return [purge_view(db, job) for job in db.scalars(select(PurgeJob).order_by(PurgeJob.id.desc()).limit(100))]


def purge_view(db, job):
    out = record(job)
    done = [step for step in PURGE_STEPS if step in (job.steps_done or [])]
    out['steps_done'] = done
    out['steps_total'] = len(PURGE_STEPS)
    out['progress'] = f'{len(done)}/{len(PURGE_STEPS)}'
    out['remaining_step'] = next((step for step in PURGE_STEPS if step not in done), None)
    logs = db.get(LogSet, job.log_set_id)
    if logs is not None:
        view = log_set_view(db, logs, hidden_keys(db, job.log_set_id))
        out['remaining_ledger'] = view.get('initial', {})
    point = db.scalar(select(SamplePoint).where(SamplePoint.log_set_id == job.log_set_id, SamplePoint.key == job.point_key))
    out['point_status'] = point.status if point else 'missing'
    return out


def apply_step(db, job, step):
    """Idempotently scrub one unit; caller commits it together with steps_done."""
    key = job.point_key
    if step == 'redact_logs':
        logs = db.get(LogSet, job.log_set_id)
        if logs is not None:
            logs.initial = {k: v for k, v in (logs.initial or {}).items() if k != key}
            logs.records = _scrub_records(logs.records, key)
            logs.redacted_points = sorted(set(logs.redacted_points or []) | {key})
    elif step == 'redact_snapshots':
        for recovery in _recoveries_of_log_set(db, job.log_set_id):
            recovery.snapshot = scrub_snapshot(recovery.snapshot, {key})
    elif step == 'redact_results':
        for recovery in _recoveries_of_log_set(db, job.log_set_id):
            recovery.result = scrub_result(recovery.result, {key})
    else:  # pragma: no cover - guarded by PURGE_STEPS
        raise ValueError(f'未知清理步骤 {step}')


def _scrub_records(records, key):
    from src.services.redaction import scrub_records
    return scrub_records(records, {key})


def _recoveries_of_log_set(db, log_set_id):
    # Lock order everywhere: Recovery rows first, then SamplePoint rows.
    case_ids = list(db.scalars(select(CrashCase.id).where(CrashCase.log_set_id == log_set_id)))
    if not case_ids:
        return []
    return list(db.scalars(
        select(Recovery).where(Recovery.crash_case_id.in_(case_ids)).order_by(Recovery.id).with_for_update()
    ))
