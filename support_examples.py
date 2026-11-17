"""Finite public inputs and a joint business demonstration; no support solver."""
import json
import tempfile
from pathlib import Path

VALUES = [-8, -8, 0, -9, 1]
VARIANCES = ["1", "0.1", "100", "0.1", "10"]
COMPONENTS = [
    ["0.2500389516876884575496005184793377528656902885445254733172184763768491",
     "3.113807552564445059380960976223873484173463044744079085823848225536272"],
    ["4.213206967801972610542334157281716323078181124724517314436894662240342",
     "5.71066844026591018280934963753680149172913087188566252355157352697100"],
]
A_MEAN_RANGE = [
    "-8.229436493964885812493807053328931285209296123990012492675363824810642",
    "-7.873988348833430132614181229170583451726359365025122114448718757228342",
]
A_INTERNAL_TAU = "5.02183252962791360947131372296353818938541608805948299274618529253"


def rows(zero=False):
    values = [1, 1, 1] if zero else VALUES
    variances = ["1"] * 3 if zero else VARIANCES
    return [
        {"measurement_id": "s" + str(i), "revision": 1, "batch_id": "ABCDE"[i],
         "value": value, "variance": variance, "unit": "mg/L"}
        for i, (value, variance) in enumerate(zip(values, variances))
    ]


def requests():
    return [{"batch_id": b, "existing": b == "A"} for b in ["A", "X", "X", "Y"]]


def main():
    from results.database import Database, database_session
    from application.measurements import apply_measurements
    from application.cohorts import freeze_cohort
    from application.analysis import fit_batch, support_batch, predict_support
    from application.results import read_result
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "support.sqlite"
        database = Database(path)
        try:
            with database_session(database):
                source = rows()
                apply_measurements(source)
                cohort = freeze_cohort([r["measurement_id"] for r in source])
                fit = fit_batch(cohort["cohort_id"])
                support = support_batch(fit["result_id"], 0.080)
                report = predict_support(support["result_id"], requests())
                assert len(support["components"]) == 2
                for actual, expected in zip(support["components"], COMPONENTS):
                    assert all(abs(x - float(y)) <= 1e-7 for x, y in zip(actual, expected))
                assert all(abs(x - float(y)) <= 1e-8
                           for x, y in zip(report["mean_ranges"][0], A_MEAN_RANGE))
                apply_measurements([dict(source[0], revision=2, value=99, batch_id="corrected")])
        finally:
            database.close()
        database = Database(path)
        try:
            with database_session(database):
                assert read_result(support["result_id"]) == support
                assert read_result(report["result_id"]) == report
        finally:
            database.close()
        print(json.dumps({"components": support["components"],
                          "A_mean_range": report["mean_ranges"][0],
                          "duplicate_X_covariance_ranges": report["covariance_ranges"][1][2],
                          "old_results_equal_after_correction_and_reopen": True},
                         ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
