from dataclasses import dataclass
from decimal import Decimal, localcontext
from predictions.identities import resolve_batch_identities, build_shared_identity_matrix
from predictions.conditioning import condition_batch_levels
from batch_analysis.matrices import dot, NumericalError


@dataclass(frozen=True)
class JointPrediction:
    requests: tuple
    means: tuple
    covariance: tuple


def validate_joint_prediction(prediction):
    size = len(prediction.requests)
    if len(prediction.means) != size or len(prediction.covariance) != size:
        raise NumericalError('prediction dimensions disagree')
    if any(len(row) != size for row in prediction.covariance):
        raise NumericalError('prediction matrix is not square')
    numbers = list(prediction.means) + [value for row in prediction.covariance for value in row]
    if any(not Decimal(value).is_finite() for value in numbers):
        raise NumericalError('nonfinite prediction')
    for i in range(size):
        if prediction.covariance[i][i] < 0:
            raise NumericalError('negative prediction variance')
        for j in range(size):
            if abs(prediction.covariance[i][j] - prediction.covariance[j][i]) > Decimal('1e-55'):
                raise NumericalError('asymmetric prediction covariance')
    for value in numbers:
        public = Decimal(str(float(value)))
        if not public.is_finite() or abs(public - value) > Decimal('1e-8'):
            raise NumericalError('public prediction cannot retain required precision')
    return prediction


def assemble_joint_prediction(state):
    with localcontext() as context:
        context.prec = 80
        shared = build_shared_identity_matrix(state.plan, state.tau)
        covariance = tuple(tuple(
            shared[i][j] - dot(state.cross[i], state.solved_cross[j]) +
            state.mean_loadings[i] * state.mean_loadings[j] / state.precision
            for j in range(len(shared))) for i in range(len(shared)))
        positions = state.plan.positions
        prediction = JointPrediction(
            state.plan.requests, tuple(state.means[i] for i in positions),
            tuple(tuple(covariance[i][j] for j in positions) for i in positions))
        return validate_joint_prediction(prediction)


def predict_joint_levels(fit, requests):
    plan = resolve_batch_identities(fit, requests)
    return assemble_joint_prediction(condition_batch_levels(fit, plan))
