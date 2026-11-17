import unittest
from decimal import Decimal
from application.measurements import apply_measurements
from measurements.model import MeasurementError, RevisionConflict, MeasurementStatus
from measurements.repository import MeasurementRepository
from results.database import Database, database_session


class TestMeasurements(unittest.TestCase):
    def setUp(self):
        self.database = Database(':memory:')
        self.session = database_session(self.database)
        self.session.__enter__()
        self.addCleanup(self.database.close)
        self.addCleanup(self.session.__exit__, None, None, None)

    def row(self, identity='m', revision=1, **changes):
        return dict({'measurement_id': identity, 'revision': revision, 'batch_id': 'A',
                     'value': 1000, 'variance': 40000, 'unit': 'ug/L'}, **changes)

    def test_units_and_revision(self):
        repository = MeasurementRepository(self.database)
        apply_measurements([self.row()])
        current = repository.read_current('m')
        self.assertEqual(Decimal(current.value), Decimal(1))
        self.assertEqual(Decimal(current.variance), Decimal('0.04'))
        equivalent = self.row(value=1, variance='0.04', unit='mg/L')
        self.assertEqual(apply_measurements([equivalent])[0]['disposition'], 'replay')
        apply_measurements([self.row(revision=3, value=2000)])
        apply_measurements([self.row(revision=2, value=1500)])
        self.assertEqual(repository.read_current('m').revision, 3)
        self.assertEqual(apply_measurements([self.row()])[0]['current_revision'], 3)
        apply_measurements([{'measurement_id': 'm', 'revision': 4, 'withdrawn': True}])
        self.assertEqual(repository.read_current('m').status, MeasurementStatus.WITHDRAWN)
        apply_measurements([{'measurement_id': 'm', 'revision': 4, 'withdrawn': True}])
        apply_measurements([self.row(revision=5, batch_id='B')])
        self.assertEqual(repository.read_current('m').status, MeasurementStatus.ACTIVE)
        self.assertEqual(repository.read_current('m').batch_id, 'B')
        self.assertEqual(len(repository.read_history('m')), 5)
        with self.assertRaises(MeasurementError):
            apply_measurements([{'measurement_id': 'absent', 'revision': 1, 'withdrawn': True}])

    def test_conflict_atomicity(self):
        repository = MeasurementRepository(self.database)
        apply_measurements([self.row()])
        before = repository.read_history('m')
        for batch in ([self.row('new'), self.row(value=3)],
                      [self.row('new'), self.row('new', value=2)]):
            with self.assertRaises(RevisionConflict):
                apply_measurements(batch)
            self.assertIsNone(repository.read_current('new'))
            self.assertEqual(repository.read_history('m'), before)
        for changes in ({'value': True}, {'variance': 0}, {'value': float('nan')},
                        {'variance': float('inf')}, {'unit': 'ppm'}, {'revision': True},
                        {'batch_id': ''}, {'value': None}):
            item = self.row()
            item.update(changes)
            with self.assertRaises(MeasurementError):
                apply_measurements([self.row('new'), item])
            self.assertIsNone(repository.read_current('new'))
        with self.assertRaises(RevisionConflict):
            apply_measurements([self.row(revision=3), self.row(value=9), self.row('new')])
        self.assertEqual(repository.read_history('m'), before)
