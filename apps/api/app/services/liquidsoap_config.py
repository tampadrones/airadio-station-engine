from __future__ import annotations

from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.station import Station


def render_liquidsoap_station_include(db: Session) -> str:
    stations = db.query(Station).filter(Station.is_enabled.is_(True)).order_by(Station.slug.asc()).all()
    lines = [f'mk_station("{st.slug}")' for st in stations]
    return "\n".join(lines) + ("\n" if lines else "")


def write_liquidsoap_station_include(db: Session) -> bool:
    s = get_settings()
    target = Path(s.playback_root) / "liquidsoap_stations.liq"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_liquidsoap_station_include(db)
    previous = target.read_text() if target.exists() else ""
    if previous == content:
        return False
    target.write_text(content)
    return True


def force_liquidsoap_reload(db: Session) -> None:
    s = get_settings()
    target = Path(s.playback_root) / "liquidsoap_stations.liq"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_liquidsoap_station_include(db)
    marker = datetime.utcnow().isoformat()
    target.write_text(f"# reload {marker}\n{content}")
