from decimal import Decimal, localcontext
from batch_analysis.likelihood import build_likelihood_problem, evaluate_fit_state
from batch_analysis.stationary import enumerate_stationary_candidates
from batch_analysis.matrices import NumericalError


class FitDomainError(ValueError):
    pass


def validate_fit_domain(cohort):
    if not 2 <= len(cohort.batches) <= 6 or not 2 <= len(cohort.rows) <= 24:
        raise FitDomainError('fit requires 2..6 batches and at most 24 rows')


def _choose_best(states):
    with localcontext() as context:
        context.prec = 80
        ordered = sorted(states, key=lambda state: state.tau)
        best = ordered[0]
        for state in ordered[1:]:
            if state.log_likelihood > best.log_likelihood + Decimal('1e-60'):
                best = state
        return best


def select_global_fit(problem, candidates=None):
    roots = enumerate_stationary_candidates(problem) if candidates is None else candidates
    points = sorted({Decimal(0)} | {root.tau for root in roots})
    states = [evaluate_fit_state(problem, point) for point in points]
    with localcontext() as context:
        context.prec = 80
        best = _choose_best(states)
        if abs(Decimal(str(float(best.tau))) - best.tau) > Decimal('1e-7'):
            raise NumericalError('public variance cannot retain required absolute precision')
        if abs(Decimal(str(float(best.log_likelihood))) - best.log_likelihood) > Decimal('1e-8'):
            raise NumericalError('public objective cannot retain required absolute precision')
    return best


def fit_frozen_cohort(cohort):
    validate_fit_domain(cohort)
    return select_global_fit(build_likelihood_problem(cohort))
