from measurements.validation import normalize_submission
from measurements.repository import MeasurementRepository
from results.database import current_database


def apply_measurements(batch):
    normalized = normalize_submission(batch)
    return MeasurementRepository(current_database()).apply_submission(normalized)
