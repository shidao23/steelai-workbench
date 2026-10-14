"""WO-32 §2 / WO-33 §3 — 最小本地会话能力（不上 SSO、不建常驻认证服务）。

服务只监听回环，所以这里要解决的**不是**「防住远程攻击者」，而是把调用方
在本地区分开，并让"能不能人审"这件事由**本地受信任入口**决定，而不是由请求
里可以自填的字符串决定：

``browser``  内置 React 页面。必须 (a) 来自可信 ``Origin``，且 (b) 提交一次
             由服务器生成、只经本地受信任通道展示、**一次性**的配对码。
             只有这样才拿到 ``review:human`` 等人身能力。
``ai``       另一个 AI/脚本，直接从回环调用。只有读、建议与「获准后执行」的
             能力；**没有人审、没有写任务/上传/接手**。

WO-33 §3 修的就是这一点：WO-32 只要 ``client=browser`` + 一个可以自己填的
``Origin`` 头就发人审能力，普通 HTTP 脚本也能领到。现在：

* ``Origin`` 仍然保留，作为**跨站防护**（挡住别的网站替本机发 POST），
  但它**不是**身份认证；
* 人审能力只由 :func:`exchange` 授予——需要服务器生成、写在本地文件里的
  一次性配对码；码用过即作废并轮换，重复使用会被拒绝；
* 普通 AI/脚本新申请 ``client=browser``、已有 AI 令牌改 ``client``/``role``、
  伪造 ``Origin``，都**不能**升级成人审；
* 令牌只存在进程内存里，进程重启即全部失效（前端会重新走一次配对）。

**能力边界要说清**：这一层只能控制本 API 的能力授予。它挡不住一个已经拥有
同一个 Windows 账号全部文件/进程权限的对手——那种对手本来就能直接读配对文件
或改本进程。这里不宣称能防住它。
"""

from __future__ import annotations

import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from steelai.web_api.security import GuardError, check_origin

CLIENT_KINDS = ("browser", "ai")
DEFAULT_TTL_HOURS = 12
PAIRING_TTL_MINUTES = 30
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混的 I/O/0/1
PAIRING_LENGTH = 8

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
    paired: bool = False       # 只有走过一次性配对的人审会话才是 True


@dataclass(frozen=True)
class Pairing:
    code: str
    issued_at: str
    expires_at: str
    consumed_at: str = ""


_LOCK = threading.Lock()
_STORE: dict[str, Session] = {}
_PAIRING: Pairing | None = None


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


# --------------------------------------------------------------------------- #
# 一次性配对码（本地受信任通道）
# --------------------------------------------------------------------------- #

def pairing_file():
    """Where the one-time pairing code is written (local, per-machine)."""
    from steelai.web_api.config import config

    return config().run_root / "session" / "pairing.txt"


def _new_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_LENGTH))


def _write_pairing_file(pairing: Pairing) -> None:
    path = pairing_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# SteelAI 科研工作台 · 本地人审配对码（一次性）\n"
            "# 用途：首次打开 http://127.0.0.1:8760/ 时，把下面这行填进页面的「配对码」输入框。\n"
            "# 这是本机回环服务的本地凭据，请不要贴进聊天/截图/公开仓库。\n"
            "# 用过一次即作废并自动轮换；超过有效期需重启服务或重新生成。\n"
            f"code: {pairing.code}\n"
            f"issued_at: {pairing.issued_at}\n"
            f"expires_at: {pairing.expires_at}\n",
            encoding="utf-8",
        )
        try:  # 尽力只让当前用户可读（Windows/POSIX 都试一下，失败不致命）
            import os
            import stat

            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - best effort
            pass
    except OSError:  # pragma: no cover - a read-only disk must not crash the API
        pass


def ensure_pairing(*, rotate: bool = False) -> Pairing:
    """Create (or rotate) the one-time pairing code and publish it locally."""
    global _PAIRING
    now = datetime.now()
    with _LOCK:
        if _PAIRING is not None and not rotate:
            try:
                if datetime.fromisoformat(_PAIRING.expires_at) > now:
                    return _PAIRING
            except ValueError:  # pragma: no cover - defensive
                pass
        _PAIRING = Pairing(
            code=_new_code(),
            issued_at=now.isoformat(timespec="seconds"),
            expires_at=(now + timedelta(minutes=PAIRING_TTL_MINUTES)).isoformat(timespec="seconds"),
        )
        current = _PAIRING
    _write_pairing_file(current)
    return current


def pairing_status() -> dict:
    """Non-secret status for ``/api/health`` and the page's honest messaging."""
    with _LOCK:
        pairing = _PAIRING
    if pairing is None:
        return {"required": True, "active": False, "file": str(pairing_file()),
                "expires_at": "", "consumed": False}
    try:
        expired = datetime.fromisoformat(pairing.expires_at) <= datetime.now()
    except ValueError:  # pragma: no cover - defensive
        expired = True
    return {"required": True, "active": not expired, "file": str(pairing_file()),
            "expires_at": pairing.expires_at, "consumed": bool(pairing.consumed_at)}


def _consume_pairing(code: str) -> None:
    """Validate and burn the one-time code; always rotate afterwards."""
    global _PAIRING
    supplied = str(code or "").strip().upper().replace("-", "").replace(" ", "")
    with _LOCK:
        pairing = _PAIRING
        if pairing is None:
            raise GuardError("配对码尚未生成：请查看服务启动窗口或本地配对文件，然后重试")
        if pairing.consumed_at:
            raise GuardError("这个配对码已经用过（一次性）：请用最新的一份，或重启服务重新生成")
        # GuardError 是 ValueError 的子类：解析与过期判断必须分开，
        # 否则「已过期」会被下面这条 except ValueError 吞掉，误报成「记录损坏」。
        try:
            expires_at = datetime.fromisoformat(pairing.expires_at)
        except ValueError:  # pragma: no cover - defensive
            raise GuardError("配对码记录损坏，请重启服务重新生成") from None
        if expires_at <= datetime.now():
            raise GuardError("配对码已过期：请重启服务或查看最新生成的配对码")
        if not supplied:
            raise GuardError("缺少配对码：请先查看服务启动窗口（或本地配对文件）里的一次性配对码，"
                             "再在页面「配对」输入框提交")
        if not hmac.compare_digest(supplied, pairing.code):
            raise GuardError("配对码不正确：请照抄服务启动窗口/本地配对文件里的那一行")
        _PAIRING = Pairing(code=pairing.code, issued_at=pairing.issued_at,
                           expires_at=pairing.expires_at,
                           consumed_at=datetime.now().isoformat(timespec="seconds"))
    # 立刻轮换出下一枚一次性码，避免同一枚被重复使用。
    ensure_pairing(rotate=True)


def exchange(code: str, *, origin: str | None, allowed_origins: Iterable[str],
             ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    """Trade a one-time local pairing code for a paired browser session."""
    if not check_origin(origin, tuple(allowed_origins)):
        raise GuardError("配对请求必须来自内置页面（可信 Origin）")
    _consume_pairing(code)
    return _grant("browser", origin=origin, paired=True, ttl_hours=ttl_hours)


# --------------------------------------------------------------------------- #
# 令牌签发 / 校验
# --------------------------------------------------------------------------- #

def _grant(client: str, *, origin: str | None, paired: bool,
           ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
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
        paired=bool(paired),
    )
    with _LOCK:
        _prune(now)
        _STORE[token] = record
    return {
        "token": token,
        "session": record.as_dict(),
    }


def issue(client: str, *, origin: str | None, allowed_origins: Iterable[str],
          pairing: str = "", ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    """Issue a local capability token; never trust a caller-supplied role.

    ``client="ai"`` 直接发受限令牌；``client="browser"`` **必须**带一次性配对码
    （见 :func:`exchange`）——否则任何人只要写个 ``Origin`` 头就能拿到人审。
    """
    client = str(client or "").strip().lower()
    if client not in CLIENT_KINDS:
        raise GuardError(f"未知客户端类型：{client}（可选：{'、'.join(CLIENT_KINDS)}）")
    if client == "ai":
        return _grant("ai", origin=origin, paired=False, ttl_hours=ttl_hours)
    if not check_origin(origin, tuple(allowed_origins)):
        raise GuardError("浏览器会话必须从内置页面（可信 Origin）发起；"
                         "本地 AI 请改用 client=ai")
    return exchange(pairing, origin=origin, allowed_origins=allowed_origins,
                    ttl_hours=ttl_hours)


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
    if capability == "review:human" and not record.paired:
        # 双保险：即使某处误配了能力集，没走过配对也不给人审。
        raise GuardError("该会话没有完成本地人审配对，不能执行人工确认。")
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
        "paired": record.paired,
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
