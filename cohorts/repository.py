import json
from uuid import uuid4
from cohorts.selection import validate_selection_ids, select_current_rows, CohortSelectionError
from cohorts.snapshot import build_snapshot, snapshot_to_record, snapshot_from_record
from measurements.repository import MeasurementRepository


class CohortRepository:
    def __init__(self, database):
        self.database = database

    def freeze(self, identities):
        identities = validate_selection_ids(identities)
        with self.database.transaction():
            current = MeasurementRepository(self.database).read_current_many(identities)
            rows = select_current_rows(identities, current)
            snapshot = build_snapshot('cohort-' + uuid4().hex, rows)
            payload = json.dumps(snapshot_to_record(snapshot), allow_nan=False)
            self.database.execute('INSERT INTO cohorts VALUES(?,?)',
                                  (snapshot.cohort_id, payload))
        return snapshot

    def read(self, cohort_id):
        rows = self.database.query('SELECT payload FROM cohorts WHERE cohort_id=?', (cohort_id,))
        if not rows:
            raise CohortSelectionError('unknown cohort')
        return snapshot_from_record(json.loads(rows[0][0]))
