"""Public finite regression checks, not an implementation or completeness oracle."""
import argparse
import copy
import sys
import tempfile
import unittest
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
from pathlib import Path
from support_examples import rows, requests, COMPONENTS, A_MEAN_RANGE, A_INTERNAL_TAU
from tests.test_batch_fit import snapshot, independent_reml
from tests.test_predictions import gaussian_oracle
from results.database import Database, database_session, StorageError, ResultNotFound
from predictions.requests import PredictionRequestError
from application.measurements import apply_measurements
from application.cohorts import freeze_cohort
from application.results import read_result
import application.analysis as analysis


class ReferenceFixtures(unittest.TestCase):
    def test_two_components_fixture(self):
        source = rows()
        cohort = snapshot([r["value"] for r in source],
                          [r["batch_id"] for r in source],
                          [r["variance"] for r in source])
        with localcontext() as context:
            context.prec = 70
            maximum = independent_reml(cohort, D("0.572635300618849692821030889591808753134188"))
            level = maximum - D("0.080")
            for pair in COMPONENTS:
                for t in pair:
                    self.assertLess(abs(independent_reml(cohort, D(t)) - level), D("1e-35"))
            self.assertLess(independent_reml(cohort, D("3.5556579892030454")), level)
            self.assertGreater(independent_reml(cohort, D("5.040483857472118")), level)

    def test_interior_mean_fixture(self):
        source = rows()
        req = [{"batch_id": "A", "existing": True}]
        middle = gaussian_oracle(source, F(A_INTERNAL_TAU), req)[0][0]
        with localcontext() as context:
            context.prec = 70
            self.assertLess(abs(D(middle.numerator) / D(middle.denominator) -
                                D(A_MEAN_RANGE[1])), D("1e-35"))
        ends = [gaussian_oracle(source, F(t), req)[0][0] for pair in COMPONENTS for t in pair]
        self.assertGreater(middle - max(ends), F("0.0006"))
        for step in [F("-0.001"), F("0.001")]:
            nearby = gaussian_oracle(source, F(A_INTERNAL_TAU) + step, req)[0][0]
            self.assertGreater(middle, nearby)


class SupportWorkflow(unittest.TestCase):
    def setUp(self):
        self.api_support = getattr(analysis, "support_batch")
        self.api_predict = getattr(analysis, "predict_support")
        self.database = Database(":memory:")
        self.addCleanup(self.database.close)
        self.session = database_session(self.database)
        self.session.__enter__()
        self.addCleanup(self.session.__exit__, None, None, None)

    def fit(self, zero=False):
        source = rows(zero)
        apply_measurements(source)
        cohort = freeze_cohort([r["measurement_id"] for r in source])
        return source, analysis.fit_batch(cohort["cohort_id"])

    def close_pair(self, actual, expected, tolerance=1e-8):
        self.assertEqual(len(actual), 2)
        self.assertLessEqual(actual[0], actual[1])
        for x, y in zip(actual, expected):
            self.assertAlmostEqual(x, float(y), delta=tolerance)

    def state(self):
        return tuple(self.database.connection.iterdump())

    def test_disconnected_and_interior_joint(self):
        source, fit = self.fit()
        support = self.api_support(fit["result_id"], D("0.080"))
        self.assertEqual(support["kind"], "support")
        self.assertEqual(support["fit_id"], fit["result_id"])
        self.assertEqual(support["cohort_id"], fit["cohort_id"])
        self.assertEqual(support["snapshot"], fit["snapshot"])
        self.assertEqual(support["provenance"], fit["provenance"])
        self.assertEqual(support["drop"], 0.080)
        self.assertEqual(len(support["components"]), 2)
        for actual, expected in zip(support["components"], COMPONENTS):
            self.close_pair(actual, expected, 1e-7)
        self.assertLess(support["components"][0][1], support["components"][1][0])
        zero_drop = self.api_support(fit["result_id"], 0)
        self.assertEqual(len(zero_drop["components"]), 1)
        self.close_pair(zero_drop["components"][0], [fit["tau"], fit["tau"]], 1e-7)
        req = requests()
        point = analysis.predict_batches(fit["result_id"], req)
        at_peak = self.api_predict(zero_drop["result_id"], req)
        for i in range(len(req)):
            self.close_pair(at_peak["mean_ranges"][i], [point["means"][i]] * 2)
            for j in range(len(req)):
                self.close_pair(at_peak["covariance_ranges"][i][j], [point["covariance"][i][j]] * 2)
        report = self.api_predict(support["result_id"], req)
        self.assertEqual(report["kind"], "support_prediction")
        self.assertEqual(report["support_id"], support["result_id"])
        self.assertEqual(report["fit_id"], fit["result_id"])
        self.assertEqual(report["requests"], req)
        self.assertEqual(len(report["mean_ranges"]), len(req))
        self.assertEqual(len(report["covariance_ranges"]), len(req))
        self.close_pair(report["mean_ranges"][0], A_MEAN_RANGE)
        self.close_pair(report["mean_ranges"][1], report["mean_ranges"][2])
        for left, right in zip(report["covariance_ranges"][1], report["covariance_ranges"][2]):
            self.close_pair(left, right)
        self.close_pair(report["covariance_ranges"][1][1], report["covariance_ranges"][1][2])
        for t in [F("0.3"), F("3"), F("4.3"), F("5.5"), F(A_INTERNAL_TAU)]:
            means, cov = gaussian_oracle(source, t, req)
            for i in range(len(req)):
                lo, hi = report["mean_ranges"][i]
                self.assertLessEqual(lo - 1e-8, float(means[i]))
                self.assertLessEqual(float(means[i]), hi + 1e-8)
                for j in range(len(req)):
                    self.close_pair(report["covariance_ranges"][i][j],
                                    report["covariance_ranges"][j][i])
                    lo, hi = report["covariance_ranges"][i][j]
                    self.assertLessEqual(lo - 1e-8, float(cov[i][j]))
                    self.assertLessEqual(float(cov[i][j]), hi + 1e-8)
        permutation = [3, 0, 2, 1]
        other = self.api_predict(support["result_id"], [req[i] for i in permutation])
        for i, p in enumerate(permutation):
            self.close_pair(other["mean_ranges"][i], report["mean_ranges"][p])
            for j, q in enumerate(permutation):
                self.close_pair(other["covariance_ranges"][i][j],
                                report["covariance_ranges"][p][q])
        empty = self.api_predict(support["result_id"], [])
        self.assertEqual((empty["mean_ranges"], empty["covariance_ranges"]), ([], []))

    def test_zero_drop_and_boundary_all_matrix_entries(self):
        _, fit = self.fit(zero=True)
        single = self.api_support(fit["result_id"], 0)
        self.assertEqual(single["components"], [[0.0, 0.0]])
        support = self.api_support(fit["result_id"], 0.5)
        with localcontext() as context:
            context.prec = 70
            upper = D("0.5").exp() - 1
        self.assertEqual(len(support["components"]), 1)
        self.close_pair(support["components"][0], [0, upper], 1e-7)
        req = [{"batch_id": b, "existing": b in ("A", "B")} for b in ["A", "B", "X", "X", "Y"]]
        report = self.api_predict(support["result_id"], req)
        point = self.api_predict(single["result_id"], req)
        with localcontext() as context:
            context.prec = 70
            third = D(1) / 3
            for i, left in enumerate(req):
                self.close_pair(report["mean_ranges"][i], [1, 1])
                for j, right in enumerate(req):
                    self.close_pair(point["covariance_ranges"][i][j], [third, third])
                    if left["existing"] and right["existing"]:
                        if left["batch_id"] == right["batch_id"]:
                            expected = [third, (upper + third) / (upper + 1)]
                        else:
                            expected = [third / (upper + 1), third]
                    elif left["existing"] or right["existing"]:
                        expected = [third, third]
                    elif left["batch_id"] == right["batch_id"]:
                        expected = [third, upper + (upper + 1) / 3]
                    else:
                        expected = [third, (upper + 1) / 3]
                    self.close_pair(report["covariance_ranges"][i][j], expected)

    def test_rejection_and_atomic_retry(self):
        _, fit = self.fit()
        support = self.api_support(fit["result_id"], 0.080)
        report = self.api_predict(support["result_id"], requests())
        before = self.state()
        for drop in [True, -1, float("nan"), float("inf"), "", object()]:
            with self.assertRaises(ValueError):
                self.api_support(fit["result_id"], drop)
            self.assertEqual(self.state(), before)
        for req in [[{"batch_id": "A", "existing": False}],
                    [{"batch_id": "unknown", "existing": True}],
                    [{"batch_id": "X", "existing": False}] * 9]:
            with self.assertRaises(PredictionRequestError):
                self.api_predict(support["result_id"], req)
            self.assertEqual(self.state(), before)
        with self.assertRaises(ResultNotFound):
            self.api_predict("absent", [])
        with self.assertRaises(ValueError):
            self.api_support(support["result_id"], 0.1)
        with self.assertRaises(ValueError):
            self.api_predict(fit["result_id"], [])
        self.assertEqual(self.state(), before)
        for kind, call in [
            ("support", lambda: self.api_support(fit["result_id"], 0.080)),
            ("support_prediction", lambda: self.api_predict(support["result_id"], requests())),
        ]:
            self.database.fail_next_publication(kind)
            with self.assertRaises(StorageError):
                call()
            self.assertEqual(self.state(), before)
            retry = call()
            self.assertEqual(read_result(retry["result_id"]), retry)
            before = self.state()
        self.assertEqual(read_result(support["result_id"]), support)
        self.assertEqual(read_result(report["result_id"]), report)

    def test_correction_reopen_and_read_without_computation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "laboratory.sqlite"
            disk = Database(path)
            try:
                with database_session(disk):
                    source = rows()
                    apply_measurements(source)
                    cohort = freeze_cohort([r["measurement_id"] for r in source])
                    fit = analysis.fit_batch(cohort["cohort_id"])
                    point = analysis.predict_batches(fit["result_id"], requests())
            finally:
                disk.close()
            disk = Database(path)
            try:
                with database_session(disk):
                    support = self.api_support(fit["result_id"], D("0.080"))
                    req = requests()
                    report = self.api_predict(support["result_id"], req)
                    saved_support, saved_report = copy.deepcopy(support), copy.deepcopy(report)
                    support["components"][0][0] = 99
                    support["snapshot"]["rows"][0]["value"] = "99"
                    report["mean_ranges"][0][0] = 99
                    req[0]["batch_id"] = "mutated"
                    apply_measurements([dict(source[0], revision=2, value=99, batch_id="corrected")])
                    self.assertEqual(read_result(saved_support["result_id"]), saved_support)
                    self.assertEqual(read_result(saved_report["result_id"]), saved_report)
                    later = self.api_predict(saved_support["result_id"], requests())
                    for i in range(len(requests())):
                        self.close_pair(later["mean_ranges"][i], saved_report["mean_ranges"][i])
                        for j in range(len(requests())):
                            self.close_pair(later["covariance_ranges"][i][j],
                                            saved_report["covariance_ranges"][i][j])
            finally:
                disk.close()
            disk = Database(path)
            try:
                with database_session(disk):
                    def forbid(frame, event, arg):
                        if event == "call":
                            name = frame.f_code.co_name
                            if name in {"fit_frozen_cohort", "select_global_fit", "evaluate_fit_state",
                                        "predict_joint_levels", "condition_batch_levels",
                                        "assemble_joint_prediction", "support_batch", "predict_support"}:
                                raise AssertionError("read_result recalculated: " + name)
                    previous = sys.getprofile()
                    sys.setprofile(forbid)
                    try:
                        self.assertEqual(read_result(fit["result_id"]), fit)
                        self.assertEqual(read_result(point["result_id"]), point)
                        self.assertEqual(read_result(saved_support["result_id"]), saved_support)
                        self.assertEqual(read_result(saved_report["result_id"]), saved_report)
                    finally:
                        sys.setprofile(previous)
            finally:
                disk.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["reference", "verify"])
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(ReferenceFixtures)
    if args.mode == "verify":
        suite.addTests(loader.discover("tests"))
        suite.addTests(loader.loadTestsFromTestCase(SupportWorkflow))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
