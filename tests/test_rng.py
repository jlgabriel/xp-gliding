import statistics

import pytest

from xp_gliding.engine.rng import SplitMix64, hash_key, mix64


def test_splitmix64_reference_values():
    # First outputs for seed 0 from the reference C implementation.
    rng = SplitMix64(0)
    assert rng.next_u64() == 0xE220A8397B1DCDAF
    assert rng.next_u64() == 0x6E789E6AA1B965F4
    assert rng.next_u64() == 0x06C45D188009454F


def test_hash_key_is_order_sensitive_and_handles_negatives():
    assert hash_key(1, 2) != hash_key(2, 1)
    assert hash_key(-1) == hash_key((1 << 64) - 1)
    assert 0 <= hash_key(-5, 7, 123) < (1 << 64)
    assert mix64(0) == 0


def test_distributions():
    rng = SplitMix64(42)
    u = [rng.uniform() for _ in range(20000)]
    assert min(u) >= 0.0 and max(u) < 1.0
    assert statistics.fmean(u) == pytest.approx(0.5, abs=0.01)
    p = [rng.poisson(3.5) for _ in range(20000)]
    assert statistics.fmean(p) == pytest.approx(3.5, abs=0.05)
    assert statistics.pvariance(p) == pytest.approx(3.5, abs=0.15)
    g = [rng.lognormal_unit_mean(0.3) for _ in range(20000)]
    assert min(g) > 0.0
    assert statistics.fmean(g) == pytest.approx(1.0, abs=0.01)
