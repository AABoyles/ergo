"""
Truncated mixture of logistic distributions
"""
from dataclasses import dataclass
from typing import Sequence

from jax import nn
import jax.numpy as np
import jax.scipy as scipy
import numpy as onp
import scipy as oscipy

import ergo.scale as scale

from .logistic import Logistic
from .logistic_mixture import LogisticMixture
from .mixture import Mixture
from .optimizable import Optimizable


@dataclass
class TruncatedLogisticMixture(Mixture, Optimizable):
    components: Sequence[Logistic]
    probs: Sequence[float]
    floor: float
    ceiling: float

    def __post_init__(self):
        self.base_dist = LogisticMixture(self.components, self.probs)
        p_below = super().cdf(self.floor)
        p_above = 1 - super().cdf(self.ceiling)
        self.p_inside = 1 - (p_below + p_above)
        self.logp_inside = np.log(self.p_inside)

    def logpdf(self, x):
        logp_x = self.base_dist.logpdf(x) - self.logp_inside
        res = np.where(
            x < self.floor, -np.inf, np.where(x > self.ceiling, -np.inf, logp_x)
        )
        return res

    def cdf(self, x):
        cdf_x = self.base_dist.cdf(x) / self.p_inside
        return np.where(x < self.floor, 0, np.where(x > self.ceiling, 1, cdf_x))

    def ppf(self, q):
        """
        Percent point function (inverse of cdf) at q.
        """
        return oscipy.optimize.bisect(
            lambda x: self.cdf(x) - q,
            self.floor - 1e-9,
            self.ceiling + 1e-9,
            maxiter=1000,
        )

    def sample(self):
        raise NotImplementedError

    @classmethod
    def from_params(cls, fixed_params, opt_params, traceable=True):
        floor = fixed_params["floor"]
        ceiling = fixed_params["ceiling"]
        # Hardcode -2 and 3 for now since importing causes an import cycle
        loc_floor = floor + (ceiling - floor) * -2
        loc_ceiling = floor + (ceiling - floor) * 3
        structured_params = opt_params.reshape((-1, 3))
        locs = loc_floor + scipy.special.expit(structured_params[:, 0]) * (
            loc_ceiling - loc_floor
        )
        scales = np.abs(structured_params[:, 1])
        probs = list(nn.softmax(structured_params[:, 2]))
        component_dists = [Logistic(l, s) for (l, s) in zip(locs, scales)]
        return cls(component_dists, probs, floor, ceiling)

    @staticmethod
    def initialize_optimizable_params(fixed_params):
        """
        Each component has (location, scale, weight).
        The shape of the components matrix is (num_components, 3).
        Weights sum to 1 (are given in log space).
        We use original numpy to initialize parameters since we don't
        want to track randomness.
        """
        num_components = fixed_params["num_components"]
        scale_multiplier = 0.2
        loc_multiplier = 1
        locs = (onp.random.rand(num_components) - 0.5) * loc_multiplier
        scales = onp.random.rand(num_components) * scale_multiplier
        weights = onp.full(num_components, -num_components)
        components = onp.stack([locs, scales, weights]).transpose()
        return components.reshape(-1)

    @classmethod
    def from_conditions(cls, *args, init_tries=100, opt_tries=2, **kwargs):
        # Increase default initialization and optimization tries
        return super(TruncatedLogisticMixture, cls).from_conditions(
            *args, init_tries=init_tries, opt_tries=opt_tries, **kwargs
        )

    @classmethod
    def from_samples(cls, *args, init_tries=100, opt_tries=2, **kwargs):
        # Increase default initialization and optimization tries
        return super(TruncatedLogisticMixture, cls).from_samples(
            *args, init_tries=init_tries, opt_tries=opt_tries, **kwargs
        )

    def normalize(self, scale_min: float, scale_max: float):
        normalized_components = [
            component.normalize(scale_min, scale_max) for component in self.components
        ]
        s = scale.Scale(scale_min, scale_max)
        floor = s.normalize_point(self.floor)
        ceiling = s.normalize_point(self.ceiling)
        return self.__class__(normalized_components, self.probs, floor, ceiling)

    def denormalize(self, scale_min: float, scale_max: float):
        denormalized_components = [
            component.denormalize(scale_min, scale_max) for component in self.components
        ]
        s = scale.Scale(scale_min, scale_max)
        floor = s.denormalize_point(self.floor)
        ceiling = s.denormalize_point(self.ceiling)
        return self.__class__(denormalized_components, self.probs, floor, ceiling)

    @classmethod
    def normalize_fixed_params(self, fixed_params, scale_min: float, scale_max: float):
        s = scale.Scale(scale_min, scale_max)
        norm_fixed_params = dict(fixed_params)
        norm_fixed_params["floor"] = s.normalize_point(fixed_params["floor"])
        norm_fixed_params["ceiling"] = s.normalize_point(fixed_params["ceiling"])
        return norm_fixed_params

    def destructure(self):
        params = (
            [(c.loc, c.scale) for c in self.components],
            self.probs,
            (self.floor, self.ceiling),
        )
        return (TruncatedLogisticMixture, params)

    @classmethod
    def structure(cls, params):
        component_params, probs, limits = params
        components = [Logistic(l, s) for (l, s) in component_params]
        return cls(
            components=components, probs=probs, floor=limits[0], ceiling=limits[1]
        )
