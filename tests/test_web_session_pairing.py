"""WO-33 §3 — 本地最小会话与一次性配对的能力边界回归。

WO-32 的洞：``POST /api/session {client:"browser"}`` 只要带一个**可以自己填**的
``Origin`` 头就发 ``review:human``，于是任意 HTTP 脚本都能领到人审能力。WO-33 把它
改成「人审能力只由本地受信任入口授予」：可信 ``Origin`` 仍作跨站防护，但**不再是**
身份认证，必须再提交一枚由服务器生成、只经本地通道展示、用过即轮换的一次性配对码。

这里把边界固化成回归：

* 谁能拿到 ``review:human``（browser 要配对 / ai 永远没有）；
* 配对码：错码、重复使用、跨站 Origin、未生成、过期 → 全部拒绝；
* 已有 AI 令牌改 ``client``/``role`` 不能升级；
* 令牌只在进程内存里：``revoke_all`` 与过期后立即失效；
* 能力集由服务端决定，调用方只能"申请类型"，不能自选能力；
* ``pairing_status()`` 只报"需要配对"，绝不回传配对码本身。
"""

from __future__ import annotations

import pytest

from steelai.web_api import session as session_store
from steelai.web_api.config import config
from steelai.web_api.security import GuardError

TRUSTED = "http://127.0.0.1:8760"
EVIL = "http://evil.example"


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """每个用例一套干净的内存令牌表 + 独立的配对文件位置。"""
    monkeypatch.setenv("RESEARCH_WEB_RUN_ROOT", str(tmp_path / "run"))
    config(refresh=True)
    session_store.revoke_all()
    monkeypatch.setattr(session_store, "_PAIRING", None)
    yield
    session_store.revoke_all()
    monkeypatch.setattr(session_store, "_PAIRING", None)
    monkeypatch.undo()
    config(refresh=True)


def _issue_browser(**kwargs) -> dict:
    return session_store.issue("browser", origin=TRUSTED, allowed_origins=(TRUSTED,), **kwargs)


# --------------------------------------------------------------------------- #
# 能力集：服务端决定，调用方不能自选
# --------------------------------------------------------------------------- #

class TestCapabilitySets:
    def test_browser_capabilities_include_human_review(self) -> None:
        caps = session_store.capabilities_for("browser")
        assert "review:human" in caps
        assert "files:write" in caps and "tasks:write" in caps and "handoff:write" in caps

    def test_ai_capabilities_are_restricted(self) -> None:
        caps = session_store.capabilities_for("ai")
        assert "runs:create" in caps           # 获准后执行仍然可以
        assert "files:read" in caps            # 读仍然可以
        for forbidden in ("review:human", "files:write", "tasks:write", "handoff:write"):
            assert forbidden not in caps

    def test_unknown_client_is_refused(self) -> None:
        with pytest.raises(GuardError, match="未知客户端类型"):
            session_store.capabilities_for("admin")

    def test_ai_session_cannot_do_human_review(self) -> None:
        issued = session_store.issue("ai", origin=None, allowed_origins=(TRUSTED,))
        token = issued["token"]
        assert issued["session"]["paired"] is False
        assert session_store.require(token, "files:read").actor_kind == "ai-assistant"
        with pytest.raises(GuardError, match="没有此能力"):
            session_store.require(token, "review:human")


# --------------------------------------------------------------------------- #
# 一次性配对码
# --------------------------------------------------------------------------- #

class TestPairing:
    def test_browser_without_any_pairing_is_refused(self) -> None:
        # 服务器还没生成过配对码：报"尚未生成"，而不是"码不对"。
        with pytest.raises(GuardError, match="尚未生成"):
            _issue_browser()

    def test_browser_with_pairing_but_no_code_is_refused(self) -> None:
        # 码已生成，但页面提交了空码：报"缺少配对码"。
        session_store.ensure_pairing(rotate=True)
        with pytest.raises(GuardError, match="缺少配对码"):
            _issue_browser()

    def test_browser_with_wrong_code_is_refused(self) -> None:
        session_store.ensure_pairing(rotate=True)
        with pytest.raises(GuardError, match="配对码不正确"):
            _issue_browser(pairing="AAAAAAAA")

    def test_untrusted_origin_is_refused_and_does_not_burn_the_code(self) -> None:
        pairing = session_store.ensure_pairing(rotate=True)
        with pytest.raises(GuardError, match="可信 Origin"):
            session_store.exchange(pairing.code, origin=EVIL, allowed_origins=(TRUSTED,))
        # 跨站失败不应消耗掉这枚码
        issued = session_store.exchange(pairing.code, origin=TRUSTED, allowed_origins=(TRUSTED,))
        assert issued["session"]["paired"] is True
        assert "review:human" in issued["session"]["capabilities"]

    def test_code_is_single_use(self) -> None:
        pairing = session_store.ensure_pairing(rotate=True)
        session_store.exchange(pairing.code, origin=TRUSTED, allowed_origins=(TRUSTED,))
        with pytest.raises(GuardError):
            session_store.exchange(pairing.code, origin=TRUSTED, allowed_origins=(TRUSTED,))

    def test_code_rotates_after_use(self) -> None:
        first = session_store.ensure_pairing(rotate=True)
        session_store.exchange(first.code, origin=TRUSTED, allowed_origins=(TRUSTED,))
        second = session_store.ensure_pairing()
        assert second.code != first.code

    def test_consumed_code_is_reported_as_consumed(self) -> None:
        pairing = session_store.ensure_pairing(rotate=True)
        session_store.exchange(pairing.code, origin=TRUSTED, allowed_origins=(TRUSTED,))
        # 轮换后的新码是"未用过"的；被用掉的那一枚应被判为已用
        session_store.revoke_all()
        with pytest.raises(GuardError):
            session_store._consume_pairing(pairing.code)

    def test_expired_code_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(session_store, "PAIRING_TTL_MINUTES", -1)
        pairing = session_store.ensure_pairing(rotate=True)
        with pytest.raises(GuardError, match="已过期"):
            session_store.exchange(pairing.code, origin=TRUSTED, allowed_origins=(TRUSTED,))

    def test_corrupt_record_is_reported_distinctly_from_expiry(self, monkeypatch) -> None:
        """回归：GuardError 是 ValueError 子类，解析与过期判断必须分开。

        否则「已过期」会被 ``except ValueError`` 吞掉误报成「记录损坏」，
        用户按错误的提示去查文件反而查不出问题。
        """
        pairing = session_store.ensure_pairing(rotate=True)
        broken = session_store.Pairing(code=pairing.code, issued_at=pairing.issued_at,
                                       expires_at="not-a-timestamp")
        monkeypatch.setattr(session_store, "_PAIRING", broken)
        with pytest.raises(GuardError, match="记录损坏"):
            session_store._consume_pairing(pairing.code)

    def test_missing_pairing_record_is_reported(self) -> None:
        with pytest.raises(GuardError, match="尚未生成"):
            session_store._consume_pairing("ABCDEFGH")

    def test_status_never_leaks_the_code(self) -> None:
        pairing = session_store.ensure_pairing(rotate=True)
        status = session_store.pairing_status()
        assert status["required"] is True and status["active"] is True
        assert "code" not in status
        assert pairing.code not in repr(status)

    def test_pairing_file_is_where_status_says(self) -> None:
        session_store.ensure_pairing(rotate=True)
        status = session_store.pairing_status()
        path = session_store.pairing_file()
        assert str(path) == status["file"]
        assert path.is_file()
        assert "code:" in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 令牌：进程内存、过期、撤销、格式
# --------------------------------------------------------------------------- #

class TestTokens:
    def test_revoke_all_invalidates_every_token(self) -> None:
        token = _issue_browser(pairing=session_store.ensure_pairing(rotate=True).code)["token"]
        assert session_store.verify(token).paired is True
        session_store.revoke_all()
        with pytest.raises(GuardError, match="不存在或已失效"):
            session_store.verify(token)

    def test_expired_token_is_refused(self) -> None:
        issued = session_store.issue("ai", origin=None, allowed_origins=(TRUSTED,), ttl_hours=-1)
        with pytest.raises(GuardError, match="已过期"):
            session_store.verify(issued["token"])

    def test_malformed_tokens_are_refused(self) -> None:
        with pytest.raises(GuardError, match="缺少会话令牌"):
            session_store.verify("")
        with pytest.raises(GuardError, match="格式不正确"):
            session_store.verify("has space")
        with pytest.raises(GuardError, match="格式不正确"):
            session_store.verify("x" * 300)

    def test_paired_flag_is_required_for_human_review(self, monkeypatch) -> None:
        """双保险：即使能力集里误配了 review:human，没走过配对也不给人审。"""
        forged = session_store.Session(
            session_id="forged", client="browser", actor_kind="human-browser",
            capabilities=session_store.BROWSER_CAPABILITIES,
            issued_at="2026-10-14T00:00:00", expires_at="2099-01-01T00:00:00",
            origin=TRUSTED, paired=False,
        )
        with session_store._LOCK:
            session_store._STORE["forged-token"] = forged
        assert session_store.verify("forged-token").paired is False
        with pytest.raises(GuardError, match="没有完成本地人审配对"):
            session_store.require("forged-token", "review:human")

    def test_caller_supplied_role_string_grants_nothing(self) -> None:
        """调用方只能申请类型；多塞一个 role/reviewer 字段不会带来任何能力。"""
        issued = session_store.issue("ai", origin=None, allowed_origins=(TRUSTED,))
        assert "review:human" not in issued["session"]["capabilities"]
        # issue() 的签名里根本没有 role/capabilities 参数，只有 client 类型
        with pytest.raises(TypeError):
            session_store.issue("ai", origin=None, allowed_origins=(TRUSTED,),
                                role="human-browser")

    def test_session_payload_has_no_secret_material(self) -> None:
        issued = _issue_browser(pairing=session_store.ensure_pairing(rotate=True).code)
        record = issued["session"]
        assert set(record) >= {"session_id", "client", "actor_kind", "capabilities",
                               "issued_at", "expires_at", "origin", "paired"}
        assert "code" not in record and "pairing" not in record
