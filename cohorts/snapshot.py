from dataclasses import dataclass, asdict
from decimal import Decimal
from measurements.validation import validate_identifier
from cohorts.provenance import capture_provenance, validate_provenance


@dataclass(frozen=True)
class FrozenRow:
    measurement_id: str
    revision: int
    batch_id: str
    value: str
    variance: str


@dataclass(frozen=True)
class FrozenCohort:
    cohort_id: str
    rows: tuple

    @property
    def batches(self):
        return tuple(dict.fromkeys(row.batch_id for row in self.rows))


def build_snapshot(cohort_id, rows):
    frozen = tuple(FrozenRow(row.measurement_id, row.revision, row.batch_id,
                            row.value, row.variance) for row in rows)
    snapshot = FrozenCohort(cohort_id, frozen)
    return snapshot_from_record(snapshot_to_record(snapshot))


def snapshot_to_record(snapshot):
    return {'cohort_id': snapshot.cohort_id, 'unit': 'mg/L',
            'rows': [asdict(row) for row in snapshot.rows]}


def snapshot_from_record(record):
    if set(record) != {'cohort_id', 'unit', 'rows'} or record['unit'] != 'mg/L':
        raise ValueError('invalid snapshot format')
    identity = validate_identifier(record['cohort_id'])
    if not isinstance(record['rows'], list) or not record['rows']:
        raise ValueError('empty snapshot')
    rows = tuple(FrozenRow(**row) for row in record['rows'])
    for row in rows:
        validate_identifier(row.measurement_id)
        validate_identifier(row.batch_id)
        if type(row.revision) is not int or row.revision <= 0:
            raise ValueError('invalid source revision')
        y, v = Decimal(row.value), Decimal(row.variance)
        if not y.is_finite() or not v.is_finite() or v <= 0:
            raise ValueError('invalid frozen measurement')
    validate_provenance(rows, capture_provenance(rows))
    return FrozenCohort(identity, rows)
