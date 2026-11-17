from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from batch_analysis.matrices import cholesky, solve_cholesky, log_determinant, dot, NumericalError

LOG_TWO_PI = Decimal('1.8378770664093454835606594728112352797227949472755668256343030809655313918545208')


@dataclass(frozen=True)
class LikelihoodProblem:
    cohort: object
    batches: tuple
    precisions: tuple
    batch_means: tuple
    within: Fraction


@dataclass(frozen=True)
class FitState:
    problem: LikelihoodProblem
    tau: Decimal
    log_likelihood: Decimal
    mean: Decimal
    precision: Decimal
    inverse_one: tuple
    inverse_residual: tuple


def build_likelihood_problem(cohort):
    weights, totals = {}, {}
    for row in cohort.rows:
        weight, value = 1 / Fraction(row.variance), Fraction(row.value)
        weights[row.batch_id] = weights.get(row.batch_id, Fraction(0)) + weight
        totals[row.batch_id] = totals.get(row.batch_id, Fraction(0)) + weight * value
    batches = tuple(weights)
    means = {batch: totals[batch] / weights[batch] for batch in batches}
    within = sum(((Fraction(row.value) - means[row.batch_id]) ** 2 / Fraction(row.variance)
                  for row in cohort.rows), Fraction(0))
    return LikelihoodProblem(cohort, batches, tuple(weights[b] for b in batches),
                             tuple(means[b] for b in batches), within)


def observation_covariance(problem, tau):
    tau = Decimal(tau)
    if not tau.is_finite() or tau < 0:
        raise NumericalError('invalid batch variance')
    rows = problem.cohort.rows
    return [[(Decimal(rows[i].variance) if i == j else Decimal(0)) +
             (tau if rows[i].batch_id == rows[j].batch_id else Decimal(0))
             for j in range(len(rows))] for i in range(len(rows))]


def evaluate_fit_state(problem, tau):
    with localcontext() as context:
        context.prec = 80
        tau = Decimal(tau)
        lower = cholesky(observation_covariance(problem, tau))
        values = [Decimal(row.value) for row in problem.cohort.rows]
        one = [Decimal(1)] * len(values)
        inverse_one = solve_cholesky(lower, one)
        precision = sum(inverse_one)
        origin = values[0]
        centered = [value - origin for value in values]
        inverse_centered = solve_cholesky(lower, centered)
        delta = sum(inverse_centered) / precision
        mean = origin + delta
        residual = [value - delta for value in centered]
        inverse_residual = solve_cholesky(lower, residual)
        objective = -((len(values) - 1) * LOG_TWO_PI + log_determinant(lower) +
                      precision.ln() + dot(residual, inverse_residual)) / 2
        state = FitState(problem, tau, objective, mean, precision,
                         tuple(inverse_one), tuple(inverse_residual))
        if precision <= 0 or any(not x.is_finite() for x in
                                 (tau, objective, mean, precision)):
            raise NumericalError('invalid likelihood state')
        return state


def restricted_log_likelihood(problem, tau):
    return evaluate_fit_state(problem, tau).log_likelihood


def restricted_score(problem, tau):
    from batch_analysis.stationary import build_score_polynomial, polynomial_value
    polynomial = build_score_polynomial(problem)
    x = Fraction(str(tau))
    with localcontext() as context:
        context.prec = 80
        d = [1 / weight for weight in problem.precisions]
        a = sum((1 / (x + variance) for variance in d), Fraction(0))
        product = Fraction(1)
        for variance in d:
            product *= x + variance
        denominator = 2 * (a * product) ** 2
        value = -polynomial_value(polynomial, x) / denominator
        return Decimal(value.numerator) / Decimal(value.denominator)
