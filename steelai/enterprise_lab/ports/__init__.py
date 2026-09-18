"""Ports of the Enterprise Lab: the interfaces the inside of the hexagon owns.

Every port is a ``typing.Protocol``, so an adapter is replaceable and needs no
inheritance.

Implemented replacement map:

===============  ===========================  ==========================================
Port             In-memory adapter            Database / delivery adapter
===============  ===========================  ==========================================
RunRepository    MemoryRunRepository          PostgreSQL (T82, Done)
AuditRepository  MemoryAuditRepository        PostgreSQL append-only (T82, Done)
ArtifactStore    MemoryArtifactStore          index row + file/object store (T82, Done)
EventPublisher   MemoryEventPublisher         Transactional Outbox write side (T82, Done)
JobQueue         MemoryJobQueue               PostgreSQL-backed queue (T82, Done)
UnitOfWork       MemoryUnitOfWork             PostgreSQL transaction (T82, Done)
EventTransport   RecordingEventTransport      outbox dispatcher (T83, Review); Kafka is
                                              **not** implemented
===============  ===========================  ==========================================

The delivery port in :mod:`steelai.enterprise_lab.ports.outbox` belongs to the outbox
dispatcher: it carries claim, acknowledge and lease-recovery semantics, and its delivery
state never enters ``DomainEvent``.

The execution port in :mod:`steelai.enterprise_lab.ports.workers` belongs to the background
job worker: it carries its own ``lease_id`` plus the ``attempt`` fencing token, heartbeat and
expiry recovery, so the distributed-worker semantics never leak into the frozen
``JobQueue`` port. A Kafka publisher, a FastAPI layer and a resident worker service remain
future work and must not be described as present.
"""
from .artifacts import ArtifactStore
from .events import EventPublisher, replay_events
from .jobs import JobQueue
from .outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
    DELIVERY_STATUSES,
    ERROR_OUTBOX_CLAIM,
    ERROR_OUTBOX_CONFIG,
    ERROR_OUTBOX_LEASE_EXPIRED,
    ERROR_OUTBOX_TRANSPORT,
    EventTransport,
    OutboxClaim,
    OutboxDeliveryRepository,
    OutboxDeliveryState,
    OutboxReclaim,
    TransportError,
    is_safe_error_code,
)
from .repositories import AuditRepository, RunFilters, RunRepository, UnitOfWork
from .workers import (
    ERROR_WORKER_CLAIM,
    ERROR_WORKER_CONFIG,
    ERROR_WORKER_EXECUTION,
    ERROR_WORKER_HANDLER_NOT_FOUND,
    ERROR_WORKER_LEASE_EXPIRED,
    JobExecutionContext,
    JobExecutionRepository,
    JobExecutionState,
    JobHandler,
    JobHandlerError,
    JobHandlerRegistry,
    JobLease,
)

__all__ = [
    "ArtifactStore",
    "AuditRepository",
    "DELIVERY_FAILED",
    "DELIVERY_PENDING",
    "DELIVERY_PUBLISHED",
    "DELIVERY_PUBLISHING",
    "DELIVERY_STATUSES",
    "ERROR_OUTBOX_CLAIM",
    "ERROR_OUTBOX_CONFIG",
    "ERROR_OUTBOX_LEASE_EXPIRED",
    "ERROR_OUTBOX_TRANSPORT",
    "ERROR_WORKER_CLAIM",
    "ERROR_WORKER_CONFIG",
    "ERROR_WORKER_EXECUTION",
    "ERROR_WORKER_HANDLER_NOT_FOUND",
    "ERROR_WORKER_LEASE_EXPIRED",
    "EventPublisher",
    "EventTransport",
    "JobExecutionContext",
    "JobExecutionRepository",
    "JobExecutionState",
    "JobHandler",
    "JobHandlerError",
    "JobHandlerRegistry",
    "JobLease",
    "JobQueue",
    "OutboxClaim",
    "OutboxDeliveryRepository",
    "OutboxDeliveryState",
    "OutboxReclaim",
    "RunFilters",
    "RunRepository",
    "TransportError",
    "UnitOfWork",
    "is_safe_error_code",
    "replay_events",
]
