"""What an operator is told when the stack cannot authenticate at boot.

No container: the failure being tested is the one where Neo4j is up, healthy and
answering -- and refusing the password. A real database with the right password
cannot produce it, so the driver is a stand-in whose only job is to raise what
Neo4j raises.
"""

import pytest
from neo4j.exceptions import AuthError

from policy_grapher.db import Neo4jAuthenticationRefused, verify_credentials


class _RefusingDriver:
    """A driver that fails the way a stale volume makes a real one fail."""

    def verify_connectivity(self):
        raise AuthError("{code: Neo.ClientError.Security.Unauthorized}")


class _WorkingDriver:
    def verify_connectivity(self):
        return None


def test_a_good_password_passes_through_silently():
    assert verify_credentials(_WorkingDriver()) is None


def test_a_refused_password_names_the_cause_and_the_fix():
    with pytest.raises(Neo4jAuthenticationRefused) as refusal:
        verify_credentials(_RefusingDriver())

    told = str(refusal.value)

    # The mechanism. Without this the reader checks the password -- the one
    # thing that is not wrong -- because every other signal says it is right.
    assert "NEO4J_AUTH is read only when Neo4j initialises an empty" in told
    assert "auth.ini" in told

    # The fix, and its cost. `down -v` is destructive and the graph holds
    # reviewed verdicts that nothing regenerates, so naming the command without
    # naming the loss would be a worse message, not a shorter one.
    assert "docker compose down -v" in told
    assert "verdicts" in told

    # The two signals that mislead. An operator who has already checked these
    # needs to be told they do not settle it.
    assert "docker compose config" in told
    assert "healthy" in told


def test_the_original_driver_error_is_kept_as_the_cause():
    """The hint replaces the driver's message in the raise, not in the traceback.

    A support question arrives as a pasted traceback, so the code Neo4j sent has
    to survive somewhere a reader can still see it.
    """
    with pytest.raises(Neo4jAuthenticationRefused) as refusal:
        verify_credentials(_RefusingDriver())

    assert isinstance(refusal.value.__cause__, AuthError)
    assert "Neo.ClientError.Security.Unauthorized" in str(refusal.value.__cause__)


def test_a_non_auth_failure_is_not_dressed_up_as_one():
    """Only an auth refusal gets the stale-volume story.

    An unreachable database, a wrong bolt port or a TLS failure are different
    problems with different fixes, and telling their reader to wipe the volume
    would cost them the graph for nothing.
    """

    class _UnreachableDriver:
        def verify_connectivity(self):
            raise OSError("connection refused")

    with pytest.raises(OSError):
        verify_credentials(_UnreachableDriver())
