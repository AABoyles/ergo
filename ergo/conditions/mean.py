import jax.numpy as np

from ergo.scale import Scale

from . import condition


class MeanCondition(condition.Condition):
    """
    The distribution should have as close to the specified mean as possible.
    """

    mean: float
    weight: float = 1.0

    def __init__(self, mean, weight=1.0):
        self.mean = mean
        super().__init__(weight)

    def actual_mean(self, dist) -> float:
        xs = np.linspace(dist.scale_min, dist.scale_max, dist.ps.size)
        return np.dot(dist.ps, xs)

    def loss(self, dist) -> float:
        return self.weight * (self.actual_mean(dist) - self.mean) ** 2

    def _describe_fit(self, dist):
        description = super()._describe_fit(dist)
        description["mean"] = self.actual_mean(dist)
        return description

    def normalize(self, scale_min: float, scale_max: float):
        scale = Scale(scale_min, scale_max)
        normalized_mean = scale.normalize_point(self.mean)
        return self.__class__(normalized_mean, self.weight)

    def denormalize(self, scale_min: float, scale_max: float):
        scale = Scale(scale_min, scale_max)
        denormalized_mean = scale.denormalize_point(self.mean)
        return self.__class__(denormalized_mean, self.weight)

    def destructure(self):
        return (MeanCondition, (self.mean, self.weight))

    def __str__(self):
        return f"The mean is {self.mean}."
