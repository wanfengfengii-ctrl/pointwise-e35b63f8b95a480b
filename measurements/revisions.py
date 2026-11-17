from dataclasses import dataclass, replace
from measurements.model import (MeasurementError, RevisionConflict, MeasurementStatus,
                                AcceptanceReceipt, canonical_content)


@dataclass(frozen=True)
class RevisionDecision:
    row: object
    disposition: str
    insert: bool


@dataclass(frozen=True)
class RevisionPlan:
    inserts: tuple
    current: tuple
    receipts: tuple


def decide_revision(row, history, current):
    known = history.get(row.revision)
    if known is not None:
        if canonical_content(known) != canonical_content(row):
            raise RevisionConflict(f'conflicting revision: {row.measurement_id}/{row.revision}')
        return RevisionDecision(row, 'replay', False)
    disposition = 'accepted' if current is None or row.revision > current.revision else 'stale'
    return RevisionDecision(row, disposition, True)


def plan_revision_batch(submission, histories):
    histories = {key: dict(value) for key, value in histories.items()}
    current = {key: max(value.values(), key=lambda row: row.revision)
               for key, value in histories.items() if value}
    inserts, pending = [], []
    for submitted in submission:
        if isinstance(submitted, dict):
            identity, revision = submitted['measurement_id'], submitted['revision']
            old = histories.get(identity, {}).get(revision)
            if old is not None and old.status == MeasurementStatus.WITHDRAWN:
                row = old
            else:
                prior = [r for r in histories.get(identity, {}).values() if r.revision < revision]
                if not prior:
                    raise MeasurementError('withdrawal requires an earlier source revision')
                source = max(prior, key=lambda r: r.revision)
                row = replace(source, revision=revision, status=MeasurementStatus.WITHDRAWN)
        else:
            row = submitted
        identity = row.measurement_id
        history = histories.setdefault(identity, {})
        decision = decide_revision(row, history, current.get(identity))
        if decision.insert:
            history[row.revision] = row
            inserts.append(row)
        if identity not in current or row.revision > current[identity].revision:
            current[identity] = row
        pending.append((row, decision.disposition))
    receipts = tuple(AcceptanceReceipt(row.measurement_id, row.revision,
                                      current[row.measurement_id].revision, disposition)
                     for row, disposition in pending)
    return RevisionPlan(tuple(inserts), tuple(current.values()), receipts)
