from results.database import current_database
from results.fit_codec import copy_fit_result, FitPayloadError
from results.prediction_codec import copy_prediction_result, PredictionPayloadError


def read_result(result_id):
    stored = current_database().read_published(result_id)
    if stored['kind'] == 'fit':
        result = copy_fit_result(stored['payload'])
        if result['cohort_id'] != stored['cohort_id']:
            raise FitPayloadError('published cohort binding mismatch')
    else:
        result = copy_prediction_result(stored['payload'])
        if result['fit_id'] != stored['fit_id']:
            raise PredictionPayloadError('published fit binding mismatch')
    result['result_id'] = result_id
    return result
