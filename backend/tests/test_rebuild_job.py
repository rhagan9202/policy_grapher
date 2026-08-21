from policy_grapher.config import Settings
from policy_grapher.jobs.queue import QUEUE_NAME, build_queue


def test_the_queue_is_named_and_carries_a_timeout():
    """A job with no timeout that hangs holds a worker until the process dies."""
    queue = build_queue(Settings(_env_file=None))

    assert queue.name == QUEUE_NAME
    # Private on purpose: RQ 2.11 exposes the class constant `Queue.DEFAULT_TIMEOUT`
    # but no public accessor for the value a queue was constructed with, and
    # asserting the constant would test RQ rather than this code.
    assert queue._default_timeout == 1800


def test_building_the_queue_does_not_connect():
    """Redis being down must fail only the rebuild routes — the app still boots,
    so constructing the queue cannot reach out to the server."""
    queue = build_queue(
        Settings(_env_file=None, redis_url="redis://not-a-host.invalid:6379/0")
    )

    assert queue is not None
