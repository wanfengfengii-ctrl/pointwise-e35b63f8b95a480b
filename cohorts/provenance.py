from dataclasses import dataclass, asdict
import hashlib
import json


@dataclass(frozen=True)
class SourceRevision:
    measurement_id: str
    revision: int


def capture_provenance(rows):
    return tuple(SourceRevision(row.measurement_id, row.revision) for row in rows)


def validate_provenance(rows, sources):
    expected = capture_provenance(rows)
    if tuple(sources) != expected or len({s.measurement_id for s in sources}) != len(expected):
        raise ValueError('invalid ordered provenance')
    return expected


def summarize_provenance(rows):
    sources = capture_provenance(rows)
    encoded = json.dumps([asdict(source) for source in sources], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'sources': [asdict(source) for source in sources],
            'sha256': hashlib.sha256(encoded).hexdigest()}
