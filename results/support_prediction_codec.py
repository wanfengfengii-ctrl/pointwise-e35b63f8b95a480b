import json
from dataclasses import dataclass
from decimal import Decimal
from predictions.requests import parse_requests
from predictions.ranges import SupportPrediction
from measurements.validation import validate_identifier


class SupportPredictionPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class StoredSupportPrediction:
    support_id: str
    fit_id: str
    prediction: SupportPrediction


def encode_support_prediction(support_id, fit_id, prediction):
    size = len(prediction.requests)
    if (len(prediction.mean_ranges) != size or
            len(prediction.covariance_ranges) != size or
            any(len(row) != size for row in prediction.covariance_ranges)):
        raise SupportPredictionPayloadError('support prediction dimensions disagree')
    for ranges in (prediction.mean_ranges, *prediction.covariance_ranges):
        for lo, hi in ranges:
            if not Decimal(str(lo)).is_finite() or not Decimal(str(hi)).is_finite() or lo > hi:
                raise SupportPredictionPayloadError('invalid persisted moment range')
    record = {
        'version': 1,
        'support_id': validate_identifier(support_id),
        'fit_id': validate_identifier(fit_id),
        'requests': [request.record() for request in prediction.requests],
        'mean_ranges': [[str(lo), str(hi)] for lo, hi in prediction.mean_ranges],
        'covariance_ranges': [[[str(lo), str(hi)] for lo, hi in row]
                              for row in prediction.covariance_ranges],
    }
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    decode_support_prediction(payload)
    return payload


def decode_support_prediction(payload):
    try:
        record = json.loads(payload)
        if record['version'] != 1:
            raise SupportPredictionPayloadError('unsupported support prediction payload')
        support_id = validate_identifier(record['support_id'])
        fit_id = validate_identifier(record['fit_id'])
        requests = parse_requests(record['requests'])
        size = len(requests)
        mean_ranges = tuple((Decimal(lo), Decimal(hi))
                            for lo, hi in record['mean_ranges'])
        covariance_ranges = tuple(
            tuple((Decimal(lo), Decimal(hi)) for lo, hi in row)
            for row in record['covariance_ranges'])
        if len(mean_ranges) != size or len(covariance_ranges) != size:
            raise SupportPredictionPayloadError('support prediction dimensions disagree')
        ranges = list(mean_ranges) + [pair for row in covariance_ranges for pair in row]
        if any(not lo.is_finite() or not hi.is_finite() or lo > hi for lo, hi in ranges):
            raise SupportPredictionPayloadError('invalid persisted moment range')
        prediction = SupportPrediction(support_id, fit_id, requests,
                                       mean_ranges, covariance_ranges)
        return StoredSupportPrediction(support_id, fit_id, prediction)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise SupportPredictionPayloadError('invalid frozen support prediction payload') from exc


def copy_support_prediction_result(payload):
    stored = decode_support_prediction(payload)
    prediction = stored.prediction
    return {
        'kind': 'support_prediction',
        'result_id': None,
        'support_id': stored.support_id,
        'fit_id': stored.fit_id,
        'requests': [request.record() for request in prediction.requests],
        'mean_ranges': [[float(lo), float(hi)] for lo, hi in prediction.mean_ranges],
        'covariance_ranges': [[[float(lo), float(hi)] for lo, hi in row]
                              for row in prediction.covariance_ranges],
    }
