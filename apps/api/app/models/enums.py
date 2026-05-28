import enum


class TrackStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    queued = "queued"
    aired = "aired"
    failed = "failed"
    deleted = "deleted"


class StorageClass(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"
    temp = "temp"
    failed = "failed"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"


class Daypart(str, enum.Enum):
    late_night = "late_night"
    morning = "morning"
    midday = "midday"
    evening = "evening"


class MoodState(str, enum.Enum):
    baseline = "baseline"
    rise = "rise"
    peak = "peak"
    release = "release"
