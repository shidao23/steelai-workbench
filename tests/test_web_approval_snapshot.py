"""WO-34 §1/§2 — 审批快照收尾回归。

WO-33 独立查收留下两个真实缺陷，本文件把它们固化成回归：

§1 相同字节的不同输入身份被暗批
    保存 ``receipt-identity`` 绑定 ``a.csv``，随后同 profile 改绑同字节的
    ``same.csv``；旧快照（profile SHA + input SHA + expected_input_file=a.csv）
    仍被 200 批准 —— 因为只核了两个 SHA，没核输入身份/修订。

§2 排队后读到替换的审批，却记录旧版本
    run 已入队（执行器延迟启动），等待期间把同 profile 改成 GPa 并重新批准；
    放行后 CLI 用了新审批（600000 MPa）却记录原 MPa 版本。

这里用**隔离合成根 + 真实原 SteelData CLI**验证：确认是完整对象
（project/task/profile 身份 + 输入 file_id+SHA + profile 内容 SHA + 修订）的
compare-and-set；run 消费的是创建时冻结的审批/输入快照。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from steelai.web_api import mapping, registry, runner, session as session_store
from steelai.web_api.config import config
from steelai.web_api.security import ConflictError, GuardError

CSV = b"specimen_id,ys_mpa,uts_mpa,el_pct\nS1,600,800,15\nS2,610,820,16\n"
COLS = [
    {"source": "specimen_id", "target": "specimen_id", "dtype": "text", "required": True},
    {"source": "ys_mpa", "target": "ys_mpa", "dtype": "number", "unit": "MPa"},
    {"source": "uts_mpa", "target": "uts_mpa", "dtype": "number", "unit": "MPa"},
    {"source": "el_pct", "target": "el_pct", "dtype": "number", "unit": "%"},
]
PROJECT = "PSYN"
TASK = "WO34SYN"


def _steeldata_registered() -> bool:
    tool = config().tool("steeldata")
    return bool(tool and tool.interpreter and tool.interpreter.is_file())


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Each test gets its own synthetic roots, task and inputs."""
    if not _steeldata_registered():
        pytest.skip("未登记 SteelData 解释器（config/settings.toml [tools] steeldata_python），"
                    "跳过需要真实原 CLI 的审批回归")
    synthetic = tmp_path / "PSYN"
    synthetic.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RESEARCH_WEB_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("RESEARCH_WEB_MASTER_WORKBOOK", str(tmp_path / "ws" / "projects.xlsx"))
    monkeypatch.setenv("RESEARCH_WEB_WORK_ROOT", str(tmp_path / "ws" / "work"))
    monkeypatch.setenv("RESEARCH_WEB_OUTPUT_ROOT", str(tmp_path / "ws" / "out"))
    monkeypatch.setenv("RESEARCH_WEB_RUN_ROOT", str(tmp_path / "ws" / "run_index"))
    monkeypatch.setenv("RESEARCH_WEB_SYNTHETIC_ROOT", str(synthetic))
    config(refresh=True)
    registry.create_task(PROJECT, TASK, "WO-34 合成回归")
    inputs = registry.task_inputs(PROJECT, TASK)
    for name in ("a.csv", "b.csv", "same.csv"):
        (inputs / name).write_bytes(CSV if name != "b.csv" else CSV.replace(b"600", b"900"))
    yield
    config(refresh=True)


def _human():
    pairing = session_store.ensure_pairing(rotate=True)
    issued = session_store.exchange(pairing.code, origin="http://127.0.0.1:8760",
                                    allowed_origins=("http://127.0.0.1:8760",))
    return session_store.verify(issued["token"])


def _save(profile_id: str, *, input_file: str = "a.csv", unit: str = "MPa") -> dict:
    cols = [dict(c) for c in COLS]
    cols[1]["unit"] = unit
    result = mapping.save_candidate(PROJECT, TASK, {
        "profile_id": profile_id, "input_file": input_file, "domain": "tensile",
        "layout": "flat", "header_row": 1, "columns": cols,
    })
    assert result["ok"], result
    return result


def _review(profile_id: str, snapshot: dict, decision: str = "approve", **overrides):
    payload = {
        "profile_id": profile_id, "decision": decision,
        "reviewer": "WO-34 Synthetic Reviewer", "note": "隔离合成回归",
        "expected_project_id": snapshot["project_id"],
        "expected_task_id": snapshot["task_id"],
        "expected_profile_sha256": snapshot["profile_sha256"],
        "expected_input_file": snapshot["input_file"],
        "expected_input_sha256": snapshot["input_sha256"],
        "expected_revision": snapshot["revision"],
    }
    payload.update(overrides)
    return mapping.review_candidate(PROJECT, TASK, payload, _human(), synthetic=True)


def _approval_path(profile_id: str) -> Path:
    return registry.approvals_dir(PROJECT, TASK) / f"{profile_id}.json"


def _approval_digest(profile_id: str) -> str:
    path = _approval_path(profile_id)
    if not path.is_file():
        return ""
    return str(json.loads(path.read_text(encoding="utf-8")).get("profile_sha256", ""))


# --------------------------------------------------------------------------- #
# §1 完整所见对象
# --------------------------------------------------------------------------- #

class TestConfirmationContract:
    def test_snapshot_has_full_identity(self) -> None:
        saved = _save("snap")
        snap = saved["snapshot"]
        assert set(snap) >= {"project_id", "task_id", "profile_id", "input_file",
                             "input_sha256", "profile_sha256", "revision"}
        assert snap["project_id"] == PROJECT and snap["task_id"] == TASK
        assert snap["input_file"] == "a.csv" and snap["revision"] == 1
        assert snap["profile_sha256"] == saved["profile_sha256"]

    def test_missing_identity_fields_are_refused(self) -> None:
        saved = _save("missing")
        for drop in ("expected_input_file", "expected_revision",
                     "expected_profile_sha256", "expected_project_id", "expected_task_id"):
            with pytest.raises(GuardError, match="完整对象|缺字段|绑定"):
                _review("missing", saved["snapshot"], **{drop: None})
        assert not _approval_path("missing").is_file()

    def test_same_bytes_different_input_identity_is_rejected(self) -> None:
        """WO-33 查收缺陷 1：同字节改绑另一文件不能沿用旧确认。"""
        first = _save("identity", input_file="a.csv")
        # 同字节、不同输入身份：profile 内容与输入 SHA 都没变，只有 file_id 变了。
        second = _save("identity", input_file="same.csv")
        assert second["profile_sha256"] == first["profile_sha256"]
        assert second["input_sha256"] == first["input_sha256"]
        assert second["revision"] == first["revision"] + 1  # 身份变化 = 有效内容变化
        # 用「用户看到 a.csv」的旧快照确认 → 必须 409，而不是暗批 same.csv。
        with pytest.raises(ConflictError, match="输入身份|已经不是当前版本"):
            _review("identity", first["snapshot"])
        assert not _approval_path("identity").is_file()

    def test_expired_revision_is_rejected(self) -> None:
        v1 = _save("rev", unit="MPa")
        _save("rev", unit="GPa")
        with pytest.raises(ConflictError, match="映射修订|映射内容"):
            _review("rev", v1["snapshot"])
        assert not _approval_path("rev").is_file()

    def test_stale_attempt_is_journaled_and_appends_only(self) -> None:
        v1 = _save("journal")
        _save("journal", unit="GPa")
        with pytest.raises(ConflictError):
            _review("journal", v1["snapshot"])
        kinds = [row.get("kind") for row in mapping.list_reviews(PROJECT, TASK)]
        assert "review_stale" in kinds


# --------------------------------------------------------------------------- #
# §1 修订语义：无变化重存保留批准；真实变化失效；互不误撤销
# --------------------------------------------------------------------------- #

class TestRevisionSemantics:
    def test_no_change_resave_keeps_approval(self) -> None:
        saved = _save("keep")
        assert _review("keep", saved["snapshot"])["ok"]
        assert _approval_path("keep").is_file()
        again = _save("keep")  # 完全相同的输入身份/字节/映射
        assert again["revision"] == saved["revision"]
        assert again["unchanged"] is True
        assert again["invalidated_approvals"] == []
        assert _approval_path("keep").is_file()
        assert _approval_digest("keep") == saved["profile_sha256"]

    def test_real_change_invalidates(self) -> None:
        saved = _save("change")
        assert _review("change", saved["snapshot"])["ok"]
        changed = _save("change", unit="GPa")
        assert changed["revision"] == saved["revision"] + 1
        assert changed["invalidated_approvals"] == ["change.json"]
        assert not _approval_path("change").is_file()

    def test_unrelated_profile_does_not_revoke(self) -> None:
        a = _save("keep-a")
        assert _review("keep-a", a["snapshot"])["ok"]
        _save("other-b", input_file="b.csv")
        assert _approval_path("keep-a").is_file()
        assert _approval_digest("keep-a") == a["profile_sha256"]

    def test_reject_invalidates_and_records(self) -> None:
        saved = _save("rej")
        assert _review("rej", saved["snapshot"])["ok"]
        result = _review("rej", saved["snapshot"], decision="reject")
        assert result["ok"] and result["decision"] == "reject"
        assert not _approval_path("rej").is_file()


# --------------------------------------------------------------------------- #
# §1 并发：核旧值后落盘新对象 / 错配批准
# --------------------------------------------------------------------------- #

class TestConcurrency:
    def test_concurrent_save_and_review_never_writes_mismatched_approval(self) -> None:
        """保存与确认并发：最终 approvals/ 里绝不能留下与当前 meta 不符的批准。"""
        saved = _save("race")
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def do_review():
            barrier.wait()
            try:
                _review("race", saved["snapshot"])
            except (ConflictError, GuardError):
                pass  # 过期被拒是允许的
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def do_save():
            barrier.wait()
            try:
                _save("race", unit="GPa")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=do_review), threading.Thread(target=do_save)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors, errors

        approval = _approval_path("race")
        if approval.is_file():
            digest = _approval_digest("race")
            meta = mapping.confirmation_snapshot(PROJECT, TASK, "race")
            assert digest == meta["profile_sha256"], (
                "approvals/ 里留下了与当前映射不符的批准")


# --------------------------------------------------------------------------- #
# §2 运行消费固定审批快照（真实原 CLI，不用 mock 成功结果）
# --------------------------------------------------------------------------- #

class TestFrozenApprovalRun:
    def test_queued_run_uses_frozen_approval(self, monkeypatch) -> None:
        """排队期间替换审批：CLI 必须用冻结的旧版本，或明确阻断。"""
        first = _save("frozen", unit="MPa")
        assert _review("frozen", first["snapshot"])["ok"]

        entered = threading.Event()
        release = threading.Event()
        real_execute = runner._execute

        def gated_execute(*args):
            entered.set()
            assert release.wait(30)
            return real_execute(*args)

        monkeypatch.setattr(runner, "_execute", gated_execute)
        created = runner.create_run(PROJECT, TASK, "steeldata.run",
                                    {"input_file": "a.csv", "approval_file": "frozen.json"},
                                    actor="synthetic-wo34")
        assert entered.wait(10)
        # 排队期间把同 profile 改成 GPa 并重新批准（旧审批被失效归档）。
        second = _save("frozen", unit="GPa")
        assert _review("frozen", second["snapshot"])["ok"]
        release.set()
        result = runner.wait_for(created["run_id"], timeout=60)
        monkeypatch.setattr(runner, "_execute", real_execute)

        assert result["status"] in {"succeeded", "blocked"}, result
        if result["status"] == "succeeded":
            # 记录与真正消费的版本必须一致：冻结的是 MPa 原版本。
            assert result["approval_profile_sha256"] == first["profile_sha256"]
            assert result["approval_profile_sha256"] != second["profile_sha256"]
            csv = next((a for a in result["artifacts"] if a["name"] == "data.csv"), None)
            assert csv is not None
            text = (Path(result["output_dir"]) / csv["rel"]).read_text(encoding="utf-8-sig")
            # 用的是 MPa 原审批 → ys_mpa 仍是 600/610，不是 GPa 换算出的 600000/610000。
            assert "600000" not in text and "610000" not in text
            assert "600" in text and "610" in text

    def test_frozen_input_tamper_is_blocked(self, monkeypatch) -> None:
        """冻结后输入快照被改动 → 启动前阻断，不执行任何子进程。"""
        saved = _save("tamper")
        assert _review("tamper", saved["snapshot"])["ok"]

        entered = threading.Event()
        release = threading.Event()
        real_execute = runner._execute

        def gated_execute(*args):
            entered.set()
            assert release.wait(30)
            return real_execute(*args)

        monkeypatch.setattr(runner, "_execute", gated_execute)
        created = runner.create_run(PROJECT, TASK, "steeldata.run",
                                    {"input_file": "a.csv", "approval_file": "tamper.json"},
                                    actor="synthetic-wo34")
        assert entered.wait(10)
        record = runner.load_record(created["run_id"])
        frozen_input = Path(record.input_frozen_path)
        frozen_input.write_bytes(frozen_input.read_bytes() + b"\nS3,700,900,20\n")
        release.set()
        result = runner.wait_for(created["run_id"], timeout=60)
        monkeypatch.setattr(runner, "_execute", real_execute)
        assert result["status"] == "blocked"
        assert "输入快照" in result["error"]
