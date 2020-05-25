"""
Location–Scale Family Distribution Base Class

A location–scale family is a family of probability distributions
parametrized by a location parameter and a non-negative scale
parameter
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar

from jax import jit, scipy
import jax.numpy as np
import numpy as onp
import scipy as oscipy

from .conditions import Condition
from .distribution import Distribution
from .scale import Scale

LSD = TypeVar("LSD", bound="LSDistribution")


@dataclass
class LSDistribution(Distribution):
    loc: float
    scale: float
    metadata: Optional[Dict[str, Any]]

    dist: Any = field(
        default=scipy.stats.logistic, repr=False
    )  # no jax.scipy.stats.rv_continuous
    odist: oscipy.stats.rv_continuous = field(default=oscipy.stats.logistic, repr=False)

    def __init__(self, loc: float, scale: float, metadata=None):
        # TODO (#303): Raise ValueError on scale < 0
        self.scale = np.max([scale, 0.0000001])
        self.loc = loc
        self.metadata = metadata

    def __mul__(self, x):
        return self.__class__(self.loc * x, self.scale * x)

    def rv(self):
        return self.odist(loc=self.loc, scale=self.scale)

    def cdf(self, x):
        y = (x - self.loc) / self.scale
        return self.dist.cdf(y)

    def ppf(self, q):
        """
        Percent point function (inverse of cdf) at q.
        """
        return self.rv().ppf(q)

    def sample(self):
        # FIXME (#296): This needs to be compatible with ergo sampling
        return self.odist.rvs(loc=self.loc, scale=self.scale)

    def normalize(self, scale_min: float, scale_max: float):
        """
        Assume that the condition's true range is [scale_min, scale_max].
        Return the normalized condition.

        :param scale_min: the true-scale minimum of the range
        :param scale_max: the true-scale maximum of the range
        :return: the condition normalized to [0,1]
        """
        scale = Scale(scale_min, scale_max)
        normalized_loc = scale.normalize_point(self.loc)
        normalized_scale = self.scale / scale.range
        return self.__class__(normalized_loc, normalized_scale, self.metadata)

    def denormalize(self, scale_min: float, scale_max: float):
        """
        Assume that the distribution has been normalized to be over [0,1].
        Return the distribution on the true scale of [scale_min, scale_max]

        :param scale_min: the true-scale minimum of the range
        :param scale_max: the true-scale maximum of the range
        """
        scale = Scale(scale_min, scale_max)
        denormalized_loc = scale.denormalize_point(self.loc)
        denormalized_scale = self.scale * scale.range
        return self.__class__(denormalized_loc, denormalized_scale, self.metadata)

    @classmethod
    def from_samples_scipy(cls: Type[LSD], samples) -> LSD:
        with onp.errstate(all="raise"):  # type: ignore
            loc, scale = cls.odist.fit(samples)
            return cls(loc, scale)

    @classmethod
    def from_conditions(
        cls: Type[LSD], conditions: List[Condition], initial_dist: Optional[Any] = None
    ) -> LSD:
        raise NotImplementedError

    @staticmethod
    def from_samples(samples):
        raise NotImplementedError


class Logistic(LSDistribution):
    dist = scipy.stats.logistic
    odist = oscipy.stats.logistic

    @staticmethod
    @jit
    def params_logpdf(x, loc, scale):  # cannot be moved to LSD because JAX
        # https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.logistic.html
        y = (x - loc) / scale
        return scipy.stats.logistic.logpdf(y) - np.log(scale)

    @staticmethod
    def from_samples(samples):  # TODO consider refactoring
        from .logistic_mixture import LogisticMixture

        mixture = LogisticMixture.from_samples(samples, num_components=1)
        return mixture.components[0]


class Normal(LSDistribution):
    dist = scipy.stats.logistic
    odist = oscipy.stats.logistic

    @staticmethod
    @jit
    def params_logpdf(x, loc, scale):  # cannot be moved to LSD because JAX
        # https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.logistic.html
        y = (x - loc) / scale
        return scipy.stats.norm.logpdf(y) - np.log(scale)

    # @staticmethod
    # def from_samples(samples):  # TODO consider refactoring
    #     from .normal_mixture import NormalMixture

    #     mixture = NormalMixture.from_samples(samples, num_components=1)
    #     return mixture.components[0]
