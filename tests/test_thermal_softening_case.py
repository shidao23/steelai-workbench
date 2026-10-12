from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from steelai.agent_evidence_gateway import AgentEvidenceGateway
from steelai.governance import verify_package
from steelai.research_tools import TOOL_FUNCTIONS, execute_readonly_tool
from steelai.research_agent import AgentStatus, run_research_agent
from steelai import thermal_softening_case
from steelai.thermal_softening_case import (
    _validate_formal_rows,
    load_softening_case,
    publish_softening_case,
)


def _one_row() -> tuple[list[dict[str, str]], list[dict[str, object]], list[dict[str, str]]]:
    candidate: dict[str, object] = {
        "experiment_run_id": "EXP-TEST-A1",
        "acquisition_id": "1",
        "sample_id": "B-DQ",
        "source_feature_row_sha256": "feature-digest",
        "method_registry_sha256": "registry-digest",
        "effective_temperature_c": 1000.0,
        "effective_deformation_gap_s": 10.0,
        "primary_sigma_1_mpa": 60.0,
        "primary_sigma_2_mpa": 50.0,
        "primary_softening_percent_raw": 120.0,
        "sensitivity_softening_percent_raw": 108.0,
        "result_qc_status": "warning_needs_human_review",
        "qc_flags": "primary_softening_outside_0_to_1",
    }
    formal = {key: str(value) for key, value in candidate.items()}
    formal.update({
        "result_review_status": "approved",
        "result_reviewer_id": "human-reviewer",
        "result_reviewed_at": "2026-09-16T19:48:56+08:00",
        "source_feature_review_status": "approved",
        "method_selection_status": "approved",
        "softening_row_sha256": "reviewed-row-digest",
    })
    features = [{"experiment_run_id": "EXP-TEST-A1", "feature_row_sha256": "feature-digest"}]
    return [formal], [candidate], features


def test_formal_values_are_recalculated_without_clipping() -> None:
    formal, calculated, features = _one_row()
    checked = _validate_formal_rows(formal, calculated, features, "registry-digest")
    assert checked[0]["primary_percent"] == 120.0
    assert checked[0]["sensitivity_percent"] == 108.0
    assert checked[0]["qc_status"] == "warning_needs_human_review"


def test_changed_formal_percentage_or_approval_is_rejected() -> None:
    formal, calculated, features = _one_row()
    formal[0]["primary_softening_percent_raw"] = "90.0"
    with pytest.raises(ValueError, match="primary_softening_percent_raw"):
        _validate_formal_rows(formal, calculated, features, "registry-digest")
    formal, calculated, features = _one_row()
    formal[0]["result_review_status"] = "calculated_needs_human_review"
    with pytest.raises(ValueError, match="approval"):
        _validate_formal_rows(formal, calculated, features, "registry-digest")


def _synthetic_case() -> dict[str, object]:
    digest = "a" * 64
    return {
        "case_id": "TSC-" + "A" * 20,
        "status": "analysis_draft_needs_human_review",
        "row_count": 1,
        "passed_count": 0,
        "warning_ids": ["A1"],
        "large_method_difference_passed_ids": [],
        "source_digests": {
            "runs_sha256": digest,
            "points_sha256": digest,
            "features_sha256": digest,
            "formal_results_sha256": digest,
            "method_registry_sha256": digest,
            "literature_pdf_sha256": digest,
        },
        "observations": {
            "near_1000_c_9_to_11_s": {
                "b_dq_primary_percent_range": [50.0, 50.0],
                "r_dq_primary_percent_range": [70.0, 70.0],
            }
        },
        "rows": [{
            "acquisition_id": "A1", "sample_id": "B-DQ", "temperature_c": 1000.0,
            "deformation_gap_s": 10.0, "primary_percent": 120.0,
            "sensitivity_percent": 108.0, "qc_status": "warning_needs_human_review",
        }],
    }


def test_package_is_append_only_and_tampering_is_detected(tmp_path: Path) -> None:
    case = _synthetic_case()
    root = tmp_path / "cases"
    destination = publish_softening_case(case, output_root=root)
    assert verify_package(destination).status == "passed"
    assert publish_softening_case(case, output_root=root) == destination
    assert load_softening_case(case["case_id"], output_root=root)["row_count"] == 1
    with pytest.raises(ValueError, match="invalid case ID"):
        load_softening_case("../escape", output_root=root)
    evidence_path = destination / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["row_count"] = 2
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert verify_package(destination).status == "invalidated"
    with pytest.raises(ValueError, match="invalidated"):
        load_softening_case(case["case_id"], output_root=root)


def test_agent_gateway_allows_only_curated_case_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _synthetic_case()
    monkeypatch.setattr(thermal_softening_case, "load_softening_case", lambda case_id: case)
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_thermal_softening_case", lambda case_id: case)
    gateway = AgentEvidenceGateway(
        "Analyse a governed double-hit case", "test-provider", "test-model",
        ("get_thermal_softening_case",),
    )
    result = gateway.execute_evidence_tool(
        "get_thermal_softening_case", {"case_id": case["case_id"]},
        execute_readonly_tool, round_number=1,
    )
    assert result["_gateway"]["verification_status"] == "passed"
    assert result["row_count"] == 1
    assert len(gateway.evidence_permits) == 1


def test_agent_model_round_trip_uses_the_case_tool_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _synthetic_case()
    monkeypatch.setattr(thermal_softening_case, "load_softening_case", lambda case_id: case)
    monkeypatch.setitem(TOOL_FUNCTIONS, "get_thermal_softening_case", lambda case_id: case)
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="get_thermal_softening_case",
            arguments=json.dumps({"case_id": case["case_id"]}),
        ),
    )
    responses = [
        SimpleNamespace(
            id="response-1", usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))],
        ),
        SimpleNamespace(
            id="response-2", usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(
                content="## 已确认事实\n- A1 是待复核值。\n## 当前判断\n- 暂不解释机制。\n"
                        "## 待验证假设\n- 取点可能影响结果。\n## 证据与局限\n- 仅有案例证据。\n"
                        "## 下一步行动\n- 检查曲线。",
                tool_calls=None,
            ))],
        ),
    ]
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: responses.pop(0)
    )))
    status = AgentStatus("online_ready", True, True, True, "fake-model", "low", 2, 3,
                         "ready", provider="deepseek")
    result = run_research_agent(
        f"请分析 {case['case_id']}", client=client, status=status,
    )
    assert result.status == "completed"
    assert result.tool_trace[0]["tool"] == "get_thermal_softening_case"
    assert result.structured_output["contract_status"] == "passed"


# --- STEEL-V1-03A: the draft must state only the case's own facts -----------------------------

def _row(acquisition: str, sample: str, temperature: float, gap: float,
         primary: float, sensitivity: float, qc: str, flags: list[str] | None = None) -> dict[str, object]:
    row: dict[str, object] = {
        "acquisition_id": acquisition, "sample_id": sample, "temperature_c": temperature,
        "deformation_gap_s": gap, "primary_percent": primary,
        "sensitivity_percent": sensitivity, "qc_status": qc,
    }
    if flags is not None:
        row["qc_flags"] = flags
    return row


def _multi_row_case() -> dict[str, object]:
    case = _synthetic_case()
    case["case_id"] = "TSC-" + "B" * 20
    case.update(row_count=3, passed_count=2, warning_ids=["A7"])
    case["rows"] = [
        _row("A2", "B-DQ", 1000.0, 10.0, 48.0, 44.0, "passed"),
        _row("A3", "R-DQ", 1000.5, 9.5, 61.0, 58.0, "passed"),
        _row("A7", "B-DQ", 1100.0, 30.0, 130.0, 95.0,
             "warning_needs_human_review", ["primary_softening_outside_0_to_1"]),
    ]
    return case


def _real_batch_shape_case() -> dict[str, object]:
    """Mirror the approved batch's SHAPE (4 window passes + 4 warnings) with synthetic values."""
    case = _synthetic_case()
    case["case_id"] = "TSC-" + "C" * 20
    case.update(row_count=8, passed_count=4, warning_ids=["A79", "A80", "A84", "A85"])
    case["large_method_difference_passed_ids"] = ["A5"]
    case["literature"] = {
        "title": "TSDR 工艺热加工过程的组织演变与控制", "author": "张玲", "year": 2007,
        "method_reference": "第4.1.2.1节",
    }
    case["rows"] = [
        _row("A1", "B-DQ", 1000.0, 9.0, 48.0, 44.0, "passed"),
        _row("A2", "B-DQ", 1002.0, 11.0, 52.0, 47.0, "passed"),
        _row("A3", "R-DQ", 999.0, 10.0, 61.0, 58.0, "passed"),
        _row("A4", "R-DQ", 1001.0, 9.5, 66.0, 60.0, "passed"),
        _row("A79", "B-DQ", 1100.0, 25.0, 118.0, 96.0,
             "warning_needs_human_review", ["primary_softening_outside_0_to_1"]),
        _row("A80", "B-DQ", 1105.0, 40.0, 126.0, 115.0,
             "warning_needs_human_review", ["primary_softening_outside_0_to_1"]),
        _row("A84", "R-DQ", 1102.0, 18.0, 122.0, 108.0,
             "warning_needs_human_review", ["primary_softening_outside_0_to_1"]),
        _row("A85", "R-DQ", 1098.0, 33.0, 119.0, 96.0,
             "warning_needs_human_review", ["primary_softening_outside_0_to_1"]),
    ]
    return case


def test_draft_states_only_one_row_synthetic_facts() -> None:
    draft = thermal_softening_case._draft_markdown(_synthetic_case())
    assert "共 1 个采集；0 个范围 QC 通过；1 个仍需复核：A1。" in draft
    assert "无法作组间比较：没有同时满足约 1000 ℃、有效变形间隔 9–11 s 且范围 QC 通过的采集。" in draft
    assert "- A1（B-DQ）：范围 QC 未通过" in draft
    assert "本案例未绑定文献条目" in draft and "张玲" not in draft
    for fabricated in ("四个通过项", "A79", "A80", "A84", "A85", "约 1100 ℃", "合成演示标记"):
        assert fabricated not in draft


def test_draft_derives_multi_row_case_without_batch_ids() -> None:
    draft = thermal_softening_case._draft_markdown(_multi_row_case())
    assert "的 2 个通过项中" in draft and "B-DQ 主软化率为 48.00–48.00%（n=1）" in draft
    assert "R-DQ 主软化率为 61.00–61.00%（n=1）" in draft
    assert "其余 1 个采集（温度 1100–1100 ℃）中 1 个 2% 主结果超过 100%" in draft
    assert "- A7（B-DQ）：范围 QC 未通过（QC 标记：primary_softening_outside_0_to_1）" in draft
    for fabricated in ("A79", "A80", "A84", "A85", "四个通过项", "张玲"):
        assert fabricated not in draft


def test_real_batch_shape_keeps_its_own_warnings_and_literature_caveats() -> None:
    draft = thermal_softening_case._draft_markdown(_real_batch_shape_case())
    assert "的 4 个通过项中" in draft
    assert "B-DQ 主软化率为 48.00–52.00%（n=2）" in draft
    assert "R-DQ 主软化率为 61.00–66.00%（n=2）" in draft
    assert "- A79（B-DQ）：范围 QC 未通过" in draft
    assert "- A80、A84：5% 对照同样超过 100%" in draft
    assert "文献（仅作方法依据）：张玲（2007）" in draft
    assert "论文的约 20% 回复、超过 90% 完全再结晶判据不直接移植到本批" in draft
    for fabricated in ("四个通过项", "合成演示标记"):
        assert fabricated not in draft


def test_draft_marks_synthetic_demo_packages() -> None:
    case = _synthetic_case()
    case["evidence_class"] = "synthetic_demo_data"
    draft = thermal_softening_case._draft_markdown(case)
    assert "合成演示标记" in draft and "synthetic_demo_data" in draft
    assert "不代表已核验真实论文 PDF" in draft
    assert "合成演示标记" not in thermal_softening_case._draft_markdown(_synthetic_case())


def test_published_draft_is_derived_from_the_case(tmp_path: Path) -> None:
    case = _multi_row_case()
    destination = publish_softening_case(case, output_root=tmp_path / "cases")
    draft = (destination / "analysis_draft.md").read_text(encoding="utf-8")
    assert "共 3 个采集；2 个范围 QC 通过；1 个仍需复核：A7。" in draft
    assert "A79" not in draft and "四个通过项" not in draft
