from dataclasses import dataclass, asdict
from measurements.validation import validate_identifier


class PredictionRequestError(ValueError):
    pass


@dataclass(frozen=True)
class BatchRequest:
    batch_id: str
    existing: bool

    def record(self):
        return asdict(self)


def validate_request_shape(request):
    if not isinstance(request, BatchRequest):
        raise PredictionRequestError('invalid batch request')
    try:
        validate_identifier(request.batch_id)
    except ValueError as exc:
        raise PredictionRequestError(str(exc)) from exc
    if type(request.existing) is not bool:
        raise PredictionRequestError('existing must be boolean')
    return request


def parse_requests(requests):
    if not isinstance(requests, (list, tuple)):
        raise PredictionRequestError('ordered request array required')
    parsed = []
    for item in requests:
        try:
            request = item if isinstance(item, BatchRequest) else BatchRequest(**item)
        except (TypeError, ValueError) as exc:
            raise PredictionRequestError('request requires batch_id and existing') from exc
        parsed.append(validate_request_shape(request))
    return tuple(parsed)
