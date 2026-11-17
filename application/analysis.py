import argparse
import json
import sys
from pathlib import Path
from results.database import Database, database_session, current_database
from cohorts.repository import CohortRepository
from batch_analysis.selection import fit_frozen_cohort
from predictions.joint import predict_joint_levels
from results.fit_codec import encode_fit, decode_fit, FitPayloadError
from results.prediction_codec import encode_prediction
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.results import read_result


def fit_batch(cohort_id):
    database = current_database()
    snapshot = CohortRepository(database).read(cohort_id)
    state = fit_frozen_cohort(snapshot)
    payload = encode_fit(state)
    identity = database.publish_fit(cohort_id, payload)
    return read_result(identity)


def predict_batches(fit_id, requests):
    database = current_database()
    stored = database.read_published(fit_id)
    if stored['kind'] != 'fit':
        raise FitPayloadError('prediction requires fit_id')
    fit = decode_fit(stored['payload']).state
    if fit.problem.cohort.cohort_id != stored['cohort_id']:
        raise FitPayloadError('frozen fit binding mismatch')
    prediction = predict_joint_levels(fit, requests)
    identity = database.publish_prediction(fit_id, encode_prediction(fit_id, prediction))
    return read_result(identity)


def run_day_demo(path, sample_path):
    if Path(path).exists():
        raise ValueError('demo requires a new database path')
    sample = json.loads(Path(sample_path).read_text(encoding='utf-8'))
    database = Database(path)
    try:
        with database_session(database):
            apply_measurements(sample)
            cohort = freeze_cohort([row['measurement_id'] for row in sample])
            fit = fit_batch(cohort['cohort_id'])
            prediction = predict_batches(fit['result_id'], [
                {'batch_id': 'new-X', 'existing': False},
                {'batch_id': 'new-X', 'existing': False},
                {'batch_id': 'new-Y', 'existing': False},
                {'batch_id': 'A', 'existing': True}])
            assert abs(fit['tau'] - 8.5) < 1e-7
            assert abs(prediction['covariance'][0][1] - 11.5) < 1e-8
            assert abs(prediction['covariance'][0][2] - 3) < 1e-8
            corrected = dict(sample[0], revision=2, value=99)
            apply_measurements([corrected])
    finally:
        database.close()
    reopened = Database(path)
    try:
        with database_session(reopened):
            old_fit = read_result(fit['result_id'])
            old_prediction = read_result(prediction['result_id'])
            assert old_fit == fit and old_prediction == prediction
            print('POINTWISE_SCENARIO ' + json.dumps({
                'case_id': 'V8', 'input': sample,
                'expected': {'tau': 8.5, 'mean': 4.5},
                'actual': {'tau': old_fit['tau'], 'mean': old_fit['mean']},
                'downstream_expected': {'same_new_covariance': 11.5, 'distinct_new_covariance': 3},
                'downstream_actual': {'same_new_covariance': old_prediction['covariance'][0][1],
                                      'distinct_new_covariance': old_prediction['covariance'][0][2]},
                'code_paths': ['application/analysis.py', 'batch_analysis/likelihood.py',
                               'batch_analysis/selection.py', 'predictions/identities.py',
                               'predictions/joint.py', 'application/results.py'],
                'oracle': 'balanced three-batch hand calculation; stored result equality after correction/reopen'
            }, ensure_ascii=False))
            return {'fit': old_fit, 'prediction': old_prediction}
    finally:
        reopened.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Chengchuan repeated-measurement analysis')
    parser.add_argument('--db', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo')
    demo.add_argument('--sample', default='sample_day.json')
    apply = commands.add_parser('apply')
    apply.add_argument('input')
    freeze = commands.add_parser('freeze')
    freeze.add_argument('input')
    fit = commands.add_parser('fit')
    fit.add_argument('cohort_id')
    predict = commands.add_parser('predict')
    predict.add_argument('fit_id')
    predict.add_argument('input')
    read = commands.add_parser('read')
    read.add_argument('result_id')
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == 'demo':
            result = run_day_demo(arguments.db, arguments.sample)
        else:
            database = Database(arguments.db)
            try:
                with database_session(database):
                    if arguments.command in ('apply', 'freeze', 'predict'):
                        data = json.loads(Path(arguments.input).read_text(encoding='utf-8'))
                    if arguments.command == 'apply':
                        result = apply_measurements(data)
                    elif arguments.command == 'freeze':
                        result = freeze_cohort(data)
                    elif arguments.command == 'fit':
                        result = fit_batch(arguments.cohort_id)
                    elif arguments.command == 'predict':
                        result = predict_batches(arguments.fit_id, data)
                    else:
                        result = read_result(arguments.result_id)
            finally:
                database.close()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, ArithmeticError, RuntimeError, LookupError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
