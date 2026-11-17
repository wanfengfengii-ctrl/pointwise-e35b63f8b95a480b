import json
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from batch_analysis.likelihood import FitState, LikelihoodProblem
from cohorts.snapshot import snapshot_to_record, snapshot_from_record
from cohorts.provenance import summarize_provenance


class FitPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class FitPayload:
    state: FitState
    provenance: dict


def _decimal(value):
    number = Decimal(value)
    if not number.is_finite():
        raise FitPayloadError('nonfinite fit payload')
    return number


def encode_fit(state):
    problem = state.problem
    record = {
        'version': 1, 'snapshot': snapshot_to_record(problem.cohort),
        'provenance': summarize_provenance(problem.cohort.rows),
        'batches': list(problem.batches),
        'precisions': [str(x) for x in problem.precisions],
        'batch_means': [str(x) for x in problem.batch_means], 'within': str(problem.within),
        'tau': str(state.tau), 'log_likelihood': str(state.log_likelihood),
        'mean': str(state.mean), 'precision': str(state.precision),
        'inverse_one': [str(x) for x in state.inverse_one],
        'inverse_residual': [str(x) for x in state.inverse_residual],
    }
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    decode_fit(payload)
    return payload


def decode_fit(payload):
    try:
        record = json.loads(payload)
        if record['version'] != 1:
            raise FitPayloadError('unsupported fit payload')
        cohort = snapshot_from_record(record['snapshot'])
        if record['provenance'] != summarize_provenance(cohort.rows):
            raise FitPayloadError('fit provenance mismatch')
        batches = tuple(record['batches'])
        weights = tuple(Fraction(x) for x in record['precisions'])
        means = tuple(Fraction(x) for x in record['batch_means'])
        if batches != cohort.batches or len(weights) != len(batches) or len(means) != len(batches):
            raise FitPayloadError('fit batch dimensions disagree')
        if any(x <= 0 for x in weights) or Fraction(record['within']) < 0:
            raise FitPayloadError('invalid sufficient statistics')
        problem = LikelihoodProblem(cohort, batches, weights, means, Fraction(record['within']))
        state = FitState(problem, *[_decimal(record[name]) for name in
                                    ('tau', 'log_likelihood', 'mean', 'precision')],
                         tuple(_decimal(x) for x in record['inverse_one']),
                         tuple(_decimal(x) for x in record['inverse_residual']))
        if state.tau < 0 or state.precision <= 0:
            raise FitPayloadError('invalid fitted variance or precision')
        if any(len(vector) != len(cohort.rows) for vector in
               (state.inverse_one, state.inverse_residual)):
            raise FitPayloadError('fit observation dimensions disagree')
        return FitPayload(state, record['provenance'])
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise FitPayloadError('invalid frozen fit payload') from exc


def copy_fit_result(payload):
    with localcontext() as context:
        context.prec = 80
        fit = decode_fit(payload)
        state = fit.state
        return {'kind': 'fit', 'cohort_id': state.problem.cohort.cohort_id,
                'tau': float(state.tau), 'log_likelihood': float(state.log_likelihood),
                'mean': float(state.mean), 'mean_variance': float(1 / state.precision),
                'snapshot': snapshot_to_record(state.problem.cohort), 'provenance': fit.provenance}
