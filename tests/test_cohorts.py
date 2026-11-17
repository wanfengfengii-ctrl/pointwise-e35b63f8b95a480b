import unittest
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from cohorts.repository import CohortRepository
from cohorts.selection import CohortSelectionError
from results.database import Database, database_session


class TestCohorts(unittest.TestCase):
    def test_withdrawn_and_frozen(self):
        database = Database(':memory:')
        self.addCleanup(database.close)
        with database_session(database):
            rows = [{'measurement_id': identity, 'revision': 1, 'batch_id': batch,
                     'value': value, 'variance': 1, 'unit': 'mg/L'}
                    for identity, batch, value in [('m1', 'A', 1), ('m2', 'A', 2), ('m3', 'B', 4)]]
            apply_measurements(rows)
            result = freeze_cohort(['m3', 'm1', 'm2'])
            repository = CohortRepository(database)
            frozen = repository.read(result['cohort_id'])
            self.assertEqual([r.measurement_id for r in frozen.rows], ['m3', 'm1', 'm2'])
            self.assertEqual([s['revision'] for s in result['provenance']['sources']], [1, 1, 1])
            apply_measurements([dict(rows[0], revision=2, value=99, batch_id='changed')])
            apply_measurements([{'measurement_id': 'm2', 'revision': 2, 'withdrawn': True}])
            self.assertEqual(repository.read(frozen.cohort_id), frozen)
            newer = freeze_cohort(['m1', 'm3'])
            self.assertEqual(repository.read(newer['cohort_id']).rows[0].batch_id, 'changed')
            count = database.query('SELECT count(*) FROM cohorts')[0][0]
            for invalid in ([], ['m1', 'm1'], ['missing'], ['m2']):
                with self.assertRaises(CohortSelectionError):
                    freeze_cohort(invalid)
                self.assertEqual(database.query('SELECT count(*) FROM cohorts')[0][0], count)
            apply_measurements([dict(rows[1], revision=3)])
            self.assertNotEqual(freeze_cohort(['m2'])['cohort_id'], frozen.cohort_id)
            self.assertEqual(repository.read(frozen.cohort_id), frozen)
