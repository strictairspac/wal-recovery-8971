from sqlalchemy import select
from src.models.entities import LogSet
from src.services.wal_engine import validate
from src.services.sample_point_service import create_points_for_log_set, hidden_keys
from src.services.sample_point_service import log_set_view as view_log_set
from src.utils.serialize import record

def list_log_sets(db):
    return [view_log_set(db, x, hidden_keys(db, x.id)) for x in db.scalars(select(LogSet).order_by(LogSet.id))]
def log_set_view(db, obj):
    return view_log_set(db, obj, hidden_keys(db, obj.id))
def create_log_set(db,data):
    values=data.model_dump();validate(values['initial'],values['records'])
    obj=LogSet(**values);db.add(obj);db.flush();create_points_for_log_set(db,obj);return record(obj)
