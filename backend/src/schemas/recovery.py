from pydantic import BaseModel, Field
class RecoveryInput(BaseModel):
    crash_case_id: int=Field(gt=0)
    label: str=Field(min_length=2,max_length=120)
class PurgeInput(BaseModel):
    log_set_id: int=Field(gt=0)
    key: str=Field(min_length=1,max_length=50,pattern=r'^[A-Za-z0-9_-]+$')
