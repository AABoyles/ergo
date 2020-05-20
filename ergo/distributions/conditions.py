from abc import ABC, abstractmethod
from dataclasses import dataclass

from jax import vmap
import jax.numpy as np

from .types import Histogram


class Condition(ABC):
    @abstractmethod
    def loss(self, dist):
        ...


@dataclass
class PercentileCondition(Condition):
    percentile: float
    value: float
    weight: float

    def __init__(self, percentile, value, weight=1.0):
        if not 0 <= percentile <= 1:
            raise ValueError(f"Percentile should be in 0..1, got {percentile}")
        self.percentile = percentile
        self.value = value
        self.weight = weight

    def loss(self, dist):
        target_percentile = self.percentile
        actual_percentile = dist.cdf(self.value)
        return self.weight * (actual_percentile - target_percentile) ** 2

    def __str__(self):
        return (
            f"There is a {self.percentile:.0%} chance that the value is <{self.value}"
        )


@dataclass
class HistogramCondition(Condition):
    histogram: Histogram
    weight: float = 1.0

    def _loss_loop(self, dist):
        total_loss = 0.0
        for entry in self.histogram:
            target_density = entry["density"]
            actual_density = dist.pdf1(entry["x"])
            total_loss += (actual_density - target_density) ** 2
        return self.weight * total_loss / len(self.histogram)

    def loss(self, dist):
        xs = np.array([entry["x"] for entry in self.histogram])
        densities = np.array([entry["density"] for entry in self.histogram])
        entry_loss_fn = lambda x, density: (density - dist.pdf1(x)) ** 2  # noqa: E731
        total_loss = np.sum(vmap(entry_loss_fn)(xs, densities))
        return self.weight * total_loss / len(self.histogram)

    def __str__(self):
        return f"The probability density function looks similar to the provided density function."


@dataclass
class IntervalCondition(Condition):
    p: float
    min: float
    max: float
    weight: float

    def __init__(self, p, min=float("-inf"), max=float("inf"), weight=1.0):
        if max <= min:
            raise ValueError(
                f"max must be greater than min, got max: {max}, min: {min}"
            )

        self.p = p
        self.min = min
        self.max = max
        self.weight = weight

    def loss(self, dist):
        cdf_at_min = dist.cdf(self.min) if self.min is not float("-inf") else 0
        cdf_at_max = dist.cdf(self.max) if self.max is not float("inf") else 1
        actual_p = cdf_at_max - cdf_at_min
        return self.weight * (actual_p - self.p) ** 2

    def __str__(self):
        return f"There is a {self.p:.0%} chance that the value is in [{self.min}, {self.max}]"
