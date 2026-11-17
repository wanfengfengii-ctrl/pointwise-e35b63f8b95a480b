from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from batch_analysis.matrices import NumericalError


def _trim(p):
    p = list(p)
    while len(p) > 1 and p[-1] == 0:
        p.pop()
    return tuple(p or [Fraction(0)])


def _add(p, q):
    return _trim([(p[i] if i < len(p) else 0) + (q[i] if i < len(q) else 0)
                  for i in range(max(len(p), len(q)))])


def _scale(p, scalar):
    return _trim([coefficient * scalar for coefficient in p])


def _multiply(p, q):
    result = [Fraction(0)] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            result[i + j] += a * b
    return _trim(result)


def _derivative(p):
    return _trim([i * p[i] for i in range(1, len(p))])


def _divide(p, q):
    p = list(_trim(p))
    q = _trim(q)
    if q == (0,):
        raise NumericalError('zero polynomial divisor')
    quotient = [Fraction(0)] * max(1, len(p) - len(q) + 1)
    while len(p) >= len(q) and _trim(p) != (0,):
        degree = len(p) - len(q)
        factor = p[-1] / q[-1]
        quotient[degree] = factor
        for i, value in enumerate(q):
            p[degree + i] -= factor * value
        p = list(_trim(p))
    return _trim(quotient), _trim(p)


def polynomial_value(p, x):
    result = Fraction(0)
    for coefficient in reversed(p):
        result = result * x + coefficient
    return result


def _product(factors):
    result = (Fraction(1),)
    for factor in factors:
        result = _multiply(result, factor)
    return result


def build_score_polynomial(problem):
    factors = [(1 / weight, Fraction(1)) for weight in problem.precisions]
    a, numerator = (Fraction(0),), (Fraction(0),)
    count = len(factors)
    for b in range(count):
        a = _add(a, _product([factors[i] for i in range(count) if i != b]))
        for c in range(b):
            difference = (problem.batch_means[b] - problem.batch_means[c]) ** 2
            term = _product([factors[i] for i in range(count) if i not in (b, c)])
            numerator = _add(numerator, _scale(term, difference))
    derivative = _derivative(a)
    return _add(_multiply(derivative, a),
                _add(_multiply(_derivative(numerator), a),
                     _scale(_multiply(numerator, derivative), -1)))


def _square_free(p):
    q = _derivative(p)
    a = p
    while q != (0,):
        _, remainder = _divide(a, q)
        a, q = q, remainder
    return _divide(p, a)[0]


def _sturm(p):
    sequence = [p, _derivative(p)]
    while sequence[-1] != (0,):
        _, remainder = _divide(sequence[-2], sequence[-1])
        if remainder == (0,):
            break
        remainder = _scale(remainder, -1)
        sequence.append(_scale(remainder, 1 / abs(remainder[-1])))
    return sequence


def _variations(sequence, x):
    values = [polynomial_value(p, x) for p in sequence]
    signs = [1 if value > 0 else -1 for value in values if value]
    return sum(left != right for left, right in zip(signs, signs[1:]))


@dataclass(frozen=True)
class StationaryCandidate:
    lower: Fraction
    upper: Fraction

    @property
    def tau(self):
        with localcontext() as context:
            context.prec = 80
            middle = (self.lower + self.upper) / 2
            return Decimal(middle.numerator) / Decimal(middle.denominator)


def isolate_positive_roots(polynomial):
    p = _trim(tuple(Fraction(x) for x in polynomial))
    if p == (0,):
        raise NumericalError('identically zero score')
    while len(p) > 1 and p[0] == 0:
        p = p[1:]
    if len(p) == 1:
        return ()
    p = _square_free(p)
    sequence = _sturm(p)
    bound = Fraction(2 + max(abs(value / p[-1]) for value in p[:-1]).__ceil__())
    stack = [(Fraction(0), bound)]
    intervals = []
    tolerance = Fraction(1, 10 ** 24)
    visits = 0
    while stack:
        lo, hi = stack.pop()
        count = _variations(sequence, lo) - _variations(sequence, hi)
        if count == 0:
            continue
        visits += 1
        if visits > 20000:
            raise NumericalError('root isolation budget exceeded')
        if count == 1 and hi - lo <= tolerance:
            intervals.append(StationaryCandidate(lo, hi))
            continue
        mid = (lo + hi) / 2
        stack.extend([(mid, hi), (lo, mid)])
    return tuple(sorted(intervals, key=lambda root: root.lower))


def refine_stationary_points(polynomial, intervals):
    # Isolation already supplies certified absolute-width intervals, including repeated roots.
    for interval in intervals:
        if interval.upper - interval.lower > Fraction(1, 10 ** 24):
            raise NumericalError('unrefined stationary interval')
    return tuple(intervals)


def enumerate_stationary_candidates(problem):
    polynomial = build_score_polynomial(problem)
    return refine_stationary_points(polynomial, isolate_positive_roots(polynomial))
