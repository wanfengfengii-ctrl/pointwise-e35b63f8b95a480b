import unittest
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.analysis import fit_batch
from application.results import read_result
from results.database import Database, database_session, StorageError, ResultNotFound
from results.schema import initialize_schema, SchemaVersionError
from results.fit_codec import decode_fit, FitPayloadError
from results.prediction_codec import decode_prediction, PredictionPayloadError


class TestPublication(unittest.TestCase):
    def test_fit_failure_retry(self):
        database = Database(':memory:')
        self.addCleanup(database.close)
        with database_session(database):
            rows = [{'measurement_id':str(i),'revision':1,'batch_id':str(i//2),
                     'value':value,'variance':1,'unit':'mg/L'}
                    for i,value in enumerate([1,2,4,5,7,8])]
            apply_measurements(rows)
            cohort = freeze_cohort([r['measurement_id'] for r in rows])
            old = fit_batch(cohort['cohort_id'])
            before_heads = database.query('SELECT * FROM result_heads')
            before_payloads = database.query('SELECT * FROM result_payloads')
            database.fail_next_publication('fit')
            with self.assertRaises(StorageError):
                fit_batch(cohort['cohort_id'])
            self.assertEqual(database.query('SELECT * FROM result_heads'), before_heads)
            self.assertEqual(database.query('SELECT * FROM result_payloads'), before_payloads)
            self.assertEqual(read_result(old['result_id']), old)
            retry = fit_batch(cohort['cohort_id'])
            self.assertNotEqual(old['result_id'], retry['result_id'])
            self.assertEqual(old['tau'], retry['tau'])
            initialize_schema(database.connection)
            self.assertEqual(read_result(old['result_id']), old)
            self.assertEqual(database.query('SELECT count(*) FROM measurement_history')[0][0], 6)
            with self.assertRaises(ResultNotFound):
                read_result('absent')
            with self.assertRaises(FitPayloadError):
                decode_fit('{"version":1}')
            with self.assertRaises(PredictionPayloadError):
                decode_prediction('{"version":1}')
            database.execute('UPDATE metadata SET version=2')
            with self.assertRaises(SchemaVersionError):
                initialize_schema(database.connection)
            database.execute('UPDATE metadata SET version=1')
            self.assertEqual(read_result(old['result_id']), old)
