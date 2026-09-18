"""Adapters of the Enterprise Lab: replaceable implementations of the ports.

Two adapter sets live here:

- the pure in-memory implementation of the T80 ports (no filesystem, database, broker or
  network dependency);
- the offline delivery and execution adapters with their recording doubles:
  :mod:`steelai.enterprise_lab.adapters.outbox_memory` (T83 delivery side) and
  :mod:`steelai.enterprise_lab.adapters.worker_memory` (T84 background job execution).
  Both are in-memory and perform no I/O.

This module deliberately does **not** import :mod:`steelai.enterprise_lab.adapters.postgresql`:
that package needs the optional dependencies of ``requirements-enterprise.txt``
(SQLAlchemy, Alembic, Psycopg), so an installation without them keeps working. Import the
PostgreSQL adapter explicitly when it is wanted. Kafka, a resident worker service and a
FastAPI layer remain future work and must not be described as present.
"""
from .memory import (
    MemoryArtifactStore,
    MemoryAuditRepository,
    MemoryEventPublisher,
    MemoryJobQueue,
    MemoryRunRepository,
    MemoryStore,
    MemoryUnitOfWork,
    MemoryUnitOfWorkFactory,
)
from .outbox_memory import (
    MemoryOutboxDeliveryRepository,
    RecordedSend,
    RecordingEventTransport,
)
from .worker_memory import (
    MemoryJobExecutionRepository,
    RecordedJobCall,
    RecordingJobHandler,
)

__all__ = [
    "MemoryArtifactStore",
    "MemoryAuditRepository",
    "MemoryEventPublisher",
    "MemoryJobExecutionRepository",
    "MemoryJobQueue",
    "MemoryOutboxDeliveryRepository",
    "MemoryRunRepository",
    "MemoryStore",
    "MemoryUnitOfWork",
    "MemoryUnitOfWorkFactory",
    "RecordedJobCall",
    "RecordedSend",
    "RecordingEventTransport",
    "RecordingJobHandler",
]
