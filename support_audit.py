"""Independent business audit for the variance-support extension.

This module is a separate accounting layer, not part of the production solver.
It rebuilds every published quantity from the frozen inputs using independent
constructions (full-matrix Decimal Gauss-Jordan inversion, Fraction Gaussian
moments and direct level-crossing checks) and asserts the business invariants
of SUPPORT.md:

* every component is closed, ordered, keeps its real gaps and never envelopes
  points whose likelihood is below the level;
* the component endpoints satisfy ell_R = M - drop (or sit on the tau = 0
  domain boundary above the level);
* every per-entry mean/covariance range contains the independently computed
  moment at interior taus of every component;
* the ranges are entrywise only - the audit never assembles a joint
  distribution from separately attained extrema;
* published support/range results survive source corrections unchanged.

Run directly:  python3.11 -B support_audit.py
"""
import json
import random
import tempfile
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from results.database import Database, database_session, StorageError
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.analysis import fit_batch, support_batch, predict_support
from application.results import read_result
from tests.test_batch_fit import independent_reml
from tests.test_predictions import gaussian_oracle


def _multi_stationary_source():
    case = json.loads(Path('NUMERICAL_CASES.json').read_text())['multi_stationary']
    return [
        {'measurement_id': 's' + str(i), 'revision': 1, 'batch_id': batch,
         'value': value, 'variance': variance, 'unit': 'mg/L'}
        for i, (batch, value, variance) in enumerate(
            zip(case['batches'], case['values'], case['variances']))
    ], case


def _frozen_snapshot(cohort_id, source):
    from cohorts.snapshot import FrozenRow, FrozenCohort
    return FrozenCohort(cohort_id, tuple(
        FrozenRow(row['measurement_id'], 1, row['batch_id'],
                  str(row['value']), str(row['variance'])) for row in source))


def audit_support_set(database, fit, source, drop_text):
    from results.fit_codec import decode_fit
    support = support_batch(fit['result_id'], Decimal(drop_text))
    assert support['kind'] == 'support'
    assert support['fit_id'] == fit['result_id']
    assert support['cohort_id'] == fit['cohort_id']
    assert support['snapshot'] == fit['snapshot']
    assert support['provenance'] == fit['provenance']
    problem = decode_fit(database.read_published(fit['result_id'])['payload']).state.problem
    snapshot = _frozen_snapshot(fit['cohort_id'], source)
    maximum = Decimal(str(fit['log_likelihood']))
    level = maximum - Decimal(drop_text)
    components = support['components']
    assert components and all(lo >= 0 and lo <= hi for lo, hi in components)
    assert components == sorted(components)
    for lo, hi in components:
        if lo > 0:
            assert abs(independent_reml(snapshot, Decimal(str(lo))) - level) < Decimal('1e-6')
        else:
            assert independent_reml(snapshot, Decimal(0)) >= level - Decimal('1e-9')
        assert abs(independent_reml(snapshot, Decimal(str(hi))) - level) < Decimal('1e-6')
    for left, right in zip(components, components[1:]):
        assert left[1] < right[0]
        middle = Decimal(str((left[1] + right[0]) / 2))
        assert independent_reml(snapshot, middle) < level
    rng = random.Random(20261117)
    span = components[-1][1]
    for _ in range(300):
        tau = rng.random() * span * 1.04
        inside = any(lo <= tau <= hi for lo, hi in components)
        above = independent_reml(snapshot, Decimal(str(tau))) >= level - Decimal('1e-9')
        assert not (above and not inside)
    return support, problem


def audit_ranges(database, support, source, requests):
    report = predict_support(support['result_id'], requests)
    assert report['kind'] == 'support_prediction'
    assert report['support_id'] == support['result_id']
    assert report['fit_id'] == support['fit_id']
    assert report['requests'] == requests
    size = len(requests)
    assert len(report['mean_ranges']) == size
    assert len(report['covariance_ranges']) == size
    assert all(len(row) == size for row in report['covariance_ranges'])
    rng = random.Random(99)
    for lo, hi in support['components']:
        for _ in range(60):
            tau = lo + rng.random() * (hi - lo)
            means, covariance = gaussian_oracle(source, Fraction(str(tau)), requests)
            for i in range(size):
                low, high = report['mean_ranges'][i]
                assert low - 1e-8 <= float(means[i]) <= high + 1e-8
                for j in range(size):
                    low, high = report['covariance_ranges'][i][j]
                    assert low - 1e-8 <= float(covariance[i][j]) <= high + 1e-8
    for i in range(size):
        assert report['mean_ranges'][i][0] <= report['mean_ranges'][i][1]
        for j in range(size):
            pair = report['covariance_ranges'][i][j]
            assert pair[0] <= pair[1]
            assert pair == report['covariance_ranges'][j][i]
    return report


def audit_publication_rollback(database, fit, support, requests):
    def snapshot_state():
        return (tuple(database.query('SELECT * FROM support_heads')),
                tuple(database.query('SELECT * FROM support_payloads')),
                tuple(database.query('SELECT * FROM support_prediction_heads')),
                tuple(database.query('SELECT * FROM support_prediction_payloads')))
    before = snapshot_state()
    database.fail_next_publication('support')
    try:
        support_batch(fit['result_id'], Decimal('0.080'))
        raise AssertionError('support failure fixture did not fire')
    except StorageError:
        pass
    assert snapshot_state() == before
    database.fail_next_publication('support_prediction')
    try:
        predict_support(support['result_id'], requests)
        raise AssertionError('support prediction failure fixture did not fire')
    except StorageError:
        pass
    assert snapshot_state() == before
    # Removing the one-shot failure allows a stable retry with a fresh identity.
    retried_support = support_batch(fit['result_id'], Decimal('0.080'))
    retried_report = predict_support(support['result_id'], requests)
    assert read_result(retried_support['result_id']) == retried_support
    assert read_result(retried_report['result_id']) == retried_report


def main():
    source, case = _multi_stationary_source()
    requests = [{'batch_id': b, 'existing': b == 'A'} for b in ['A', 'X', 'X', 'Y']]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'audit.sqlite'
        database = Database(path)
        try:
            with database_session(database):
                apply_measurements(source)
                cohort = freeze_cohort([row['measurement_id'] for row in source])
                fit = fit_batch(cohort['cohort_id'])
                with localcontext() as context:
                    context.prec = 70
                    # Two-component drop keeps a genuine gap and an interior peak.
                    support, _ = audit_support_set(database, fit, source, '0.080')
                    assert len(support['components']) == 2
                    gap = Decimal('3.5556579892030454')
                    peak = Decimal('5.040483857472118')
                    snapshot = _frozen_snapshot(fit['cohort_id'], source)
                    level = Decimal(str(fit['log_likelihood'])) - Decimal('0.080')
                    assert independent_reml(snapshot, gap) < level
                    assert independent_reml(snapshot, peak) > level
                    audit_ranges(database, support, source, requests)
                    # Zero drop collapses to the published global maximizer.
                    zero = support_batch(fit['result_id'], 0)
                    assert zero['components'] == [[fit['tau'], fit['tau']]]
                    point = predict_support(zero['result_id'], requests)
                    for i, pair in enumerate(point['mean_ranges']):
                        assert pair[0] == pair[1]
                    audit_publication_rollback(database, fit, support, requests)
                saved_support = read_result(support['result_id'])
                saved_report = predict_support(support['result_id'], requests)
                # A later correction must not move any frozen result.
                apply_measurements(
                    [dict(source[0], revision=2, value=99, batch_id='corrected')])
                assert read_result(saved_support['result_id']) == saved_support
                assert read_result(saved_report['result_id']) == saved_report
        finally:
            database.close()
        database = Database(path)
        try:
            with database_session(database):
                assert read_result(fit['result_id'])['result_id'] == fit['result_id']
                reopened_support = read_result(saved_support['result_id'])
                assert reopened_support == saved_support
        finally:
            database.close()
    print('SUPPORT_AUDIT_OK ' + json.dumps({
        'stationary_points': case['stationary_tau'],
        'components': support['components'],
        'checks': ['closed_components', 'real_gaps', 'level_endpoints',
                   'interior_moment_containment', 'entrywise_only',
                   'zero_drop_collapse', 'rollback_retry',
                   'correction_immutability', 'reopen_read']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
