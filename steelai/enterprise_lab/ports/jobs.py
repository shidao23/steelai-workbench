"""Background-job queue port.

T80 defines the queue contract and the legal job-state transitions. It
implements no concurrent worker, no scheduler and no distributed lease: the
in-memory adapter exists so that the interface is executable and testable.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..domain.models import BackgroundJob


@runtime_checkable
class JobQueue(Protocol):
    """Background-job lifecycle.

    Contract:

    - ``enqueue`` resolves identity through an idempotency index that binds one
      ``idempotency_key`` to one ``job_id`` and one request digest: the same key
      with the same request reuses the job (``reused=True``), while the same key
      with a different ``job_id`` or a different request, and the same
      ``job_id`` with a different key, fail closed with the duplicate error;
    - ``lease`` hands one queued or retrying job to a worker and counts the
      attempt;
    - ``complete`` and ``fail`` only accept a leased job; ``retry`` moves a
      failed job to ``retrying`` while attempts remain;
    - every illegal transition fails closed.
    """

    def enqueue(self, job: BackgroundJob) -> tuple[BackgroundJob, bool]:
        ...

    def lease(self, *, job_type: str | None = None) -> BackgroundJob | None:
        ...

    def complete(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        ...

    def fail(self, job_id: str, *, error_code: str, updated_at: str | None = None) -> BackgroundJob:
        ...

    def retry(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        ...

    def cancel(self, job_id: str, *, updated_at: str | None = None) -> BackgroundJob:
        ...

    def get(self, job_id: str) -> BackgroundJob | None:
        ...

    def list_jobs(self) -> Sequence[BackgroundJob]:
        ...


__all__ = ["JobQueue"]
