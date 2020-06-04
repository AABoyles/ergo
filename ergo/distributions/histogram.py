from dataclasses import dataclass
from functools import partial
from typing import List

from jax import grad, jit, nn
import jax.numpy as np
import numpy as onp
import scipy as oscipy

from . import conditions, distribution
from .scale import Scale


@dataclass
class HistogramDist(distribution.Distribution):
    logps: np.DeviceArray

    def __init__(
        self,
        logps=None,
        scale=None,
        normed_bins=None,
        true_bins=None,
        traceable=False,
        direct_init=None,
    ):
        if direct_init:
            self.logps = direct_init["logps"]
            self.ps = direct_init["ps"]
            self.cum_ps = direct_init["cum_ps"]
            self.normed_bins = direct_init["normed_bins"]
            self.size = direct_init["size"]
            self.scale = direct_init["scale"]
            self.true_bins = None  # self.scale.denormalize_points(self.normed_bins)
        else:
            init_numpy = np if traceable else onp
            self.logps = logps
            self.ps = np.exp(logps)
            self.cum_ps = np.array(init_numpy.cumsum(self.ps))
            self.size = logps.size
            self.scale = scale if scale else Scale(0, 1)

            if true_bins:
                self.true_bins = true_bins
                self.normed_bins = self.scale.normalize_points(self.true_bins)
            elif normed_bins:
                self.normed_bins = normed_bins
                self.true_bins = self.scale.denormalize_points(self.normed_bins)
            else:
                print(
                    "No bin information provided, assuming probabilities correspond to a linear spacing in [0,1]"
                )
                self.normed_bins = np.linspace(0, 1, self.logps.size)
                self.true_bins = self.scale.denormalize_points(self.normed_bins)

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, conditions.Condition):
            return self.__key() == other.__key()
        return NotImplemented

    def __key(self):
        return tuple(self.logps)

    def entropy(self):
        return -np.dot(self.ps, self.logps)

    def cross_entropy(self, q_dist):
        # Uncommented to support Jax tracing:
        # assert self.scale_min == q_dist.scale_min, (self.scale_min, q_dist.scale_min)
        # assert self.scale_max == q_dist.scale_max
        # assert self.size == q_dist.size, (self.size, q_dist.size)
        return -np.dot(self.ps, q_dist.logps)

    def pdf(self, x):
        return self.ps[np.argmax(self.normed_bins >= self.scale.normalize_point(x))]

    def cdf(self, x):
        return self.cum_ps[np.argmax(self.normed_bins >= self.scale.normalize_point(x))]

    def ppf(self, q):
        return self.scale.denormalize_point(
            np.where(self.cum_ps >= q)[0][0] / self.cum_ps.size
        )

    def sample(self):
        raise NotImplementedError

    def rv(self):
        raise NotImplementedError

    def normalize(self):
        raise NotImplementedError
        # return HistogramDist(self.logps, Scale(0, 1))

    def denormalize(self, scale: Scale):
        return HistogramDist(self.logps, scale)

    @classmethod
    def from_conditions(
        cls,
        conditions: List["conditions.Condition"],
        scale_cls,
        scale_params,
        num_bins=100,
        verbose=False,
    ):
        scale = scale_cls(*scale_params)
        normalized_conditions = [condition.normalize(scale) for condition in conditions]

        cond_data = [condition.destructure() for condition in normalized_conditions]
        if cond_data:
            cond_classes, cond_params = zip(*cond_data)
        else:
            cond_classes, cond_params = [], []

        loss = lambda params: static_loss(  # noqa: E731
            params, cond_classes, cond_params
        )
        jac = lambda params: static_loss_grad(  # noqa: E731
            params, cond_classes, cond_params
        )

        normalized_dist = cls.from_loss(loss=loss, jac=jac, num_bins=num_bins)

        if verbose:
            for condition in normalized_conditions:
                print(condition)
                print(condition.describe_fit(normalized_dist))

        return normalized_dist.denormalize(scale)

    @classmethod
    def from_loss(cls, loss, jac, num_bins=100):
        x0 = cls.initialize_params(num_bins)
        results = oscipy.optimize.minimize(loss, jac=jac, x0=x0)
        return cls.from_params(results.x)

    @classmethod
    def from_params(cls, params, traceable=False):
        logps = nn.log_softmax(params)
        return cls(logps, traceable=traceable)

    def destructure(self):
        return (
            HistogramDist,
            (self.logps, self.ps, self.cum_ps, self.normed_bins, self.size,),
            *self.scale.destructure(),
        )

    @classmethod
    def structure(cls, *params):
        print(f"direct init bins are:\n {params[3]}")
        return cls(
            direct_init={
                "logps": params[0],
                "ps": params[1],
                "cum_ps": params[2],
                "normed_bins": params[3],
                "size": params[4],
                "scale": params[5](*params[6]),
            }
        )

    @classmethod
    def from_pairs(cls, pairs, scale: Scale, normalized=False):
        sorted_pairs = sorted([(v["x"], v["density"]) for v in pairs])
        xs = [x for (x, density) in sorted_pairs]
        densities = [density for (x, density) in sorted_pairs]
        logps = onp.log(onp.array(densities) / sum(densities))
        if normalized:
            return cls(logps, scale, normed_bins=xs)
        else:
            return cls(logps, scale, true_bins=xs)

    def to_normalized_pairs(self):
        pairs = []
        bins = onp.array(self.normed_bins)
        ps = onp.array(self.ps)
        for i, bin in enumerate(bins[:-1]):
            x = float((bin + bins[i + 1]) / 2.0)
            bin_size = float(bins[i + 1] - bin)
            density = float(ps[i]) / bin_size
            pairs.append({"x": x, "density": density})
        return pairs

    def to_pairs(self):
        pairs = []
        bins = onp.array(self.true_bins)
        ps = onp.array(self.ps)
        for i, bin in enumerate(bins[:-1]):
            x = float((bin + bins[i + 1]) / 2.0)
            bin_size = float(bins[i + 1] - bin)
            density = float(ps[i]) / bin_size
            pairs.append({"x": x, "density": density})
        return pairs

    def to_lists(self):
        xs = []
        densities = []
        bins = onp.array(self.true_bins)
        ps = onp.array(self.ps)
        for i, bin in enumerate(bins[:-1]):
            x = float((bin + bins[i + 1]) / 2.0)
            bin_size = float(bins[i + 1] - bin)
            density = float(ps[i]) / bin_size
            xs.append(x)
            densities.append(density)
        return xs, densities

    def to_arrays(self):
        # TODO: vectorize
        xs, densities = self.to_lists()
        return np.array(xs), np.array(densities)

    @staticmethod
    def initialize_params(num_bins):
        return onp.full(num_bins, -num_bins)


def static_loss(dist_params, cond_classes, cond_params):
    total_loss = 0.0
    for (cond_class, cond_param) in zip(cond_classes, cond_params):
        total_loss += static_condition_loss(dist_params, cond_class, cond_param)
    return total_loss


def static_loss_grad(dist_params, cond_classes, cond_params):
    total_grad = 0.0
    for (cond_class, cond_param) in zip(cond_classes, cond_params):
        total_grad += static_condition_loss_grad(dist_params, cond_class, cond_param)
    return total_grad


@partial(jit, static_argnums=1)
def static_condition_loss(dist_params, cond_class, cond_param):
    print(f"Tracing condition loss for {cond_class.__name__} with params {cond_param}")
    dist = HistogramDist.from_params(dist_params, traceable=True)
    condition = cond_class.structure(cond_param)
    return condition.loss(dist) * 100


static_condition_loss_grad = jit(
    grad(static_condition_loss, argnums=0), static_argnums=1
)

# class LogHistogramDist(HistogramDist):

#     def change_base(new_base: float = 10):
#         # self.scale =
#         self.normed_bins = np.linspace(0, 1, logps.size + 1)
#         self.true_bins = self.scale.denormalize_points(self.normed_bins)
#         self.logps = logps
#         return
