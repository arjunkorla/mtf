"""Regression tests for the Redis test/live isolation fix (Phase 5): a
service-level test calling get_redis() directly must never be able to read
or write the same logical Redis DB the live application uses.

conftest.py rewrites REDIS_URL to a dedicated logical DB (15) before any
app.* module is imported, and flushes it before/after every test
(_isolated_redis_db, autouse). These tests prove that mechanism actually
isolates -- not just that it's configured to.
"""

from redis.asyncio import Redis

from app.config import get_settings
from app.db.redis_client import get_redis

# No module-level `pytestmark = pytest.mark.asyncio` here (unlike
# test_fno_service.py/test_global_macro_service.py, which are all-async):
# this file mixes one sync test with async ones, and asyncio_mode="auto"
# (pyproject.toml) already detects async tests on its own -- an explicit
# mark applied file-wide would incorrectly tag the sync test too.


def test_settings_points_at_a_dedicated_non_production_redis_db():
    redis_url = get_settings().redis_url
    assert redis_url.endswith("/15"), (
        f"test Settings.redis_url is {redis_url!r} -- expected the dedicated test DB (15), "
        "not whatever index production/docker-compose configures (0)"
    )
    assert not redis_url.endswith("/0")


async def test_a_key_written_during_a_test_never_reaches_the_production_db():
    """Writes through the app's real get_redis() (test DB 15), then connects
    directly to db 0 on the same server and proves the key is NOT there --
    physical isolation, not just "we didn't happen to collide"."""
    test_redis = get_redis()
    await test_redis.set("isolation_probe_key", "should-never-reach-db-0", ex=30)

    base_url = get_settings().redis_url.rsplit("/", 1)[0]
    prod_db = Redis.from_url(f"{base_url}/0", decode_responses=True)
    try:
        assert await prod_db.get("isolation_probe_key") is None
    finally:
        await prod_db.aclose()


async def test_autouse_fixture_flushes_state_between_tests_part_a():
    """Paired with part_b below: proves _isolated_redis_db's per-test flush
    actually runs, rather than tests happening to use disjoint keys."""
    redis = get_redis()
    await redis.set("cross_test_leak_probe", "leftover-from-part-a", ex=30)
    assert await redis.get("cross_test_leak_probe") == "leftover-from-part-a"


async def test_autouse_fixture_flushes_state_between_tests_part_b():
    redis = get_redis()
    assert await redis.get("cross_test_leak_probe") is None
