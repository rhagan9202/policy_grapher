"""The rebuild queue.

The only module that constructs a Redis connection. `Redis.from_url` does not
connect eagerly, which is what lets the application boot with Redis down — every
route but the two rebuild ones talks to Neo4j and is unaffected.
"""

from redis import Redis
from rq import Queue

from policy_grapher.config import Settings

QUEUE_NAME = "rebuilds"


def build_queue(settings: Settings) -> Queue:
    """The queue rebuild jobs are enqueued on.

    `default_timeout` is not decoration: a job that hangs without one holds a
    worker until the process is killed, and with a real model a rebuild
    legitimately runs for minutes, so there is no short timeout that is safe.
    """
    return Queue(
        QUEUE_NAME,
        connection=Redis.from_url(settings.redis_url),
        default_timeout=settings.rebuild_job_timeout_seconds,
    )
