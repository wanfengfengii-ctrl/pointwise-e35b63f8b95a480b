from decimal import Decimal, localcontext


class NumericalError(ArithmeticError):
    pass


def dot(left, right):
    if len(left) != len(right):
        raise NumericalError('incompatible vectors')
    return sum((a * b for a, b in zip(left, right)), Decimal(0))


def transpose(matrix):
    if not matrix:
        return []
    if any(len(row) != len(matrix[0]) for row in matrix):
        raise NumericalError('ragged matrix')
    return [list(column) for column in zip(*matrix)]


def matrix_product(left, right):
    columns = transpose(right)
    return [[dot(row, column) for column in columns] for row in left]


def cholesky(matrix):
    n = len(matrix)
    if any(len(row) != n for row in matrix):
        raise NumericalError('square matrix required')
    lower = [[Decimal(0)] * n for _ in range(n)]
    with localcontext() as context:
        context.prec = 80
        for i in range(n):
            for j in range(i + 1):
                value = Decimal(matrix[i][j]) - dot(lower[i][:j], lower[j][:j])
                if not value.is_finite():
                    raise NumericalError('nonfinite matrix')
                if i == j:
                    if value <= 0:
                        raise NumericalError('matrix is not positive definite at working precision')
                    lower[i][j] = value.sqrt()
                else:
                    lower[i][j] = value / lower[j][j]
    return lower


def solve_cholesky(lower, rhs):
    if len(lower) != len(rhs):
        raise NumericalError('incompatible solve')
    with localcontext() as context:
        context.prec = 80
        n = len(rhs)
        forward = [Decimal(0)] * n
        for i in range(n):
            forward[i] = (rhs[i] - dot(lower[i][:i], forward[:i])) / lower[i][i]
        result = [Decimal(0)] * n
        for i in reversed(range(n)):
            result[i] = (forward[i] - sum(
                (lower[j][i] * result[j] for j in range(i + 1, n)), Decimal(0))) / lower[i][i]
        return result


def log_determinant(lower):
    with localcontext() as context:
        context.prec = 80
        return 2 * sum((lower[i][i].ln() for i in range(len(lower))), Decimal(0))
