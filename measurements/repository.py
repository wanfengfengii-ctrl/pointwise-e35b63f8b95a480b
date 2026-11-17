import json
from measurements.model import MeasurementRevision
from measurements.revisions import plan_revision_batch


class MeasurementRepository:
    def __init__(self, database):
        self.database = database

    def read_history(self, identity):
        rows = self.database.query(
            'SELECT payload FROM measurement_history WHERE measurement_id=? ORDER BY revision',
            (identity,))
        return {row.revision: row for row in
                (MeasurementRevision.from_record(json.loads(item[0])) for item in rows)}

    def read_current(self, identity):
        rows = self.database.query(
            'SELECT h.payload FROM measurement_current c JOIN measurement_history h '
            'ON h.measurement_id=c.measurement_id AND h.revision=c.revision '
            'WHERE c.measurement_id=?', (identity,))
        return MeasurementRevision.from_record(json.loads(rows[0][0])) if rows else None

    def read_current_many(self, identities):
        return {identity: self.read_current(identity) for identity in identities}

    def apply_submission(self, submission):
        identities = {item['measurement_id'] if isinstance(item, dict) else item.measurement_id
                      for item in submission}
        with self.database.transaction():
            histories = {identity: self.read_history(identity) for identity in identities}
            plan = plan_revision_batch(submission, histories)
            for row in plan.inserts:
                self.database.execute(
                    'INSERT INTO measurement_history VALUES(?,?,?)',
                    (row.measurement_id, row.revision, json.dumps(row.record(), allow_nan=False)))
            for row in plan.current:
                self.database.execute(
                    'INSERT INTO measurement_current VALUES(?,?) '
                    'ON CONFLICT(measurement_id) DO UPDATE SET revision=excluded.revision',
                    (row.measurement_id, row.revision))
        return [receipt.record() for receipt in plan.receipts]
