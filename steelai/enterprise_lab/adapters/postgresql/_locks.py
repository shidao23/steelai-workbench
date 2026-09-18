"""Stable advisory-lock keys for the PostgreSQL adapter (T82).

PostgreSQL advisory locks need a 64-bit integer. Deriving it from a stable digest
(rather than Python's ``hash()``, which is salted per process) keeps the key
identical across processes, restarts and platforms.

Every key carries a fixed SteelAI/T82 namespace prefix, which reduces the chance of
an accidental collision with another application's advisory locks in the same
database. That is a mitigation, not a guarantee: two different applications can
still choose the same namespace and identity.

Only two lock scopes exist - the global audit append order and the per-run outbox
sequence. Job leasing deliberately uses no advisory lock: it relies on
``FOR UPDATE SKIP LOCKED`` so two transactions can lease different rows at the same
time.
"""
from __future__ import annotations

import hashlib


#: Namespace prefix folded into every key, so the two-int form is not needed.
LOCK_NAMESPACE = "steelai-t82-enterprise-lab"

#: Human-readable lock scopes. They are part of the key, so a future scope cannot
#: accidentally reuse an existing key.
LOCK_SCOPE_AUDIT_SEQUENCE = "audit-sequence"
LOCK_SCOPE_EVENT_SEQUENCE = "outbox-sequence"

#: Signed 64-bit range accepted by ``pg_advisory_xact_lock(bigint)``.
_SIGNED_64_MAX = (1 << 63) - 1


def advisory_lock_key(scope: str, *parts: object) -> int:
    """Return a stable signed 64-bit advisory-lock key.

    The key is the first eight bytes of a SHA-256 over the namespace, the scope and
    the caller's identity parts. It is deterministic for the same inputs in any
    process, which is what makes it safe for cross-process serialization.
    """
    seed = "\x1f".join([LOCK_NAMESPACE, scope, *(str(part) for part in parts)])
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % (_SIGNED_64_MAX + 1)


def audit_sequence_lock_key() -> int:
    """One key for the global audit append order."""
    return advisory_lock_key(LOCK_SCOPE_AUDIT_SEQUENCE)


def event_sequence_lock_key(run_id: str) -> int:
    """One key per run for the outbox sequence."""
    return advisory_lock_key(LOCK_SCOPE_EVENT_SEQUENCE, run_id)


__all__ = [
    "LOCK_NAMESPACE",
    "LOCK_SCOPE_AUDIT_SEQUENCE",
    "LOCK_SCOPE_EVENT_SEQUENCE",
    "advisory_lock_key",
    "audit_sequence_lock_key",
    "event_sequence_lock_key",
]
