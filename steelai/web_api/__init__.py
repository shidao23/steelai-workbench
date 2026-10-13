"""WO-31 §3 — SteelAI 科研薄 API。

``steelai.web_api`` 只做编排：解析可信 project/task/file/run 标识，按固定 argv
调用已登记的独立工具，把状态与产物如实返回。科学算法仍在各自 owner 仓里。
"""

from __future__ import annotations

__all__ = ["app", "config", "registry", "runner", "security", "tools"]
