from decimal import Decimal, InvalidOperation, localcontext
from measurements.model import MeasurementError, MeasurementRevision, MeasurementStatus

UNIT_FACTORS = {'mg/L': Decimal(1), 'ug/L': Decimal('0.001'), 'g/L': Decimal(1000)}


def validate_identifier(value):
    if not isinstance(value, str) or not value or not value.strip() or '\x00' in value:
        raise MeasurementError('identifier must be a nonempty opaque string')
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise MeasurementError('invalid numeric field')
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise MeasurementError('invalid numeric field') from exc
    if not number.is_finite():
        raise MeasurementError('finite number required')
    return number


def _canonical(value):
    if value == 0:
        return '0'
    return str(value.normalize())


def convert_value_and_variance(value, variance, unit):
    if not isinstance(unit, str) or unit not in UNIT_FACTORS:
        raise MeasurementError('unknown concentration unit')
    y, v = _number(value), _number(variance)
    if v <= 0:
        raise MeasurementError('variance must be positive')
    with localcontext() as context:
        context.prec = max(80, len(y.as_tuple().digits) + len(v.as_tuple().digits) + 10)
        factor = UNIT_FACTORS[unit]
        return _canonical(y * factor), _canonical(v * factor * factor)


def normalize_measurement(record):
    if not isinstance(record, dict):
        raise MeasurementError('measurement must be an object')
    allowed = {'measurement_id', 'revision', 'batch_id', 'value', 'variance', 'unit', 'withdrawn'}
    if set(record) - allowed:
        raise MeasurementError('unknown measurement fields')
    identity = validate_identifier(record.get('measurement_id'))
    revision = record.get('revision')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise MeasurementError('positive integer revision required')
    withdrawn = record.get('withdrawn', False)
    if not isinstance(withdrawn, bool):
        raise MeasurementError('withdrawn must be boolean')
    if withdrawn:
        if set(record) - {'measurement_id', 'revision', 'withdrawn'}:
            raise MeasurementError('withdrawal only accepts identity and revision')
        return {'measurement_id': identity, 'revision': revision, 'withdrawn': True}
    batch = validate_identifier(record.get('batch_id'))
    value, variance = convert_value_and_variance(
        record.get('value'), record.get('variance'), record.get('unit'))
    return MeasurementRevision(identity, revision, batch, value, variance, MeasurementStatus.ACTIVE)


def normalize_submission(batch):
    if not isinstance(batch, (list, tuple)) or not batch:
        raise MeasurementError('nonempty measurement batch required')
    return tuple(normalize_measurement(item) for item in batch)
