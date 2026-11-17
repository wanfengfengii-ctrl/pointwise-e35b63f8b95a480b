from cohorts.repository import CohortRepository
from cohorts.provenance import summarize_provenance
from results.database import current_database


def freeze_cohort(measurement_ids):
    snapshot = CohortRepository(current_database()).freeze(measurement_ids)
    return {'cohort_id': snapshot.cohort_id, 'provenance': summarize_provenance(snapshot.rows)}
