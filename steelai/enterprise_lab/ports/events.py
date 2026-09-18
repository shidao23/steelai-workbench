"""Domain-event publishing port.

The publisher carries structured domain events only: IDs, states, versions,
hashes and a redacted summary. It is not an RPC channel, it never carries large
files and it never executes scientific computation.

A future Kafka adapter must sit behind a Transactional Outbox and reuse
``replay_events`` to prove the recorded order is intact.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..domain.models import DomainEvent


@runtime_checkable
class EventPublisher(Protocol):
    """Structured event publication with per-run ordered replay.

    Contract:

    - ``publish`` assigns a strictly increasing per-run sequence or the caller
      supplies one; a duplicated or out-of-order sequence fails closed;
    - ``replay`` returns the events of a run in creation order;
    - publishing is append-only: a published event is never rewritten.
    """

    def publish(self, event: DomainEvent) -> DomainEvent:
        ...

    def next_sequence(self, run_id: str) -> int:
        ...

    def replay(self, run_id: str) -> Sequence[DomainEvent]:
        ...

    def count(self) -> int:
        ...


def replay_events(repository: EventPublisher, run_id: str) -> list[dict]:
    """Return a replayable, order-preserving projection of a run's events."""
    return [event.to_dict() for event in repository.replay(run_id)]


__all__ = ["EventPublisher", "replay_events"]
