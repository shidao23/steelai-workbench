"""WO-31 §3 — 科研薄 API 的路径、文件名与来源守卫。

这一层只做**拒绝**，不做任何科学计算，也不接受客户端提交的磁盘路径、URL、
解释器或 shell 片段。所有"可信根"都由服务端配置解析，客户端只能提交
``project_id`` / ``task_id`` / ``file_id`` / ``run_id`` 这类标识。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Windows 保留设备名：即使带扩展名也不能作为文件名的一部分出现。
_WINDOWS_DEVICES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_SEPARATORS = ("/", "\\")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")


class GuardError(ValueError):
    """Raised when a caller-supplied value fails a trust check."""


class ConflictError(GuardError):
    """Raised when a caller's expected snapshot no longer matches the server's.

    WO-33 §2: a review must be a compare-and-set against the version the human
    actually saw. A stale ``expected_*`` digest is a 409, never a silent
    "approve whatever is newest" — that would let a confirmation of v1 bless v2.
    """


def is_reparse_point(path: Path) -> bool:
    """Return ``True`` for symlinks, junctions and other reparse points."""
    try:
        if path.is_symlink():
            return True
        info = path.lstat()
    except OSError:
        return False
    # Windows 上 junction/symlink 由 FILE_ATTRIBUTE_REPARSE_POINT (0x400) 标记。
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _check_ancestors(root: Path, target: Path) -> None:
    """Reject when any path component between ``root`` and ``target`` is a reparse point."""
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and is_reparse_point(current):
            raise GuardError(f"路径组件是重解析点，拒绝：{part}")


def resolve_under(root: Path, relative: str) -> Path:
    """Resolve *relative* inside *root*, refusing escapes and reparse points.

    The check is done on the *resolved* path so ``..`` segments, absolute
    paths, drive-relative paths and trailing separators cannot slip through.
    """
    if relative is None:
        raise GuardError("缺少相对路径")
    raw = str(relative).strip()
    if not raw:
        raise GuardError("相对路径为空")
    if Path(raw).is_absolute() or Path(raw).drive:
        raise GuardError(f"不接受绝对路径：{raw}")
    root = Path(root).resolve()
    if not root.is_dir():
        raise GuardError(f"可信根不存在：{root}")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:  # pragma: no cover - defensive
        raise GuardError(f"路径越出可信根：{raw}") from exc
    _check_ancestors(root, candidate)
    return candidate


def safe_filename(name: str) -> str:
    """Return a filesystem-safe basename or raise.

    Uploaded names are the classic escape vector (``../``, ``C:\\``, NTFS
    alternate data streams, Windows device names, control characters), so they
    are reduced to a single validated component and never used as a path.
    """
    raw = str(name or "").strip()
    if not raw:
        raise GuardError("文件名为空")
    if len(raw) > 200:
        raise GuardError("文件名过长")
    if raw != Path(raw).name or any(sep in raw for sep in _SEPARATORS):
        raise GuardError(f"文件名含路径分隔符：{raw}")
    if raw in {".", ".."} or raw.startswith(".."):
        raise GuardError(f"非法文件名：{raw}")
    if ":" in raw:
        raise GuardError(f"文件名含冒号（可能是数据流或盘符）：{raw}")
    if any(ord(ch) < 32 for ch in raw):
        raise GuardError("文件名含控制字符")
    stem = raw.split(".")[0].strip().lower()
    if stem in _WINDOWS_DEVICES:
        raise GuardError(f"文件名是系统保留设备名：{raw}")
    if raw.endswith((" ", ".")):
        raise GuardError(f"文件名不能以空格或点结尾：{raw}")
    return raw


def safe_identifier(value: str, what: str = "标识") -> str:
    """Validate a project/task/run identifier: no separators, no traversal."""
    raw = str(value or "").strip()
    if not _IDENTIFIER_RE.match(raw):
        raise GuardError(f"非法{what}：{raw!r}")
    return raw


def check_origin(origin: str | None, allowed: tuple[str, ...]) -> bool:
    """Accept only origins the server itself registered.

    A missing ``Origin`` is accepted because same-origin ``fetch`` from the
    bundled page may omit it in some browsers; a *present* but unknown origin
    is always rejected, and no wildcard is ever configured.
    """
    if origin is None or origin == "":
        return True
    return origin.rstrip("/") in {item.rstrip("/") for item in allowed}


def interpreter_is_trusted(candidate: Path | None, allowed_roots: tuple[Path, ...]) -> bool:
    """A configured interpreter must live under a declared tool root.

    Used as a reporting check: interpreters are only ever resolved server-side
    (environment variable or the ignored ``config/settings.toml``), so this
    answers "is the path we resolved still inside a root we registered?", and a
    missing interpreter is reported as untrusted rather than raising.
    """
    if candidate is None:
        return False
    try:
        resolved = Path(candidate).resolve()
    except OSError:
        return False
    for root in allowed_roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def default_allowed_origins(host: str, ports: tuple[int, ...]) -> tuple[str, ...]:
    """Origins for the loopback page(s) the launcher actually serves."""
    origins: list[str] = []
    for port in ports:
        origins.append(f"http://127.0.0.1:{port}")
        origins.append(f"http://localhost:{port}")
    return tuple(dict.fromkeys(origins))


def is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("127.")


def env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
