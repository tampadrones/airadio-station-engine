from datetime import datetime
from pydantic import BaseModel


class OpsEventOut(BaseModel):
    id: int
    timestamp: datetime
    service: str
    host: str
    station_id: int | None
    track_id: int | None
    generation_job_id: str | None
    severity: str
    event_type: str
    message: str
    duration_ms: int | None
    error_code: str | None
    details: dict

    class Config:
        from_attributes = True
