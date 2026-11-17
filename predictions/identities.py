from dataclasses import dataclass
from decimal import Decimal
from predictions.requests import parse_requests, PredictionRequestError


@dataclass(frozen=True)
class IdentityPlan:
    requests: tuple
    unique: tuple
    positions: tuple


def resolve_batch_identities(fit, requests):
    parsed = parse_requests(requests)
    known = set(fit.problem.batches)
    unique, positions, index = [], [], {}
    for request in parsed:
        if request.existing != (request.batch_id in known):
            raise PredictionRequestError('batch marker disagrees with frozen observations')
        if request.batch_id in index:
            previous = unique[index[request.batch_id]]
            if previous.existing != request.existing:
                raise PredictionRequestError('contradictory batch identity')
        else:
            index[request.batch_id] = len(unique)
            unique.append(request)
        positions.append(index[request.batch_id])
    return IdentityPlan(parsed, tuple(unique), tuple(positions))


def build_shared_identity_matrix(plan, tau):
    return [[tau if left.batch_id == right.batch_id else Decimal(0)
             for right in plan.unique] for left in plan.unique]
