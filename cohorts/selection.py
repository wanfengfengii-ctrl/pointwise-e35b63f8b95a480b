from measurements.model import MeasurementStatus
from measurements.validation import validate_identifier


class CohortSelectionError(ValueError):
    pass


def validate_selection_ids(identities):
    if not isinstance(identities, (list, tuple)) or not identities:
        raise CohortSelectionError('nonempty ordered selection required')
    try:
        selected = tuple(validate_identifier(identity) for identity in identities)
    except ValueError as exc:
        raise CohortSelectionError(str(exc)) from exc
    if len(set(selected)) != len(selected):
        raise CohortSelectionError('duplicate measurement identity')
    return selected


def select_current_rows(identities, current):
    rows = []
    for identity in validate_selection_ids(identities):
        row = current.get(identity)
        if row is None or row.status != MeasurementStatus.ACTIVE:
            raise CohortSelectionError(f'measurement unavailable: {identity}')
        rows.append(row)
    return tuple(rows)
