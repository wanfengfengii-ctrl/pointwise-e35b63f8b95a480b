import unittest
from fractions import Fraction as F
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.analysis import fit_batch, predict_batches
from predictions.requests import PredictionRequestError
from results.database import Database, database_session


def gaussian_oracle(rows, tau, requests):
    # Exact latent precision inverse, independent of production covariance conditioning.
    observed = list(dict.fromkeys(row['batch_id'] for row in rows))
    batches = observed + [b for b in dict.fromkeys(r['batch_id'] for r in requests) if b not in observed]
    dimension = 1 + len(batches) if tau else 1
    precision = [[F(0) for _ in range(dimension)] for _ in range(dimension)]
    rhs = [F(0)] * dimension
    if tau:
        for j in range(1, dimension):
            precision[j][j] = 1 / tau
    for row in rows:
        design = [F(1)] + ([F(b == row['batch_id']) for b in batches] if tau else [])
        for i in range(dimension):
            rhs[i] += design[i] * F(row['value']) / F(row['variance'])
            for j in range(dimension):
                precision[i][j] += design[i] * design[j] / F(row['variance'])
    inverse = [[F(i == j) for j in range(dimension)] for i in range(dimension)]
    for col in range(dimension):
        pivot = precision[col][col]
        precision[col] = [x / pivot for x in precision[col]]
        inverse[col] = [x / pivot for x in inverse[col]]
        for i in range(dimension):
            if i != col:
                factor = precision[i][col]
                precision[i] = [a - factor*b for a,b in zip(precision[i],precision[col])]
                inverse[i] = [a - factor*b for a,b in zip(inverse[i],inverse[col])]
    mean = [sum(a*b for a,b in zip(row,rhs)) for row in inverse]
    designs = [[F(1)] + ([F(b == r['batch_id']) for b in batches] if tau else []) for r in requests]
    means = [sum(a*b for a,b in zip(row,mean)) for row in designs]
    covariance = [[sum(left[i]*inverse[i][j]*right[j]
                       for i in range(dimension) for j in range(dimension))
                   for right in designs] for left in designs]
    return means, covariance


class TestPredictions(unittest.TestCase):
    def setUp(self):
        self.database = Database(':memory:')
        self.session = database_session(self.database)
        self.session.__enter__()
        self.addCleanup(self.database.close)
        self.addCleanup(self.session.__exit__, None, None, None)
        self.rows = [{'measurement_id': str(i), 'revision': 1, 'batch_id': 'ABC'[i//2],
                      'value': value, 'variance': 1, 'unit': 'mg/L'}
                     for i,value in enumerate([1,2,4,5,7,8])]
        apply_measurements(self.rows)
        cohort = freeze_cohort([r['measurement_id'] for r in self.rows])
        self.fit = fit_batch(cohort['cohort_id'])

    def assert_oracle(self, fit, requests, rows, tau):
        result = predict_batches(fit['result_id'], requests)
        means, covariance = gaussian_oracle(rows, tau, requests)
        for i in range(len(requests)):
            self.assertAlmostEqual(result['means'][i], float(means[i]), delta=1e-8)
            for j in range(len(requests)):
                self.assertAlmostEqual(result['covariance'][i][j], float(covariance[i][j]), delta=1e-8)
        return result

    def test_shared_new_identity(self):
        requests = [{'batch_id': b, 'existing': False} for b in ['X','X','Y']]
        result = self.assert_oracle(self.fit, requests, self.rows, F(17,2))
        self.assertEqual(result['means'], [4.5]*3)
        self.assertEqual(result['covariance'][0][0], 11.5)
        self.assertEqual(result['covariance'][0][1], 11.5)
        self.assertEqual(result['covariance'][0][2], 3)
        self.assertEqual(result['covariance'][0][0]+result['covariance'][1][1]-
                         2*result['covariance'][0][1], 0)
        apply_measurements([dict(row, revision=2, value=1) for row in self.rows])
        cohort = freeze_cohort([r['measurement_id'] for r in self.rows])
        zero = fit_batch(cohort['cohort_id'])
        zero_result = self.assert_oracle(zero, requests, [dict(r,value=1) for r in self.rows], F(0))
        self.assertEqual(zero['tau'], 0)
        self.assertAlmostEqual(zero_result['covariance'][0][1], 1/6, delta=1e-8)

    def test_existing_conditioning_and_conflict(self):
        requests = [{'batch_id': b, 'existing': b in 'ABC'} for b in ['A','X','C','A']]
        result = self.assert_oracle(self.fit, requests, self.rows, F(17,2))
        self.assertAlmostEqual(result['means'][0], 5/3, delta=1e-8)
        self.assertAlmostEqual(result['means'][1], 4.5, delta=1e-8)
        permutation = [2,0,3,1]
        reordered = predict_batches(self.fit['result_id'], [requests[i] for i in permutation])
        for i,p in enumerate(permutation):
            self.assertEqual(reordered['means'][i], result['means'][p])
            for j,q in enumerate(permutation):
                self.assertEqual(reordered['covariance'][i][j], result['covariance'][p][q])
        count = self.database.query('SELECT count(*) FROM result_heads')[0][0]
        for invalid in ([{'batch_id':'A','existing':False}],
                        [{'batch_id':'unknown','existing':True}],
                        [{'batch_id':'X','existing':False},{'batch_id':'X','existing':True}],
                        [{'batch_id':'X','existing':1}], [{'batch_id':'','existing':False}]):
            with self.assertRaises(PredictionRequestError):
                predict_batches(self.fit['result_id'], invalid)
            self.assertEqual(self.database.query('SELECT count(*) FROM result_heads')[0][0], count)
        empty = predict_batches(self.fit['result_id'], [])
        self.assertEqual((empty['means'],empty['covariance']), ([],[]))

    def test_heteroscedastic_conditioning(self):
        values, variances = [-8,-8,0,-9,1], ['1','0.1','100','0.1','10']
        rows = [{'measurement_id':'h'+str(i),'revision':1,'batch_id':'H'+str(i),
                 'value':value,'variance':variance,'unit':'mg/L'}
                for i,(value,variance) in enumerate(zip(values,variances))]
        apply_measurements(rows)
        cohort = freeze_cohort([r['measurement_id'] for r in rows])
        fit = fit_batch(cohort['cohort_id'])
        requests = [{'batch_id':b,'existing':b.startswith('H')}
                    for b in ['H0','new','H1','H0','new']]
        self.assert_oracle(fit, requests, rows, F(str(fit['tau'])))
