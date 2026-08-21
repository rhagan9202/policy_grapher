"""The rebuild queue.

The only module that constructs a Redis connection. `Redis.from_url` does not
connect eagerly, which is what lets the application boot with Redis down — every
route but the two rebuild ones talks to Neo4j and is unaffected.
"""

from redis import Redis
from rq import Queue

from policy_grapher.config import Settings

# Repeated in docker-compose.yml, in the worker's `rq worker rebuilds` command
# — RQ's CLI takes queue names as arguments and cannot import this constant.
# Change one and you must change the other: a worker listening on a queue nobody
# writes to drains nothing while every route still answers 202.
QUEUE_NAME = "rebuilds"


def build_queue(settings: Settings) -> Queue:
    """The queue rebuild jobs are enqueued on.

    `default_timeout` is not decoration: a job that hangs without one holds a
    worker until the process is killed, and with a real model a rebuild
    legitimately runs for minutes, so there is no short timeout that is safe.

    There is deliberately no `result_ttl` here. RQ 2.11's `Queue.__init__` takes
    `**kwargs` and drops everything it does not recognise, so a `result_ttl=`
    passed to this constructor is accepted, ignored, and leaves every job on RQ's
    500-second default — a silent wrong answer. The TTL is a per-job property, so
    the route sets `rebuild_result_ttl_seconds` on the `enqueue` call instead.
    """
    return Queue(
        QUEUE_NAME,
        connection=Redis.from_url(settings.redis_url),
        default_timeout=settings.rebuild_job_timeout_seconds,
    )
