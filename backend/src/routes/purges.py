from fastapi import APIRouter, Depends
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.recovery import PurgeInput
from src.services.sample_point_service import accept_purge, get_purge, list_points, list_purges, purge_view
from src.controllers.actions import audit
router = APIRouter()
@router.get('/sample-points')
def points(log_set_id: int | None = None, db=Depends(get_db), user=Depends(current_user)):
    return list_points(db, log_set_id)
@router.get('/purges')
def purges(db=Depends(get_db), user=Depends(current_user)):
    return list_purges(db)
@router.get('/purges/{ident}')
def purge_detail(ident: int, db=Depends(get_db), user=Depends(current_user)):
    return purge_view(db, get_purge(db, ident))
@router.post('/purges', status_code=202)
def create(data: PurgeInput, db=Depends(get_db), user=Depends(writable)):
    job = accept_purge(db, data.log_set_id, data.key)
    audit(db, user, f'purge:accept:{data.log_set_id}:{data.key}')
    db.commit()
    return purge_view(db, job)
