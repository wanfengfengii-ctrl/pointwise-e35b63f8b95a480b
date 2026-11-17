"""Exact rational-function machinery for moment ranges over a variance support.

Every conditional mean / covariance entry of the original latent Gaussian model
is a rational function R(tau) = P(tau) / Q(tau) on tau >= 0 whose coefficients
are exact Fractions derived from the frozen sufficient statistics.  All
denominators are products of (tau + d_b) with d_b = 1/w_b > 0, hence strictly
positive on the fitted domain and free of non-negative singularities.

With V_b = D_b + tau 1 1^T the per-batch block of the observation covariance,
the Woodbury identities give, writing G_c(tau) = Prod_{j != c}(tau + d_j) and
Q(tau) = Prod_j (tau + d_j):

    s(tau) = 1^T V^-1 1 = sum_c 1/(tau + d_c),          Q s  = sum_c G_c = S
    1^T V_c^-1 y_c = m_c / (tau + d_c),                 Q t  = sum_c m_c G_c = T
    mu_hat = T / S
    kappa_c = tau / (tau + d_c) = tau G_c / Q
    a_c = 1 - kappa_c
    B V^-1 B^T (c, c) = tau^2 / (tau + d_c) = tau^2 G_c / Q
    B V^-1 B^T (c, e) = 0 for c != e, and zero for new batches

Interior extrema of an entry therefore coincide with the non-negative roots of
the exact numerator polynomial of P'Q - PQ'.  Those roots are isolated with the
same Sturm-count construction used for the score polynomial, so the extrema
catalogue is complete without grid or endpoint trial searches.
"""
from dataclasses import dataclass
from fractions import Fraction
from batch_analysis.stationary import (
    _trim, _add, _scale, _multiply, _derivative,
    isolate_positive_roots,
)
from batch_analysis.matrices import NumericalError

TAU_POLYNOMIAL = (Fraction(0), Fraction(1))


@dataclass(frozen=True)
class RationalFunction:
    numerator: tuple
    denominator: tuple

    def __post_init__(self):
        object.__setattr__(self, 'numerator', _trim(self.numerator))
        object.__setattr__(self, 'denominator', _trim(self.denominator))
        if self.denominator == (Fraction(0),):
            raise NumericalError('rational function has zero denominator polynomial')

    def derivative_numerator(self):
        # Numerator of d/dtau(P/Q): P'Q - P Q'; the positive denominator Q**2 is irrelevant.
        return _trim(_add(_multiply(_derivative(self.numerator), self.denominator),
                          _scale(_multiply(self.numerator, _derivative(self.denominator)),
                                 Fraction(-1))))

    def stationary_points(self):
        """Certified non-negative stationary points of this rational function."""
        numerator = self.derivative_numerator()
        if numerator == (Fraction(0),):
            return ()
        return tuple(root.tau for root in isolate_positive_roots(numerator))


def constant_rational(value):
    value = Fraction(value)
    return RationalFunction((value,), (Fraction(1),))


@dataclass(frozen=True)
class MomentModel:
    requests: tuple
    positions: tuple
    unique: tuple
    mean_entries: tuple           # one RationalFunction per request
    covariance_entries: tuple     # q x q RationalFunctions


def _product_polynomial(factors):
    result = (Fraction(1),)
    for factor in factors:
        result = _multiply(result, factor)
    return _trim(result)


def _batch_poly(d, index):
    # G_index(tau) = product of the (tau + d_j) factors of every other batch.
    factors = [(d[j], Fraction(1)) for j in range(len(d)) if j != index]
    return _product_polynomial(factors)


def _add_rational(left, right):
    return RationalFunction(
        _add(_multiply(left.numerator, right.denominator),
             _multiply(right.numerator, left.denominator)),
        _multiply(left.denominator, right.denominator))


def _scale_rational(function, scalar):
    return RationalFunction(_scale(function.numerator, Fraction(scalar)), function.denominator)


def _mul_rational(left, right):
    return RationalFunction(_multiply(left.numerator, right.numerator),
                            _multiply(left.denominator, right.denominator))


def build_moment_model(problem, plan):
    """Construct exact rational mean/covariance functions for an ordered request plan."""
    d = tuple(Fraction(1) / weight for weight in problem.precisions)
    batches = problem.batches
    index_of = {batch: b for b, batch in enumerate(batches)}
    k = len(batches)

    q_poly = _product_polynomial([(d[b], Fraction(1)) for b in range(k)])
    g_polys = [_batch_poly(d, c) for c in range(k)]
    s_poly = (Fraction(0),)
    t_poly = (Fraction(0),)
    for c in range(k):
        s_poly = _add(s_poly, g_polys[c])
        t_poly = _add(t_poly, _scale(g_polys[c], problem.batch_means[c]))
    s_poly, t_poly = _trim(s_poly), _trim(t_poly)
    mu = RationalFunction(t_poly, s_poly)

    # Per unique request identity: mean and a(tau) rational functions.
    unique_means, unique_a, unique_existing = [], [], []
    for request in plan.unique:
        if request.existing:
            c = index_of[request.batch_id]
            # kappa_c = tau G_c / Q ; mean_c = mu + kappa_c (m_c - mu); a_c = 1 - kappa_c
            kappa = RationalFunction(_multiply(TAU_POLYNOMIAL, g_polys[c]), q_poly)
            mc = problem.batch_means[c]
            mean_c = _add_rational(
                mu, _mul_rational(kappa, _add_rational(
                    constant_rational(mc), _scale_rational(mu, Fraction(-1)))))
            unique_means.append(mean_c)
            unique_a.append(_add_rational(constant_rational(1),
                                          _scale_rational(kappa, Fraction(-1))))
            unique_existing.append(c)
        else:
            unique_means.append(mu)
            unique_a.append(constant_rational(1))
            unique_existing.append(None)

    tau_rational = RationalFunction(TAU_POLYNOMIAL, (Fraction(1),))
    size = len(plan.unique)
    unique_cov = [[None] * size for _ in range(size)]
    for u in range(size):
        for v in range(u, size):
            same = plan.unique[u].batch_id == plan.unique[v].batch_id
            term_k = tau_rational if same else constant_rational(0)
            cu, cv = unique_existing[u], unique_existing[v]
            if cu is not None and cv is not None and cu == cv:
                # tau^2 G_c / Q
                btb = RationalFunction(
                    _multiply(_multiply(TAU_POLYNOMIAL, TAU_POLYNOMIAL), g_polys[cu]), q_poly)
            else:
                btb = constant_rational(0)
            # a_u a_v / s = a_u a_v Q / S
            aa_over_s = _mul_rational(
                _mul_rational(unique_a[u], unique_a[v]),
                RationalFunction(q_poly, s_poly))
            entry = _add_rational(_add_rational(term_k, _scale_rational(btb, Fraction(-1))),
                                  aa_over_s)
            unique_cov[u][v] = entry
            unique_cov[v][u] = entry

    positions = plan.positions
    mean_entries = tuple(unique_means[positions[r]] for r in range(len(plan.requests)))
    covariance_entries = tuple(tuple(unique_cov[positions[r]][positions[c]]
                                     for c in range(len(plan.requests)))
                               for r in range(len(plan.requests)))
    return MomentModel(plan.requests, positions, plan.unique,
                       mean_entries, covariance_entries)


def evaluate_rational(function, tau):
    """Evaluate a rational function at a Decimal tau with 80-digit working precision."""
    from decimal import Decimal, localcontext
    with localcontext() as context:
        context.prec = 80
        x = Decimal(tau)

        def value_of(polynomial):
            total = Decimal(0)
            for coefficient in reversed(polynomial):
                total = (total * x +
                         Decimal(coefficient.numerator) / Decimal(coefficient.denominator))
            return total

        numerator = value_of(function.numerator)
        denominator = value_of(function.denominator)
        if not denominator.is_finite() or denominator <= 0:
            raise NumericalError('moment denominator lost positivity')
        value = numerator / denominator
        if not value.is_finite():
            raise NumericalError('nonfinite moment evaluation')
        return value


def collect_interior_stationary(model, components):
    """All certified interior stationary tau values of every moment entry, in one sorted set."""
    points = set()
    functions = list(model.mean_entries) + [entry for row in model.covariance_entries
                                            for entry in row]
    for function in functions:
        for tau in function.stationary_points():
            for lo, hi in components:
                if lo < tau < hi:
                    points.add(tau)
                    break
    return sorted(points)
