from __future__ import annotations

import socket
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.enums import Severity
from app.models.ops_event import OpsEvent


def emit_event(
    db: Session,
    *,
    service: str,
    event_type: str,
    message: str,
    severity: Severity = Severity.info,
    station_id: int | None = None,
    track_id: int | None = None,
    generation_job_id: str | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    details: dict | None = None,
) -> OpsEvent:
    ev = OpsEvent(
        timestamp=datetime.utcnow(),
        service=service,
        host=socket.gethostname(),
        station_id=station_id,
        track_id=track_id,
        generation_job_id=generation_job_id,
        severity=severity,
        event_type=event_type,
        message=message,
        duration_ms=duration_ms,
        error_code=error_code,
        details=details or {},
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
