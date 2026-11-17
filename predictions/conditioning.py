from dataclasses import dataclass
from decimal import Decimal, localcontext
from batch_analysis.likelihood import observation_covariance
from batch_analysis.matrices import cholesky, solve_cholesky, dot


@dataclass(frozen=True)
class ConditioningState:
    plan: object
    means: tuple
    cross: tuple
    solved_cross: tuple
    mean_loadings: tuple
    precision: Decimal
    tau: Decimal


def build_observation_cross_covariance(fit, plan):
    return tuple(tuple(fit.tau if request.existing and request.batch_id == row.batch_id
                       else Decimal(0) for row in fit.problem.cohort.rows)
                 for request in plan.unique)


def condition_batch_levels(fit, plan):
    with localcontext() as context:
        context.prec = 80
        cross = build_observation_cross_covariance(fit, plan)
        lower = cholesky(observation_covariance(fit.problem, fit.tau))
        solved = tuple(tuple(solve_cholesky(lower, row)) for row in cross)
        means = tuple(fit.mean + dot(row, fit.inverse_residual) for row in cross)
        loadings = tuple(1 - dot(row, fit.inverse_one) for row in cross)
        return ConditioningState(plan, means, cross, solved, loadings, fit.precision, fit.tau)
