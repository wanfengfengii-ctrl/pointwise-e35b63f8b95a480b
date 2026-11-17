import json
import sys
import tempfile
import unittest
from pathlib import Path
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.analysis import fit_batch, predict_batches, run_day_demo
from application.results import read_result
from cohorts.repository import CohortRepository
from measurements.repository import MeasurementRepository
from results.database import Database, database_session, StorageError


class TestWorkflow(unittest.TestCase):
    def test_correct_reopen_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'laboratory.sqlite'
            database = Database(path)
            rows = json.loads(Path('sample_day.json').read_text())
            try:
                with database_session(database):
                    apply_measurements(rows)
                    cohort = freeze_cohort([r['measurement_id'] for r in rows])
                    snapshot = CohortRepository(database).read(cohort['cohort_id'])
                    fit = fit_batch(cohort['cohort_id'])
                    requests = [{'batch_id':'A','existing':True},
                                {'batch_id':'X','existing':False},
                                {'batch_id':'X','existing':False}]
                    prediction = predict_batches(fit['result_id'], requests)
                    expected_fit = read_result(fit['result_id'])
                    expected_prediction = read_result(prediction['result_id'])
                    fit['snapshot']['rows'][0]['value'] = '9999'
                    prediction['means'][0] = 9999
                    requests[0]['batch_id'] = 'unrelated'
                    self.assertEqual(read_result(fit['result_id']), expected_fit)
                    self.assertEqual(read_result(prediction['result_id']), expected_prediction)
                    count = database.query('SELECT count(*) FROM result_heads')[0][0]
                    database.fail_next_publication('prediction')
                    with self.assertRaises(StorageError):
                        predict_batches(fit['result_id'], [{'batch_id':'Z','existing':False}])
                    self.assertEqual(database.query('SELECT count(*) FROM result_heads')[0][0], count)
                    self.assertEqual(read_result(prediction['result_id']), expected_prediction)
                    predict_batches(fit['result_id'], [{'batch_id':'Z','existing':False}])
                    apply_measurements([dict(rows[0], revision=3, value=99, batch_id='corrected')])
                    apply_measurements(rows)
                    self.assertEqual(MeasurementRepository(database).read_current(rows[0]['measurement_id']).revision, 3)
                    self.assertEqual(CohortRepository(database).read(snapshot.cohort_id), snapshot)
            finally:
                database.close()
            database = Database(path)
            try:
                with database_session(database):
                    forbidden = {'fit_frozen_cohort','select_global_fit','evaluate_fit_state',
                                 'predict_joint_levels','condition_batch_levels','assemble_joint_prediction'}
                    calls = []
                    def observe(frame, event, arg):
                        if event == 'call' and frame.f_code.co_name in forbidden:
                            calls.append(frame.f_code.co_name)
                    previous = sys.getprofile()
                    sys.setprofile(observe)
                    try:
                        self.assertEqual(read_result(expected_fit['result_id']), expected_fit)
                        self.assertEqual(read_result(expected_prediction['result_id']), expected_prediction)
                    finally:
                        sys.setprofile(previous)
                    self.assertEqual(calls, [])
                    self.assertEqual(expected_prediction['fit_id'], expected_fit['result_id'])
                    self.assertEqual(expected_fit['cohort_id'], cohort['cohort_id'])
                    self.assertEqual(expected_fit['provenance'], cohort['provenance'])
                    self.assertEqual(expected_fit['snapshot']['rows'][0]['revision'], 1)
                    self.assertAlmostEqual(expected_prediction['covariance'][1][2], 11.5, delta=1e-8)
            finally:
                database.close()

    def test_demo_and_user_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'demo.sqlite'
            result = run_day_demo(path, 'sample_day.json')
            self.assertAlmostEqual(result['fit']['tau'], 8.5, delta=1e-7)
            with self.assertRaises(ValueError):
                run_day_demo(path, 'sample_day.json')
            database = Database(path)
            try:
                with database_session(database):
                    self.assertEqual(read_result(result['fit']['result_id']), result['fit'])
            finally:
                database.close()
