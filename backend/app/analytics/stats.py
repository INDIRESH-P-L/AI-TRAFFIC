"""TRAFFICINTEL AI - Dependency-Free Statistical Primitives

The handful of numerical routines the grounded-intelligence features need,
written out rather than imported. The platform deliberately carries no
NumPy/SciPy/statsmodels (see `verification._t_critical` for the same decision
made earlier): a traffic control system's dependency surface is attack surface,
and every function here is small enough to read and test in full.

What is here, and why each one is exact rather than approximate:

* **Student-t tail probability** via the regularized incomplete beta function
  (Lentz's continued fraction). Anomaly confidence is reported as `1 - p`, so
  the p-value has to be a real p-value - an interpolated table would put an
  invented precision on every confidence the console prints.
* **Linear least squares** via Gaussian elimination with partial pivoting, for
  fitting autoregressive forecast models. The systems are tiny (at most 4x4),
  so a textbook solver is both sufficient and auditable.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def sample_variance(values: Sequence[float]) -> float:
    """Unbiased (n-1) variance. Callers must ensure len(values) >= 2."""
    m = mean(values)
    return sum((v - m) ** 2 for v in values) / (len(values) - 1)


def sample_std(values: Sequence[float]) -> float:
    return math.sqrt(sample_variance(values))


# ---------------------------------------------------------------------------
# Regularized incomplete beta -> Student-t tail probability
# ---------------------------------------------------------------------------

def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (modified Lentz method)."""
    max_iterations = 300
    epsilon = 3.0e-14
    tiny = 1.0e-300

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d

    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            return h

    # Not reached for the (a, b) ranges this module uses; raising is better
    # than returning a p-value that silently failed to converge.
    raise ArithmeticError("Incomplete beta continued fraction did not converge")


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    front = math.exp(log_front)
    # Use the symmetry relation where the continued fraction converges fastest.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def student_t_two_sided_p(t: float, df: float) -> float:
    """Two-sided tail probability P(|T| >= |t|) for Student's t with `df`."""
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    if math.isinf(t):
        return 0.0
    x = df / (df + t * t)
    return regularized_incomplete_beta(df / 2.0, 0.5, x)


# ---------------------------------------------------------------------------
# Linear least squares
# ---------------------------------------------------------------------------

def solve_linear_system(matrix: List[List[float]], rhs: List[float]) -> Optional[List[float]]:
    """Solves A x = b by Gaussian elimination with partial pivoting.

    Returns None when the system is singular (or numerically so). Callers treat
    that as "this model cannot be fitted to this data" and say so, rather than
    receiving coefficients from a matrix that had no unique solution.
    """
    n = len(matrix)
    augmented = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]

    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]

        for row in range(column + 1, n):
            factor = augmented[row][column] / augmented[column][column]
            if factor == 0.0:
                continue
            for k in range(column, n + 1):
                augmented[row][k] -= factor * augmented[column][k]

    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        accumulated = augmented[row][n] - sum(
            augmented[row][k] * solution[k] for k in range(row + 1, n)
        )
        solution[row] = accumulated / augmented[row][row]
    return solution


def ordinary_least_squares(
    design: List[List[float]], target: List[float]
) -> Optional[List[float]]:
    """Fits target ~ design by solving the normal equations X'X b = X'y."""
    if not design or len(design) != len(target):
        return None
    width = len(design[0])
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for row, y in zip(design, target):
        for i in range(width):
            xty[i] += row[i] * y
            ri = row[i]
            xtx_i = xtx[i]
            for j in range(width):
                xtx_i[j] += ri * row[j]
    return solve_linear_system(xtx, xty)
