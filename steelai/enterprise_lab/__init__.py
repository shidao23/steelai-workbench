"""SteelAI Enterprise Lab (T80 boundary, T82 PostgreSQL adapter, T83 outbox dispatcher).

This package is an **optional extension**. Nothing in ``app.py``, ``pages/`` or the
scientific modules imports it, so the current Streamlit application and the
deterministic research pipeline keep working with no enterprise dependency,
service or configuration present.

Implemented so far:

- T80: interfaces plus one pure in-memory adapter;
- T82: an optional PostgreSQL adapter (schema-driven repositories and the transactional
  outbox **write** side), which needs the extra packages of
  ``requirements-enterprise.txt`` and is therefore **not** imported here;
- T83: an optional outbox **dispatcher** with lease recovery and at-least-once delivery,
  plus the in-memory delivery adapter and the recording transport used offline and in
  tests;
- T84: an optional background **job worker** with its own lease identity, heartbeat,
  ``job_id + lease_id + attempt`` fencing and expired-lease recovery, plus the in-memory
  execution adapter and the recording handler used offline and in tests. It keeps the T82
  ``JobQueue`` untouched and adds no new job state.

Not implemented: Kafka or any real broker, a resident worker or scheduler, a FastAPI layer,
RBAC, multi-tenancy, monitoring and a replay console. Delivery is **at-least-once**, never
exactly-once, and none of this may be described as providing those.

Boundary summary (see ``docs/enterprise/ADR-0001_ENTERPRISE_LAB_BOUNDARY.md``):

- ``domain``       stable IDs, versions, states and content digests; no I/O
- ``application``  use-case orchestration over ports only; no I/O
- ``ports``        replaceable interfaces owned by the inside of the hexagon
- ``adapters``     replaceable implementations owned by the outside

Dependency rule: ``domain`` <- ``application`` -> ``ports`` <- ``adapters``.
Inward layers never import outward layers. This module exports only types that need no
optional PostgreSQL dependency: importing ``steelai.enterprise_lab`` must never pull in
SQLAlchemy, Alembic or Psycopg.
"""
from .adapters.outbox_memory import MemoryOutboxDeliveryRepository, RecordingEventTransport
from .adapters.worker_memory import (
    MemoryJobExecutionRepository,
    RecordedJobCall,
    RecordingJobHandler,
)
from .application.outbox_dispatcher import (
    STATUS_FAILED,
    STATUS_FAILURE_UNRECORDED,
    STATUS_PUBLISHED,
    STATUS_RETRY_SCHEDULED,
    STATUS_SENT_UNACKNOWLEDGED,
    OutboxDispatchOutcome,
    OutboxDispatcher,
    OutboxDispatcherConfig,
)
from .application.job_worker import (
    OUTCOME_FAILURE_UNRECORDED,
    OUTCOME_FAILED_TERMINAL,
    OUTCOME_RETRY_SCHEDULED,
    OUTCOME_SUCCEEDED,
    OUTCOME_SUCCESS_UNRECORDED,
    JobOutcome,
    JobWorker,
    JobWorkerConfig,
)
from .application.services import (
    AuditEntryRequest,
    EnterpriseWorkflowService,
    RunArtifactRequest,
    UnitOfWorkFactory,
    WorkflowRunRequest,
    WorkflowRunResult,
    start_workflow_run,
)
from .domain.models import (
    ArtifactReference,
    AuditEvent,
    BackgroundJob,
    DomainEvent,
    EnterpriseProject,
    JobState,
    WorkflowRun,
)
from .ports.artifacts import ArtifactStore
from .ports.events import EventPublisher
from .ports.jobs import JobQueue
from .ports.outbox import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_PUBLISHED,
    DELIVERY_PUBLISHING,
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
)
from .ports.repositories import AuditRepository, RunFilters, RunRepository, UnitOfWork
from .ports.workers import (
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
    "ArtifactReference",
    "ArtifactStore",
    "AuditEntryRequest",
    "AuditEvent",
    "AuditRepository",
    "BackgroundJob",
    "DELIVERY_FAILED",
    "DELIVERY_PENDING",
    "DELIVERY_PUBLISHED",
    "DELIVERY_PUBLISHING",
    "DomainEvent",
    "ERROR_OUTBOX_CLAIM",
    "ERROR_OUTBOX_CONFIG",
    "ERROR_OUTBOX_LEASE_EXPIRED",
    "ERROR_OUTBOX_TRANSPORT",
    "ERROR_WORKER_CLAIM",
    "ERROR_WORKER_CONFIG",
    "ERROR_WORKER_EXECUTION",
    "ERROR_WORKER_HANDLER_NOT_FOUND",
    "ERROR_WORKER_LEASE_EXPIRED",
    "EnterpriseProject",
    "EnterpriseWorkflowService",
    "EventPublisher",
    "EventTransport",
    "JobExecutionContext",
    "JobExecutionRepository",
    "JobExecutionState",
    "JobHandler",
    "JobHandlerError",
    "JobHandlerRegistry",
    "JobLease",
    "JobOutcome",
    "JobQueue",
    "JobWorker",
    "JobWorkerConfig",
    "JobState",
    "MemoryJobExecutionRepository",
    "MemoryOutboxDeliveryRepository",
    "OutboxClaim",
    "OutboxDeliveryRepository",
    "OutboxDeliveryState",
    "OutboxDispatchOutcome",
    "OutboxDispatcher",
    "OutboxDispatcherConfig",
    "OutboxReclaim",
    "OUTCOME_FAILURE_UNRECORDED",
    "OUTCOME_FAILED_TERMINAL",
    "OUTCOME_RETRY_SCHEDULED",
    "OUTCOME_SUCCEEDED",
    "OUTCOME_SUCCESS_UNRECORDED",
    "RecordedJobCall",
    "RecordingEventTransport",
    "RecordingJobHandler",
    "RunArtifactRequest",
    "RunFilters",
    "RunRepository",
    "STATUS_FAILED",
    "STATUS_FAILURE_UNRECORDED",
    "STATUS_PUBLISHED",
    "STATUS_RETRY_SCHEDULED",
    "STATUS_SENT_UNACKNOWLEDGED",
    "TransportError",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "WorkflowRun",
    "WorkflowRunRequest",
    "WorkflowRunResult",
    "start_workflow_run",
]
