"""Application layer of the Enterprise Lab.

Use cases orchestrate ports only. There is no adapter import, no database call, no HTTP
handler and no broker client in this layer.

Two use cases live here:

- :class:`~steelai.enterprise_lab.application.services.EnterpriseWorkflowService` runs the
  minimal vertical workflow (run, artifacts, audit, events, jobs) through the ports;
- :class:`~steelai.enterprise_lab.application.outbox_dispatcher.OutboxDispatcher` performs
  the bounded outbox delivery loop (claim, send outside any transaction, acknowledge,
  recover expired leases). It is a finite call, not a daemon: there is no timer, no
  scheduler and no resident worker.
- :class:`~steelai.enterprise_lab.application.job_worker.JobWorker` performs the bounded
  background-job execution loop (claim a lease, run the handler outside any transaction,
  heartbeat on demand, confirm the result, recover expired leases). It is also a finite
  call: there is no ``run_forever``, no timer and no background thread.
"""
from .job_worker import (
    OUTCOME_FAILURE_UNRECORDED,
    OUTCOME_FAILED_TERMINAL,
    OUTCOME_PROPERTIES,
    OUTCOME_RETRY_SCHEDULED,
    OUTCOME_STATUSES,
    OUTCOME_SUCCEEDED,
    OUTCOME_SUCCESS_UNRECORDED,
    PERSISTED_FIELDS,
    JobOutcome,
    JobWorker,
    JobWorkerConfig,
    default_lease_id,
)
from .outbox_dispatcher import (
    OUTCOME_PROPERTIES as OUTBOX_OUTCOME_PROPERTIES,
    OUTCOME_STATUSES as OUTBOX_OUTCOME_STATUSES,
    STATUS_FAILED,
    STATUS_FAILURE_UNRECORDED,
    STATUS_PUBLISHED,
    STATUS_RETRY_SCHEDULED,
    STATUS_SENT_UNACKNOWLEDGED,
    OutboxDispatchOutcome,
    OutboxDispatcher,
    OutboxDispatcherConfig,
)
from .services import (
    AuditEntryRequest,
    EnterpriseWorkflowService,
    RunArtifactRequest,
    UnitOfWorkFactory,
    WorkflowRunRequest,
    WorkflowRunResult,
    start_workflow_run,
)

__all__ = [
    "AuditEntryRequest",
    "EnterpriseWorkflowService",
    "JobOutcome",
    "JobWorker",
    "JobWorkerConfig",
    "OUTBOX_OUTCOME_PROPERTIES",
    "OUTBOX_OUTCOME_STATUSES",
    "OUTCOME_FAILURE_UNRECORDED",
    "OUTCOME_FAILED_TERMINAL",
    "OUTCOME_PROPERTIES",
    "OUTCOME_RETRY_SCHEDULED",
    "OUTCOME_STATUSES",
    "OUTCOME_SUCCEEDED",
    "OUTCOME_SUCCESS_UNRECORDED",
    "PERSISTED_FIELDS",
    "OutboxDispatchOutcome",
    "OutboxDispatcher",
    "OutboxDispatcherConfig",
    "RunArtifactRequest",
    "STATUS_FAILED",
    "STATUS_FAILURE_UNRECORDED",
    "STATUS_PUBLISHED",
    "STATUS_RETRY_SCHEDULED",
    "STATUS_SENT_UNACKNOWLEDGED",
    "UnitOfWorkFactory",
    "WorkflowRunRequest",
    "WorkflowRunResult",
    "default_lease_id",
    "start_workflow_run",
]
