# ADR-040: A worker is alive if its heartbeat says so, not if a registry lists it

**Status:** Accepted · **Date:** 2026-09-09 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

Taken while diagnosing a rebuild reported dead on 2026-09-09, against the containerised
stack, on a run that was still working.

## Context

[ADR-023](ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)'s eight-hour job timeout
created a reporting problem that STORY-082 then had to solve. RQ moves an abandoned job to
failed only when its timeout expires, so a rebuild whose worker vanished reported `started`
for a working day with its progress frozen — observed 2026-08-27, stuck at 17 of 38 after a
worker container was replaced mid-run. The guard added then asked the direct-seeming question:
the job records the worker that took it, so is that worker still among the living?

It asked by scanning `Worker.all(connection=…)`. That reads RQ's **global** `rq:workers` set,
and the assumption underneath — that the set lists the workers which are alive — is false.

RQ keeps two registries, `rq:workers` and a per-queue `rq:workers:<name>`, and prunes them
asymmetrically. `Worker.find_by_key` removes a key whose heartbeat has lapsed from the global
set only:

```python
if not connection.exists(worker_key):
    connection.srem(cls.redis_workers_keys, worker_key)
    return None
```

The per-queue set is left alone, and nothing adds a worker back to the global set except
`register_birth`. So a single momentary lapse evicts a live worker from the global registry
for the rest of its life, while every other signal about it stays correct.

A rebuild is where that lapse is both likely and expensive. The heartbeat TTL while a job runs
is about ninety seconds, an open tab polls `GET /rebuilds/{run_id}` every thirty
([STORY-089](../../backlog/backlog.md)), and the run itself pins a CPU for an hour. Measured
on the live stack while a real run was 30 chunks into 41:

| | |
| --- | --- |
| `rq:workers` (global) | **did not exist** |
| `rq:workers:rebuilds` (per-queue) | held the worker |
| `rq:worker:<name>` (heartbeat) | present, TTL cycling 77→73 |
| container | `RestartCount=0`, no error in its log |
| chunks | still climbing |

The route reported `failed` — *"The worker running this rebuild is no longer alive"* — over a
run that went on to finish with 75 obligations and 119 proposals. Reporting a healthy run dead
is the worse of the two errors this guard can make: the screen then invites a second rebuild of
an edition already an hour into being built, and the reader's most likely response is to
abandon the first.

The test that should have caught it was
`test_a_run_on_a_live_worker_is_not_called_dead`, and it passed throughout. It asserted only
that a *queued* job with no worker name is not judged — so it never had a live worker in it at
all, and its name promised a guarantee its body did not make.

## Options considered

**Scan the per-queue registry instead** — `Worker.all(queue=queue)`. A one-word change, and it
would have been correct here: the per-queue set is pruned only when a key genuinely does not
exist. Rejected because it is right by accident. It still answers "is this worker in a set
somebody else maintains", and the reason that set is currently trustworthy is an implementation
detail of `find_by_key` that no contract obliges RQ to keep.

**Widen the guard to tolerate a lapse** — treat a worker as alive until it has been missing
from the registry for several consecutive polls. Rejected: it makes a wrong signal slower to
act on rather than making it right, and it needs state across requests that this route does not
have.

**Ask the worker's own heartbeat key.** Chosen.

## Decision

`read_rebuild` resolves liveness with `Worker.find_by_key`, on the key built from the job's
recorded `worker_name`:

```python
worker_key = Worker.redis_worker_namespace_prefix + job.worker_name
if Worker.find_by_key(worker_key, connection=queue.connection) is None:
```

`find_by_key` returns `None` exactly when that key is absent. RQ refreshes the key on every
heartbeat and lets it expire when the worker stops, so its presence *is* the liveness signal
rather than a cache of one. This depends on neither registry being consistent.

The guard's intent is unchanged and STORY-082's failure is still caught — a worker that is
genuinely gone has no heartbeat key, and
`test_a_run_whose_worker_died_reads_as_failed` still passes. What changed is the instrument.

## Consequences

**Makes easy.** The question the route asks is the question it means, and its answer does not
depend on maintenance RQ performs for its own reasons. A long rebuild — the case the eight-hour
timeout exists for, and the only case where being wrong costs an hour — is no longer the case
most likely to be misreported.

**Makes hard.** The key name is constructed from `Worker.redis_worker_namespace_prefix` rather
than handed over by an API that takes a worker name, so an RQ release that changes its key
layout would break this. `find_by_key` is public and raises `ValueError` on a key that does not
carry the prefix, so the failure would be loud rather than silent, and the prefix is read from
RQ rather than written out here.

**Commits us to.** Reading liveness from the heartbeat wherever we need it. A second consumer
asking `Worker.all()` would reintroduce exactly this defect somewhere else, and it would again
be invisible to a suite that never puts a live worker in front of the code.
