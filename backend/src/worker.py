import logging, time
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.constants.enums import PURGE_STEPS
from src.models.entities import PurgeJob, Recovery, SamplePoint
from src.services.redaction import scrub_result, scrub_snapshot
from src.services.sample_point_service import apply_step, hidden_keys
from src.services.wal_engine import recover
redis = Redis.from_url(REDIS_URL)
logging.basicConfig(level=logging.INFO)

def persist_recovery(db, job):
    """Run one queued recovery, then persist a result that never resurrects a purged point."""
    job.status = 'running'
    db.flush()
    try:
        result = recover(job.snapshot['log_set']['initial'],job.snapshot['log_set']['records'],job.snapshot['case']['crash_after'])
        status = 'completed'
    except ValueError as exc:
        result = {'error': str(exc), 'simulation': True}
        status = 'failed'
    # Hold the lifecycle rows until commit so a purge accepted concurrently either
    # lands before this read (and is honoured) or waits and scrubs this result.
    log_set_id = job.snapshot['log_set']['id']
    list(db.scalars(select(SamplePoint.id).where(SamplePoint.log_set_id == log_set_id).order_by(SamplePoint.id).with_for_update()))
    hidden = hidden_keys(db, log_set_id)
    if hidden:
        # Concurrent purge accepted after this job was queued: strip the readings.
        result = scrub_result(result, hidden)
        job.snapshot = scrub_snapshot(job.snapshot, hidden)
    job.result = result
    job.status = status
    db.commit()
    logging.info('recovery %s %s', job.id, job.status)

def run_purge(db, job):
    """Advance one purge job by one durable unit, resumable after interruption."""
    steps_done = list(job.steps_done or [])
    step = next((s for s in PURGE_STEPS if s not in steps_done), None)
    if step is None:
        job.status = 'completed'
        db.commit()
        return
    job.status = 'running'
    apply_step(db, job, step)
    # Lock the lifecycle row last, then read the authoritative state back.
    point = db.scalar(select(SamplePoint).where(SamplePoint.log_set_id == job.log_set_id, SamplePoint.key == job.point_key).with_for_update())
    done = [s for s in PURGE_STEPS if s in steps_done] + [step]
    job.steps_done = [s for s in PURGE_STEPS if s in done]
    if all(s in job.steps_done for s in PURGE_STEPS):
        if point is not None and point.status == 'purging':
            point.status = 'purged'
        job.status = 'completed'
        job.message = '清理完成，读数不再保留'
    else:
        job.message = f'已完成 {step}，继续清理'
    # Single durable commit: the scrub unit and its step marker land together.
    db.commit()

def tick():
    """One pass over the durable queue; returns True if a unit of work was done."""
    lock = redis.lock('wal-worker', timeout=15, blocking_timeout=1)
    with lock:
        with Session() as db:
            recovery = db.scalar(select(Recovery).where(Recovery.status == 'queued').order_by(Recovery.id).with_for_update(skip_locked=True))
            if recovery is not None:
                persist_recovery(db, recovery)
                return True
            job = db.scalar(select(PurgeJob).where(PurgeJob.status.in_(('queued','running'))).order_by(PurgeJob.id).with_for_update(skip_locked=True))
            if job is not None:
                run_purge(db, job)
                logging.info('purge %s %s', job.id, job.status)
                return True
    return False

def main():
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            tick()
        except Exception:
            logging.exception('worker retry')
        time.sleep(1)

if __name__ == '__main__':
    main()
