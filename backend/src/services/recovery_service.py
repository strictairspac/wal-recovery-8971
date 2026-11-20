from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Recovery,CrashCase,LogSet
from src.services.sample_point_service import hidden_map, hidden_keys, log_set_view, scrub_recovery
from src.utils.serialize import record

def list_recoveries(db):
    hidden = hidden_map(db)
    cases = {}
    out = []
    for obj in db.scalars(select(Recovery).order_by(Recovery.id.desc()).limit(100)):
        case = cases.get(obj.crash_case_id)
        if case is None:
            case = db.get(CrashCase, obj.crash_case_id)
            cases[obj.crash_case_id] = case
        log_set_id = case.log_set_id if case else None
        out.append(scrub_recovery(db, obj, hidden.get(log_set_id, set()) if log_set_id is not None else set(), cases))
    return out
def get_recovery(db,ident):
    obj=db.get(Recovery,ident)
    if obj is None:raise HTTPException(404,'恢复记录不存在')
    return obj
def recovery_view(db, obj):
    return scrub_recovery(db, obj)
def create_recovery(db,data):
    case=db.get(CrashCase,data.crash_case_id)
    if case is None:raise HTTPException(404,'故障场景不存在')
    if len(db.scalars(select(Recovery.id).where(Recovery.status.in_(['queued','running']))).all())>=20:raise HTTPException(429,'待处理配额20已满')
    logs=db.get(LogSet,case.log_set_id)
    # Snapshot the log set with every already-accepted purge applied, so a queued
    # job never captures readings that are no longer allowed to be kept.
    snapshot_logs = log_set_view(db, logs, hidden_keys(db, case.log_set_id)) if logs is not None else record(logs)
    obj=Recovery(**data.model_dump(),status='queued',snapshot={'log_set':snapshot_logs,'case':record(case)})
    db.add(obj);db.flush();return obj
