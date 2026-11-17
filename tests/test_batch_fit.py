import json
import math
import unittest
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from cohorts.snapshot import FrozenRow, FrozenCohort
from batch_analysis.likelihood import build_likelihood_problem, restricted_score
from batch_analysis.selection import fit_frozen_cohort, FitDomainError, select_global_fit, _choose_best
from batch_analysis.stationary import enumerate_stationary_candidates, isolate_positive_roots


def snapshot(values=(1, 2, 4, 5, 7, 8), batches=('A', 'A', 'B', 'B', 'C', 'C'),
             variances=None):
    variances = variances or [1] * len(values)
    return FrozenCohort('test-cohort', tuple(
        FrozenRow('m' + str(i), 1, batch, str(value), str(variance))
        for i, (batch, value, variance) in enumerate(zip(batches, values, variances))))


def independent_reml(cohort, tau):
    # Independent full-matrix Gauss-Jordan inverse and determinant; no production algebra.
    with localcontext() as context:
        context.prec = 70
        size = len(cohort.rows)
        tau = Decimal(str(tau))
        matrix = [[(Decimal(row.variance) if i == j else Decimal(0)) +
                   (tau if row.batch_id == other.batch_id else Decimal(0))
                   for j, other in enumerate(cohort.rows)] for i, row in enumerate(cohort.rows)]
        inverse = [[Decimal(i == j) for j in range(size)] for i in range(size)]
        determinant = Decimal(1)
        for col in range(size):
            pivot = matrix[col][col]
            determinant *= pivot
            matrix[col] = [x / pivot for x in matrix[col]]
            inverse[col] = [x / pivot for x in inverse[col]]
            for i in range(size):
                if i != col:
                    factor = matrix[i][col]
                    matrix[i] = [a - factor * b for a, b in zip(matrix[i], matrix[col])]
                    inverse[i] = [a - factor * b for a, b in zip(inverse[i], inverse[col])]
        precision = sum(sum(row) for row in inverse)
        values = [Decimal(row.value) for row in cohort.rows]
        mean = sum(sum(row[j] * values[j] for j in range(size)) for row in inverse) / precision
        residual = [value - mean for value in values]
        quadratic = sum(residual[i] * inverse[i][j] * residual[j]
                        for i in range(size) for j in range(size))
        log_two_pi = Decimal('1.8378770664093454835606594728112352797227949472755668256343030809655')
        return -((size - 1) * log_two_pi + determinant.ln() + precision.ln() + quadratic) / 2


class TestBatchFit(unittest.TestCase):
    def test_balanced_and_zero_boundary(self):
        cohort = snapshot()
        fit = fit_frozen_cohort(cohort)
        self.assertAlmostEqual(float(fit.tau), 8.5, delta=1e-7)
        self.assertAlmostEqual(float(fit.mean), 4.5, delta=1e-8)
        self.assertAlmostEqual(float(1 / fit.precision), 3, delta=1e-8)
        # Within-batch RSS=1.5; determinant=(1+2*tau)^3; s=6/(1+2*tau).
        expected = -.5 * (5 * math.log(2 * math.pi) + 3 * math.log(18) +
                          math.log(1 / 3) + 1.5 + 2)
        self.assertAlmostEqual(float(fit.log_likelihood), expected, delta=1e-8)
        self.assertLess(abs(fit.log_likelihood - independent_reml(cohort, fit.tau)), Decimal('1e-50'))
        zero = fit_frozen_cohort(snapshot([1] * 6))
        self.assertEqual(zero.tau, 0)
        self.assertAlmostEqual(float(1 / zero.precision), 1 / 6, delta=1e-8)
        self.assertLess(abs(zero.log_likelihood - independent_reml(snapshot([1] * 6), 0)),
                        Decimal('1e-50'))

    def test_global_candidates(self):
        case = json.loads(Path('NUMERICAL_CASES.json').read_text())['multi_stationary']
        cohort = snapshot(case['values'], case['batches'], case['variances'])
        problem = build_likelihood_problem(cohort)
        roots = enumerate_stationary_candidates(problem)
        self.assertEqual(len(roots), 3)
        for root, expected in zip(roots, case['stationary_tau']):
            self.assertAlmostEqual(float(root.tau), expected, delta=1e-10)
            self.assertLess(abs(restricted_score(problem, root.tau)), Decimal('1e-20'))
        candidates = [Decimal(0)] + [root.tau for root in roots]
        objectives = [independent_reml(cohort, tau) for tau in candidates]
        for actual, expected in zip(objectives, case['log_likelihoods']):
            self.assertAlmostEqual(float(actual), expected, delta=1e-10)
        fit = fit_frozen_cohort(cohort)
        self.assertEqual(fit.tau, candidates[1])
        self.assertEqual(max(range(4), key=lambda i: objectives[i]), 1)
        # Independent Decimal score bisection in three disjoint sign-change brackets.
        with localcontext() as context:
            context.prec = 70
            def score(tau):
                w = [1 / (tau + Decimal(str(v))) for v in case['variances']]
                s = sum(w)
                mu = sum(a * Decimal(y) for a, y in zip(w, case['values'])) / s
                return sum(a*a*(Decimal(y)-mu)**2 for a,y in zip(w,case['values'])) - s + sum(a*a for a in w)/s
            for root, (left, right) in zip(roots, [('0.5','0.7'),('3','4'),('4.8','5.3')]):
                lo, hi = Decimal(left), Decimal(right)
                sign = score(lo)
                self.assertLess(sign * score(hi), 0)
                for _ in range(150):
                    mid = (lo + hi) / 2
                    if score(mid) * sign > 0:
                        lo = mid
                    else:
                        hi = mid
                self.assertLess(abs(root.tau - (lo + hi) / 2), Decimal('1e-23'))

    def test_limits_repeated_roots_and_ties(self):
        for cohort in (snapshot([1,2], ['A','A']),
                       snapshot(list(range(7)), list('ABCDEFG')),
                       snapshot(list(range(25)), ['A','B'] * 12 + ['A'])):
            with self.assertRaises(FitDomainError):
                fit_frozen_cohort(cohort)
        # (t-1)^2(t-2), repeated roots must not disappear.
        roots = isolate_positive_roots([Fraction(-2), Fraction(5), Fraction(-4), Fraction(1)])
        self.assertEqual(len(roots), 2)
        self.assertAlmostEqual(float(roots[0].tau), 1, delta=1e-12)
        self.assertAlmostEqual(float(roots[1].tau), 2, delta=1e-12)
        # Pure candidate comparison policy: exact objective ties choose the smaller variance.
        state = fit_frozen_cohort(snapshot())
        self.assertEqual(_choose_best([replace(state, tau=Decimal(2)),
                                       replace(state, tau=Decimal(1))]).tau, 1)
        # Repeated candidate enumeration does not alter an actual fit.
        problem = build_likelihood_problem(snapshot())
        candidates = enumerate_stationary_candidates(problem)
        self.assertEqual(select_global_fit(problem, candidates * 2),
                         select_global_fit(problem, tuple(reversed(candidates))))
