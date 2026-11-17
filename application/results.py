from results.database import current_database, ResultNotFound
from results.fit_codec import copy_fit_result, FitPayloadError
from results.prediction_codec import copy_prediction_result, PredictionPayloadError
from results.support_codec import copy_support_result, SupportPayloadError
from results.support_prediction_codec import (
    copy_support_prediction_result, SupportPredictionPayloadError,
)


def read_result(result_id):
    database = current_database()
    heads = database.query(
        'SELECT result_id FROM result_heads WHERE result_id=?', (result_id,))
    supports = database.query(
        'SELECT support_id FROM support_heads WHERE support_id=?', (result_id,))
    range_heads = database.query(
        'SELECT prediction_id FROM support_prediction_heads WHERE prediction_id=?',
        (result_id,))
    if sum(bool(rows) for rows in (heads, supports, range_heads)) > 1:
        raise ResultNotFound('ambiguous result identity: ' + result_id)
    if supports:
        stored = database.read_support(result_id)
        result = copy_support_result(stored['payload'], stored['fit_id'])
        if result['cohort_id'] != stored['cohort_id']:
            raise SupportPayloadError('published cohort binding mismatch')
    elif range_heads:
        stored = database.read_support_prediction(result_id)
        result = copy_support_prediction_result(stored['payload'])
        if (result['support_id'] != stored['support_id'] or
                result['fit_id'] != stored['fit_id']):
            raise SupportPredictionPayloadError('published support binding mismatch')
    elif heads:
        stored = database.read_published(result_id)
        if stored['kind'] == 'fit':
            result = copy_fit_result(stored['payload'])
            if result['cohort_id'] != stored['cohort_id']:
                raise FitPayloadError('published cohort binding mismatch')
        else:
            result = copy_prediction_result(stored['payload'])
            if result['fit_id'] != stored['fit_id']:
                raise PredictionPayloadError('published fit binding mismatch')
    else:
        raise ResultNotFound(result_id)
    result['result_id'] = result_id
    return result
