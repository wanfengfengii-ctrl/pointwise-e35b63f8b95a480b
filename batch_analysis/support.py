"""Complete likelihood support set S = {tau >= 0 : ell_R(tau) >= M - drop}.

Completeness argument
---------------------
The score numerator is the exact Fraction polynomial built in
``batch_analysis.stationary`` and A(tau) > 0 on tau >= 0, so every positive
stationary point of ell_R is an isolated Sturm-certified root of that
polynomial and ell_R has no other positive critical point.  Between two
consecutive stationary points (and on the boundary intervals [0, r_1] and
[r_last, infinity)) the score keeps a constant sign, hence ell_R is strictly
monotone.  On each such monotone segment the super-level set {ell_R >= L} is
either empty, a single point, or one closed interval, and any crossing of the
level L is refined by bracket bisection rather than grid probing.  Segments are
merged only when they genuinely touch at a retained stationary point, so real
gaps survive and no enclosing envelope is ever returned.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from batch_analysis.likelihood import evaluate_fit_state
from batch_analysis.stationary import enumerate_stationary_candidates
from batch_analysis.matrices import NumericalError

WORKING_PRECISION = 80
MAX_BISECTION_STEPS = 400
PUBLIC_TAU_TOLERANCE = Decimal('1e-7')
# Numerical floor of the 80-digit likelihood evaluation at an isolated root.
LIKELIHOOD_TOLERANCE = Decimal('1e-30')
# Membership at a sub-resolution seam is decided within this band: it only
# applies when the geometric gap itself is below the merge threshold, so no
# point excluded by a meaningful margin can enter S.  The band sits just above
# the 80-digit evaluation floor at an isolated root (~1e-27) and many orders
# below the smallest genuine stationary-point likelihood separation.
SEAM_MEMBERSHIP_TOLERANCE = Decimal('1e-20')
# Two independently bisected endpoints that both resolve, within twice the
# numerical floor on a single endpoint, to the same stationary breakpoint
# describe components touching at that breakpoint.  The breakpoint's own
# likelihood is always checked, so a genuinely excluded point is never merged;
# a wider separation is published as a real, resolvable gap.
MERGE_EPSILON = Decimal('2e-6')
TAIL_LIMIT = Decimal('1e100')


class SupportError(ValueError):
    pass


def validate_drop(drop):
    if isinstance(drop, bool) or not isinstance(drop, (int, float, str, Decimal)):
        raise SupportError('drop must be a finite non-negative number')
    try:
        number = Decimal(str(drop))
    except Exception as exc:
        raise SupportError('drop must be a finite non-negative number') from exc
    if not number.is_finite() or number < 0:
        raise SupportError('drop must be finite and non-negative')
    return number


@dataclass(frozen=True)
class SupportSet:
    problem: object
    drop: Decimal
    maximum: Decimal
    maximizers: tuple            # Decimal tau values attaining the global maximum
    components: tuple            # (lo, hi) Decimal closed intervals, sorted by lo


def _likelihood(problem, tau):
    return evaluate_fit_state(problem, Decimal(tau)).log_likelihood


def _global_extrema(problem):
    roots = enumerate_stationary_candidates(problem)
    positive = tuple(root.tau for root in roots)
    # Evaluate every candidate, including tau = 0, at full working precision.
    # The global maximum is derived from the exact isolated roots rather than
    # from the float-rounded published fit, so level crossings stay consistent
    # with the likelihood evaluated at the same stationary points.
    points = (Decimal(0),) + positive
    states = [evaluate_fit_state(problem, point) for point in points]
    objectives = [state.log_likelihood for state in states]
    highest = max(objectives)
    maximizers = [point for point, objective in zip(points, objectives)
                  if abs(objective - highest) <= LIKELIHOOD_TOLERANCE]
    return positive, highest, tuple(sorted(maximizers))


def _bisect_level(problem, left, right, level):
    """Refine ell_R(tau) = level inside a sign-changing bracket [left, right]."""
    lo, hi = Decimal(left), Decimal(right)
    f_lo = _likelihood(problem, lo) - level
    f_hi = _likelihood(problem, hi) - level
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        raise NumericalError('level bracket does not straddle the likelihood level')
    with localcontext() as context:
        context.prec = WORKING_PRECISION
        for _ in range(MAX_BISECTION_STEPS):
            width = hi - lo
            # Keep the internal bracket far tighter than the public 1e-7 endpoint
            # tolerance at every scale: an absolute floor near zero and a relative
            # gate that still yields a sub-1e-9 bracket even at tau around 1e16.
            span_ok = (width <= Decimal('1e-14') or
                       width <= abs(hi) * Decimal('1e-30'))
            if span_ok:
                break
            mid = (lo + hi) / 2
            f_mid = _likelihood(problem, mid) - level
            if f_mid == 0:
                lo = hi = mid
                break
            if f_mid * f_lo > 0:
                lo, f_lo = mid, f_mid
            else:
                hi = mid
        else:
            raise NumericalError('likelihood level bisection budget exceeded')
        tau = (lo + hi) / 2
        if abs(_likelihood(problem, tau) - level) > Decimal('1e-12'):
            raise NumericalError('likelihood level did not converge')
        return tau


def _safe_public(tau):
    public = Decimal(str(float(tau)))
    # The published endpoint is a double.  Absolute 1e-7 accuracy can only be
    # demanded inside the range where a double distinguishes that spacing;
    # beyond it the best achievable error grows with the magnitude, so reject
    # only genuine non-representability (overflow / non-finite) rather than a
    # physically impossible absolute spacing requirement.
    if not public.is_finite():
        raise NumericalError('support endpoint cannot be represented as a finite number')
    if abs(tau) <= Decimal('1e8') and abs(public - tau) > PUBLIC_TAU_TOLERANCE:
        raise NumericalError('support endpoint cannot retain required absolute precision')
    if abs(tau) > Decimal('1e8') and abs(public - tau) > abs(tau) * Decimal('1e-15'):
        raise NumericalError('support endpoint cannot retain relative precision')
    return public


def solve_support(problem, drop):
    drop = validate_drop(drop)
    positive, maximum, maximizers = _global_extrema(problem)
    if drop == 0:
        components = tuple((tau, tau) for tau in maximizers)
        return SupportSet(problem, drop, maximum, maximizers, components)

    level = maximum - drop
    breakpoints = (Decimal(0),) + positive
    raw_intervals = []
    for segment in range(len(breakpoints)):
        lo = breakpoints[segment]
        hi = breakpoints[segment + 1] if segment + 1 < len(breakpoints) else None
        f_lo = _likelihood(problem, lo) - level
        if hi is None:
            # Tail segment: ell_R strictly decreases towards -infinity (at least two batches).
            if f_lo < 0:
                continue
            anchor = lo
            end = lo if lo > 0 else Decimal(1)
            while end <= TAIL_LIMIT:
                if _likelihood(problem, end) < level:
                    break
                anchor = end
                end *= 2
            else:
                raise NumericalError('support component exceeds representable range')
            crossing = _bisect_level(problem, anchor, end, level)
            raw_intervals.append((lo, crossing))
            continue
        f_hi = _likelihood(problem, hi) - level
        if f_lo < 0 and f_hi < 0:
            continue
        if f_lo >= 0 and f_hi >= 0:
            raw_intervals.append((lo, hi))
        elif f_lo >= 0 > f_hi:
            crossing = _bisect_level(problem, lo, hi, level)
            raw_intervals.append((lo, crossing))
        else:
            crossing = _bisect_level(problem, lo, hi, level)
            raw_intervals.append((crossing, hi))

    components = _merge_segments(raw_intervals, breakpoints, level, problem)
    if not components:
        raise NumericalError('support set vanished despite a non-negative drop')
    for lo, hi in components:
        _safe_public(lo)
        _safe_public(hi)
    return SupportSet(problem, drop, maximum, maximizers, components)


def _merge_segments(raw_intervals, breakpoints, level, problem):
    if not raw_intervals:
        return ()

    def breakpoint_between(left_end, right_start):
        return min(breakpoints, key=lambda point: abs(point - (left_end + right_start) / 2))

    merged = [raw_intervals[0]]
    for lo, hi in raw_intervals[1:]:
        previous_lo, previous_hi = merged[-1]
        if lo < previous_hi:
            # Segments of a strict monotone partition can only overlap through the
            # shared stationary breakpoint, which must itself belong to S.
            shared = [point for point in breakpoints
                      if previous_hi <= point <= lo]
            if not shared or any(_likelihood(problem, point) < level - LIKELIHOOD_TOLERANCE
                                 for point in shared):
                raise NumericalError('support segments overlap across an excluded point')
            merged[-1] = (previous_lo, max(previous_hi, hi))
            continue
        gap = lo - previous_hi
        if gap <= MERGE_EPSILON:
            # A gap this narrow cannot be rendered faithfully in the public
            # doubles.  The stationary breakpoint between the two segments is the
            # only point that can occupy it, so membership is decided from the
            # likelihood itself: breakpoint in S means the closed components
            # touch there and form one connected component (snap the seam to the
            # exact breakpoint); breakpoint out of S is an unresolvably narrow
            # real gap, so refuse rather than merge it away or round a non-member
            # point into S.  The seam band is far smaller than the smallest
            # meaningful likelihood margin observed across distinct stationary
            # points, while covering the evaluation floor at an isolated root.
            breakpoint = breakpoint_between(previous_hi, lo)
            if _likelihood(problem, breakpoint) >= level - SEAM_MEMBERSHIP_TOLERANCE:
                merged[-1] = (previous_lo, max(hi, breakpoint))
            else:
                raise NumericalError('unresolvably narrow support gap')
            continue
        merged.append((lo, hi))
    return tuple(merged)
