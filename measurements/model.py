from dataclasses import dataclass, asdict
from enum import Enum


class MeasurementError(ValueError):
    pass


class RevisionConflict(MeasurementError):
    pass


class MeasurementStatus(str, Enum):
    ACTIVE = 'active'
    WITHDRAWN = 'withdrawn'


@dataclass(frozen=True)
class MeasurementRevision:
    measurement_id: str
    revision: int
    batch_id: str
    value: str
    variance: str
    status: MeasurementStatus = MeasurementStatus.ACTIVE

    def record(self):
        result = asdict(self)
        result['status'] = self.status.value
        return result

    @classmethod
    def from_record(cls, record):
        data = dict(record)
        data['status'] = MeasurementStatus(data['status'])
        return cls(**data)


@dataclass(frozen=True)
class AcceptanceReceipt:
    measurement_id: str
    submitted_revision: int
    current_revision: int
    disposition: str

    def record(self):
        return asdict(self)


def canonical_content(row):
    return (row.batch_id, row.value, row.variance, row.status.value)
