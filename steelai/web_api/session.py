"""WO-32 §2 — 最小本地会话能力（不上 SSO、不建常驻认证服务）。

服务只监听回环，所以这里要解决的**不是**「防住远程攻击者」，而是把三种调用方
在本地区分开，并让"能不能人审"这件事由服务端决定：

``browser``  内置 React 页面。必须带可信 ``Origin``（同源 POST 一定会带），
             拿到的人员能力，包含 ``review:human``。
``ai``       另一个 AI/脚本，直接从回环调用（没有 Origin 或者 Origin 不同）。
             只有读、建议与「获准后执行」的能力；**没有人审、没有写任务/上传/接手**。

要点：

* 客户端只能**请求**一种 client 类型，权限由服务端授予；请求里的
  ``reviewer``/``actor`` 字符串**不授予任何权限**。
* token 只存在进程内存里，TLS 之外不上传、不落盘；进程重启即全部失效，
  前端会自动重新申请（这不是缺陷，是本地最小面）。
* 未知 / 过期 / 缺能力的 token 一律拒绝，不接受"顺带放行"。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from steelai.web_api.security import GuardError, check_origin

CLIENT_KINDS = ("browser", "ai")
DEFAULT_TTL_HOURS = 12

READ_CAPS = ("projects:read", "tasks:read", "files:read", "preview:read",
             "runs:read", "artifacts:read", "tools:list")

# 内置页面（人）。
BROWSER_CAPABILITIES = READ_CAPS + (
    "tasks:write", "files:write", "runs:create", "handoff:write", "review:human",
)
# 本地 AI：读 / 建议 / 获准后执行；不能人审、不能写任务与上传。
AI_CAPABILITIES = READ_CAPS + ("runs:create",)


@dataclass(frozen=True)
class Session:
    session_id: str
    client: str
    actor_kind: str            # "human-browser" | "ai-assistant"
    capabilities: tuple[str, ...]
    issued_at: str
    expires_at: str
    origin: str


_LOCK = threading.Lock()
_STORE: dict[str, Session] = {}


def capabilities_for(client: str) -> tuple[str, ...]:
    """The capability set the server grants for a client type.

    A caller may *ask* for a client type but never choose its capability set:
    this function is the single place that decides what each kind may do.
    """
    if client == "browser":
        return BROWSER_CAPABILITIES
    if client == "ai":
        return AI_CAPABILITIES
    raise GuardError(f"未知客户端类型：{client}（可选：{'、'.join(CLIENT_KINDS)}）")


def issue(client: str, *, origin: str | None, allowed_origins: Iterable[str],
         ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    """Issue a local capability token; never trust a caller-supplied role."""
    client = str(client or "").strip().lower()
    if client not in CLIENT_KINDS:
        raise GuardError(f"未知客户端类型：{client}（可选：{'、'.join(CLIENT_KINDS)}）")
    allowed = tuple(allowed_origins)
    if client == "browser":
        # 内置页面的写操作来自同源 POST，浏览器一定会带 Origin；没有 Origin
        # 就无法证明"是从内置页面来的"，此时不给人员能力。
        if not origin or not check_origin(origin, allowed):
            raise GuardError("浏览器会话必须从内置页面（可信 Origin）发起；"
                            "本地 AI 请改用 client=ai")
    granted = capabilities_for(client)
    now = datetime.now()
    token = secrets.token_urlsafe(32)
    record = Session(
        session_id=token[:12],
        client=client,
        actor_kind="human-browser" if client == "browser" else "ai-assistant",
        capabilities=granted,
        issued_at=now.isoformat(timespec="seconds"),
        expires_at=(now + timedelta(hours=ttl_hours)).isoformat(timespec="seconds"),
        origin=str(origin or ""),
    )
    with _LOCK:
        _prune(now)
        _STORE[token] = record
    return {
        "token": token,
        "session": record.as_dict(),
    }


def _prune(now: datetime) -> None:
    for token, record in list(_STORE.items()):
        try:
            if datetime.fromisoformat(record.expires_at) <= now:
                _STORE.pop(token, None)
        except (ValueError, TypeError):  # pragma: no cover - defensive
            _STORE.pop(token, None)


def verify(token: str) -> Session:
    """Return the session for *token* or refuse (unknown/expired/malformed)."""
    raw = str(token or "").strip()
    if not raw:
        raise GuardError("缺少会话令牌")
    if len(raw) > 200 or any(ch.isspace() for ch in raw):
        raise GuardError("会话令牌格式不正确")
    with _LOCK:
        record = _STORE.get(raw)
        if record is None:
            raise GuardError("会话不存在或已失效（重启进程后需重新申请）")
        try:
            expired = datetime.fromisoformat(record.expires_at) <= datetime.now()
        except ValueError:  # pragma: no cover - defensive
            raise GuardError("会话记录损坏，请重新申请") from None
        if expired:
            _STORE.pop(raw, None)
            raise GuardError("会话已过期，请重新申请")
    return record


def require(token: str, capability: str) -> Session:
    record = verify(token)
    if capability not in record.capabilities:
        raise GuardError(
            f"该会话没有此能力：{capability}（当前 {record.actor_kind}）。"
            "人工确认、写任务/上传/接手只能由内置页面的具名人工会话完成。")
    return record


def _as_dict(record: Session) -> dict:
    return {
        "session_id": record.session_id,
        "client": record.client,
        "actor_kind": record.actor_kind,
        "capabilities": list(record.capabilities),
        "issued_at": record.issued_at,
        "expires_at": record.expires_at,
        "origin": record.origin,
    }


def active_count() -> int:
    with _LOCK:
        _prune(datetime.now())
        return len(_STORE)


def revoke_all() -> None:
    with _LOCK:
        _STORE.clear()


# 让 dataclass 有一个稳定的 as_dict（保持与 API 其它部分一致）。
def _session_as_dict(self: Session) -> dict:  # pragma: no cover - patch helper
    return _as_dict(self)


if not hasattr(Session, "as_dict"):  # pragma: no cover
    Session.as_dict = _session_as_dict  # type: ignore[attr-defined]
