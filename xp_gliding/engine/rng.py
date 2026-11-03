"""Portable deterministic random numbers.

The sky must be reproducible from (seed, day, place): the same inputs give the
same thermals on every machine, Python version and, later, a C++ port. Python's
`random` module only guarantees `random()` across versions, and seeding it from
a tuple goes through a hash, so the engine uses its own tiny generator instead:
splitmix64 (Steele, Lea and Flood, 2014), which is a few lines in any language.

Every distribution used by the engine is built here on top of `uniform()`.
"""

import math

MASK64 = (1 << 64) - 1
GOLDEN_GAMMA = 0x9E3779B97F4A7C15


def mix64(z):
    """splitmix64 finalizer: a 64-bit integer -> a well-mixed 64-bit integer."""
    z &= MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def hash_key(*parts):
    """Combine integers (any sign) into one 64-bit key, order-sensitive."""
    h = 0x6A09E667F3BCC908
    for p in parts:
        h = mix64(h ^ (int(p) & MASK64))
    return h


class SplitMix64:
    __slots__ = ("state",)

    def __init__(self, seed):
        self.state = int(seed) & MASK64

    def next_u64(self):
        self.state = (self.state + GOLDEN_GAMMA) & MASK64
        return mix64(self.state)

    def uniform(self):
        """Uniform float in [0, 1) with 53 random bits."""
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def uniform_range(self, lo, hi):
        return lo + (hi - lo) * self.uniform()

    def poisson(self, lam):
        """Poisson-distributed count by inversion (fine for lam up to a few hundred)."""
        if lam <= 0.0:
            return 0
        if lam > 500.0:
            # Normal approximation keeps the loop bounded for huge areas.
            return max(0, round(lam + math.sqrt(lam) * self.normal()))
        u = self.uniform()
        k = 0
        p = math.exp(-lam)
        cdf = p
        while u > cdf:
            k += 1
            p *= lam / k
            cdf += p
            if p == 0.0:
                break
        return k

    def normal(self):
        """Standard normal by Box-Muller (one value per call, the other is dropped)."""
        u1 = 1.0 - self.uniform()  # (0, 1]
        u2 = self.uniform()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def lognormal_unit_mean(self, sigma):
        """Positive multiplier with mean 1 and log-standard-deviation sigma."""
        return math.exp(sigma * self.normal() - 0.5 * sigma * sigma)
