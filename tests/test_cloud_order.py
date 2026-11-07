from xp_gliding.engine.cloud_order import FAR, HYSTERESIS_M, RING_EDGES_M, RingPool, ring_bounds, ring_of


def test_rings_go_out_from_the_glider_and_the_last_is_the_rest_of_the_sky():
    assert ring_of(0.0) == 0
    assert ring_of(RING_EDGES_M[0] - 1.0) == 0 and ring_of(RING_EDGES_M[0]) == 1
    assert ring_of(RING_EDGES_M[-1]) == FAR == ring_of(50000.0)
    assert ring_bounds(0) == (0.0, RING_EDGES_M[0])
    assert ring_bounds(FAR)[1] == float("inf")


def test_a_cloud_changes_ring_only_well_past_the_edge():
    edge = RING_EDGES_M[1]
    assert ring_of(edge + HYSTERESIS_M - 1.0, current=1) == 1
    assert ring_of(edge + HYSTERESIS_M, current=1) == 2
    assert ring_of(edge - HYSTERESIS_M, current=2) == 2
    assert ring_of(edge - HYSTERESIS_M - 1.0, current=2) == 1


def pool_of(sizes):
    pool = RingPool()
    rank = 0
    for ring, size in enumerate(sizes):
        for _ in range(size):
            rank += 1
            pool.add(ring, rank, f"i{rank}")
    return pool


def test_a_cloud_takes_an_instance_of_its_ring_about_as_old_as_it_is_near():
    pool = pool_of((3, 3, 3, 3))
    low, high = ring_bounds(1)
    assert pool.take(low) == (1, 4, "i4")  # nearest in the ring: the oldest left
    assert pool.take(high - 1.0) == (1, 6, "i6")  # farthest: the newest
    assert pool.take((low + high) / 2) == (1, 5, "i5")
    assert pool.misses == 0 and pool.count() == 9


def test_in_a_ring_with_clouds_one_goes_under_the_nearer_and_over_the_farther():
    pool = pool_of((0, 9, 0, 0))
    low, high = ring_bounds(1)
    # Two clouds came in at the outer edge one after the other, the first now nearer.
    first = pool.take(high - 10.0)
    assert first[1] == 9  # the newest: nothing else in the ring yet
    second = pool.take(high - 5.0, [(high - 400.0, first[1])])
    assert second[1] > first[1] or not any(rank > first[1] for rank, _ in pool.idle[1])
    # Room was left on the near side: a cloud nearer than the first goes over it.
    third = pool.take(low + 10.0, [(high - 400.0, first[1])])
    assert third[1] < first[1]
    # Between two of them, between their ranks.
    fourth = pool.take((low + high) / 2, [(low + 10.0, third[1]), (high - 400.0, first[1])])
    assert third[1] < fourth[1] < first[1]


def test_with_no_room_between_its_neighbours_a_cloud_takes_the_nearest_rank():
    pool = RingPool()
    for rank in (1, 2, 5, 6):
        pool.add(1, rank, f"i{rank}")  # 3 and 4 are its neighbours'
    assert pool.take(2000.0, [(1600.0, 3), (2900.0, 4)])[1] in (2, 5)
    pool = RingPool()
    pool.add(1, 1, "i1")
    assert pool.take(2000.0, [(1600.0, 5)]) == (1, 1, "i1")  # under the nearer one if it could
    pool.add(1, 9, "i9")
    assert pool.take(2000.0, [(2900.0, 5)]) == (1, 9, "i9")  # over the farther one if it could


def test_beyond_the_rings_a_cloud_gets_none():
    pool = pool_of((1, 1, 1, 1))
    assert pool.take(RING_EDGES_M[-1] + 1.0) is None
    assert pool.misses == 0


def test_with_its_ring_empty_a_cloud_takes_the_oldest_of_the_next_ring_out():
    pool = pool_of((1, 2, 0, 0))
    assert pool.take(100.0) == (0, 1, "i1")
    assert pool.take(100.0) == (1, 2, "i2")
    assert pool.misses == 1
    assert pool.take(100.0) == (1, 3, "i3")
    assert pool.take(100.0) is None
    assert pool.misses == 3


def test_an_instance_given_back_keeps_its_place_in_its_ring():
    pool = pool_of((0, 3, 0, 0))
    ring, rank, instance = pool.take(RING_EDGES_M[0])
    assert (ring, rank, instance) == (1, 1, "i1")
    pool.add(ring, rank, instance)
    assert pool.idle[1] == [(1, "i1"), (2, "i2"), (3, "i3")]


def test_cleared_it_hands_every_idle_instance_back_once():
    pool = pool_of((1, 2, 0, 1))
    assert sorted(pool.clear()) == ["i1", "i2", "i3", "i4"]
    assert pool.count() == 0 and pool.clear() == []
