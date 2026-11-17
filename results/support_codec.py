import json
from dataclasses import dataclass
from decimal import Decimal
from batch_analysis.support import SupportSet
from cohorts.snapshot import snapshot_to_record, snapshot_from_record
from cohorts.provenance import summarize_provenance


class SupportPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class SupportPayload:
    support: SupportSet
    provenance: dict
    cohort_id: str
    drop_text: str


def encode_support(cohort_id, fit_id, support, provenance):
    record = {
        'version': 1,
        'cohort_id': cohort_id,
        'fit_id': fit_id,
        'drop': str(support.drop),
        'snapshot': snapshot_to_record(support.problem.cohort),
        'provenance': provenance,
        'maximum': str(support.maximum),
        'maximizers': [str(tau) for tau in support.maximizers],
        'components': [[str(lo), str(hi)] for lo, hi in support.components],
    }
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    decode_support(payload)
    return payload


def _fraction_decimal(text):
    number = Decimal(text)
    if not number.is_finite():
        raise SupportPayloadError('nonfinite support payload')
    return number


def decode_support(payload):
    try:
        record = json.loads(payload)
        if record['version'] != 1:
            raise SupportPayloadError('unsupported support payload')
        cohort = snapshot_from_record(record['snapshot'])
        if record['provenance'] != summarize_provenance(cohort.rows):
            raise SupportPayloadError('support provenance mismatch')
        if record['cohort_id'] != cohort.cohort_id:
            raise SupportPayloadError('support cohort binding mismatch')
        components = tuple((_fraction_decimal(lo), _fraction_decimal(hi))
                           for lo, hi in record['components'])
        if not components or any(lo < 0 or lo > hi for lo, hi in components):
            raise SupportPayloadError('invalid support components')
        for left, right in zip(components, components[1:]):
            if right[0] <= left[1]:
                raise SupportPayloadError('support components must keep their gaps')
        drop = _fraction_decimal(record['drop'])
        if drop < 0:
            raise SupportPayloadError('negative persisted drop')
        from batch_analysis.likelihood import build_likelihood_problem
        problem = build_likelihood_problem(cohort)
        support = SupportSet(problem, drop, _fraction_decimal(record['maximum']),
                             tuple(_fraction_decimal(tau) for tau in record['maximizers']),
                             components)
        return SupportPayload(support, record['provenance'], record['cohort_id'],
                              record['drop']), record['fit_id']
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise SupportPayloadError('invalid frozen support payload') from exc


def copy_support_result(payload, fit_id):
    decoded, stored_fit_id = decode_support(payload)
    support = decoded.support
    if stored_fit_id != fit_id:
        raise SupportPayloadError('published fit binding mismatch')
    return {
        'kind': 'support',
        'result_id': None,
        'fit_id': fit_id,
        'cohort_id': decoded.cohort_id,
        'drop': float(Decimal(decoded.drop_text)),
        'components': [[float(lo), float(hi)] for lo, hi in support.components],
        'snapshot': snapshot_to_record(support.problem.cohort),
        'provenance': decoded.provenance,
    }
