import json
from dataclasses import dataclass
from decimal import Decimal
from predictions.requests import parse_requests
from predictions.joint import JointPrediction, validate_joint_prediction
from measurements.validation import validate_identifier


class PredictionPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class PredictionPayload:
    fit_id: str
    prediction: JointPrediction


def encode_prediction(fit_id, prediction):
    validate_joint_prediction(prediction)
    record = {'version': 1, 'fit_id': validate_identifier(fit_id),
              'requests': [request.record() for request in prediction.requests],
              'means': [str(value) for value in prediction.means],
              'covariance': [[str(value) for value in row] for row in prediction.covariance]}
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    decode_prediction(payload)
    return payload


def decode_prediction(payload):
    try:
        record = json.loads(payload)
        if record['version'] != 1:
            raise PredictionPayloadError('unsupported prediction payload')
        parent = validate_identifier(record['fit_id'])
        prediction = JointPrediction(
            parse_requests(record['requests']), tuple(Decimal(x) for x in record['means']),
            tuple(tuple(Decimal(x) for x in row) for row in record['covariance']))
        validate_joint_prediction(prediction)
        markers = {}
        for request in prediction.requests:
            if request.batch_id in markers and markers[request.batch_id] != request.existing:
                raise PredictionPayloadError('contradictory persisted identity')
            markers[request.batch_id] = request.existing
        return PredictionPayload(parent, prediction)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise PredictionPayloadError('invalid frozen prediction payload') from exc


def copy_prediction_result(payload):
    decoded = decode_prediction(payload)
    prediction = decoded.prediction
    return {'kind': 'prediction', 'fit_id': decoded.fit_id,
            'requests': [request.record() for request in prediction.requests],
            'means': [float(value) for value in prediction.means],
            'covariance': [[float(value) for value in row] for row in prediction.covariance]}
