"""Per-entry moment ranges over a fixed likelihood support set.

For every conditional mean entry and every full covariance entry the exact
rational function of tau (see ``batch_analysis.rational_moments``) is evaluated
on the SAME published support S.  Each entry is smooth with a strictly positive
denominator on tau >= 0, so its extrema on a closed component can only occur at
a component endpoint or at a non-negative root of its exact derivative
numerator.  Sturm isolation enumerates those interior roots completely; no
grid, sampling or endpoint-only trial takes the place of the enumeration.

The ranges are entrywise: minima and maxima of different entries are never
combined into a claim about one jointly attainable distribution.  Every entry
is additionally cross-checked at every candidate tau against the unchanged V1
conditioning computation before a result is published.
"""
from dataclasses import dataclass
from decimal import Decimal
from batch_analysis.likelihood import evaluate_fit_state
from batch_analysis.rational_moments import (
    build_moment_model, evaluate_rational, collect_interior_stationary,
)
from batch_analysis.matrices import NumericalError
from predictions.identities import resolve_batch_identities
from predictions.joint import predict_joint_levels
from predictions.requests import PredictionRequestError

MAX_REQUESTS = 8
PUBLIC_MOMENT_TOLERANCE = Decimal('1e-8')


@dataclass(frozen=True)
class SupportPrediction:
    support_id: str
    fit_id: str
    requests: tuple
    mean_ranges: tuple
    covariance_ranges: tuple


def _candidate_taus(components, model):
    candidates = {Decimal(0)}
    for lo, hi in components:
        candidates.add(Decimal(lo))
        candidates.add(Decimal(hi))
    for tau in collect_interior_stationary(model, components):
        candidates.add(Decimal(tau))
    inside = []
    for tau in sorted(candidates):
        if any(lo <= tau <= hi for lo, hi in components):
            inside.append(tau)
    if not inside:
        raise NumericalError('no evaluation points lie on the support set')
    return tuple(inside)


def _v1_point_prediction(problem, tau, plan):
    state = evaluate_fit_state(problem, tau)
    return predict_joint_levels(state, plan.requests)


def _agrees(left, right):
    # Both paths evaluate the same moment at one tau.  Absolute 1e-8 agreement
    # is required at normal magnitudes; for entries whose magnitude itself
    # exceeds the range where a double resolves 1e-8 spacing, agreement is
    # demanded to tight relative precision, matching the publication gate.
    magnitude = max(abs(left), abs(right), Decimal(1))
    if magnitude <= Decimal('1e8'):
        return abs(left - right) <= Decimal('1e-12')
    return abs(left - right) <= magnitude * Decimal('1e-20')


def _public_value(value):
    public = Decimal(str(float(value)))
    if not public.is_finite():
        raise NumericalError('moment range endpoint cannot be represented finitely')
    if abs(value) <= Decimal('1e8'):
        if abs(public - value) > PUBLIC_MOMENT_TOLERANCE:
            raise NumericalError('moment range endpoint cannot retain required precision')
    elif abs(public - value) > abs(value) * Decimal('1e-15'):
        raise NumericalError('moment range endpoint cannot retain relative precision')
    return public


def compute_support_ranges(fit, fit_id, support_id, components, requests):
    plan = resolve_batch_identities(fit, requests)
    if len(plan.requests) > MAX_REQUESTS:
        raise PredictionRequestError('at most eight ordered requests are supported')
    problem = fit.problem
    model = build_moment_model(problem, plan)
    candidates = _candidate_taus(components, model)
    size = len(plan.requests)

    mean_values = [[] for _ in range(size)]
    covariance_values = [[[] for _ in range(size)] for _ in range(size)]
    for tau in candidates:
        for i in range(size):
            mean_values[i].append(evaluate_rational(model.mean_entries[i], tau))
        for i in range(size):
            for j in range(size):
                covariance_values[i][j].append(
                    evaluate_rational(model.covariance_entries[i][j], tau))
        # Independent cross-check against the unchanged V1 conditioning path.
        point = _v1_point_prediction(problem, tau, plan)
        for i in range(size):
            if not _agrees(point.means[i], mean_values[i][-1]):
                raise NumericalError('support mean disagrees with point conditioning')
        for i in range(size):
            for j in range(size):
                if not _agrees(point.covariance[i][j], covariance_values[i][j][-1]):
                    raise NumericalError('support covariance disagrees with point conditioning')

    mean_ranges = tuple(
        (_public_value(min(values)), _public_value(max(values)))
        for values in mean_values)
    covariance_ranges = tuple(
        tuple((_public_value(min(covariance_values[i][j])),
               _public_value(max(covariance_values[i][j])))
              for j in range(size))
        for i in range(size))
    return SupportPrediction(support_id, fit_id, plan.requests,
                             mean_ranges, covariance_ranges)
