"""Stable governance errors shared by every SteelAI workspace."""
from __future__ import annotations

from typing import Any


class GovernanceError(ValueError):
    """A fail-closed governance decision with a stable code and target state."""

    def __init__(
        self,
        code: str,
        state: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.state = state
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }
