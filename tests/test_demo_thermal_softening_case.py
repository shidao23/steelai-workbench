"""STEEL-V1-03B - acceptance for the one-command offline synthetic demo.

The demo must publish a FIXED synthetic input through the governed pipeline, classify the
Manifest as ``synthetic_demo_data`` with synthetic (never human-approved) sources, keep the
formal path byte-for-byte unchanged, reuse a verified package on a second identical run, refuse
a tampered package without overwriting it, and refuse to enter the formal evidence library.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from steelai.governance import load_verified_manifest, verify_package
from steelai import thermal_softening_case

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "demo_thermal_softening_case.py"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("demo_thermal_softening_case", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_demo_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(_SCRIPT), *args],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=180,
    )


def _formal_shape_case() -> dict[str, object]:
    """The minimal evidence shape the FORMAL path accepts (mirrors the existing fixture)."""
    digest = "a" * 64
    return {
        "case_id": "TSC-" + "F" * 20,
        "status": "analysis_draft_needs_human_review",
        "row_count": 1,
        "passed_count": 0,
        "warning_ids": ["A1"],
        "large_method_difference_passed_ids": [],
        "source_digests": {
            "runs_sha256": digest, "points_sha256": digest, "features_sha256": digest,
            "formal_results_sha256": digest, "method_registry_sha256": digest,
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


def test_demo_cli_publishes_a_verified_synthetic_package(tmp_path: Path) -> None:
    result = _run_demo_cli("--output-root", str(tmp_path / "demo"))
    assert result.returncode == 0, result.stderr
    assert "合成演示" in result.stdout
    assert "非真实测量" in result.stdout and "非科研结论" in result.stdout

    case_id_line = next(line for line in result.stdout.splitlines() if line.startswith("case_id: "))
    case_id = case_id_line.split(": ", 1)[1].strip()
    package = tmp_path / "demo" / case_id
    assert (package / "analysis_draft.md").is_file()
    assert (package / "evidence.json").is_file()

    manifest = load_verified_manifest(package)
    assert manifest.evidence_class == "synthetic_demo_data"
    assert manifest.state == "needs_human"
    assert manifest.result_level == "working_candidate"
    for source in manifest.sources:
        assert source.evidence_class == "synthetic_demo_data"
        assert source.source_status == "synthetic_demo_input"
        assert source.source_status != "human_approved"

    draft = (package / "analysis_draft.md").read_text(encoding="utf-8")
    assert "合成演示标记" in draft and "synthetic_demo_data" in draft
    assert "不代表已核验真实论文 PDF" in draft
    assert "张玲" not in draft and "文献（仅作方法依据）" not in draft
    # Every value in the draft traces back to the fixed synthetic rows.
    assert "48.00" in draft and "130.00" in draft and "D3" in draft
    assert "的 2 个通过项中" in draft and "B-DEMO" in draft and "R-DEMO" in draft

    evidence = json.loads((package / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["evidence_class"] == "synthetic_demo_data"


def test_demo_second_identical_run_reuses_the_verified_package(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    first = _run_demo_cli("--output-root", str(root))
    assert first.returncode == 0, first.stderr
    assert "reused: false" in first.stdout
    second = _run_demo_cli("--output-root", str(root))
    assert second.returncode == 0, second.stderr
    assert "reused: true" in second.stdout
    assert second.stdout == first.stdout.replace("reused: false", "reused: true")


def test_demo_refuses_a_tampered_package_without_overwriting_it(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    first = _run_demo_cli("--output-root", str(root))
    assert first.returncode == 0, first.stderr
    case_id = next(
        line.split(": ", 1)[1].strip()
        for line in first.stdout.splitlines() if line.startswith("case_id: ")
    )
    package = root / case_id
    evidence_path = package / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["row_count"] = 99
    tampered_bytes = json.dumps(evidence).encode("utf-8")
    evidence_path.write_bytes(tampered_bytes)

    second = _run_demo_cli("--output-root", str(root))
    assert second.returncode == 2, second.stdout
    assert "DEMO_REFUSED" in second.stderr
    assert "verification" in second.stderr or "failed" in second.stderr
    assert evidence_path.read_bytes() == tampered_bytes
    assert verify_package(package).status == "invalidated"


def test_demo_refuses_the_same_id_with_different_content(tmp_path: Path) -> None:
    demo = _load_demo_module()
    case = demo.build_synthetic_demo_case()
    destination = thermal_softening_case.publish_softening_case(
        case, output_root=tmp_path, synthetic_demo=True
    )
    assert destination.is_dir()
    conflicting = json.loads(json.dumps(case))
    conflicting["rows"][0]["primary_percent"] = 12.5
    with pytest.raises(ValueError, match="different evidence"):
        thermal_softening_case.publish_softening_case(
            conflicting, output_root=tmp_path, synthetic_demo=True
        )


def test_demo_case_id_is_stable_and_input_derived() -> None:
    demo = _load_demo_module()
    first = demo.build_synthetic_demo_case()
    second = demo.build_synthetic_demo_case()
    assert first == second
    assert first["case_id"] == second["case_id"]
    assert first["case_id"].startswith("TSC-")
    for row in first["rows"]:
        assert row["sample_id"].endswith("-DEMO")


def test_demo_never_enters_the_formal_evidence_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _load_demo_module()
    formal_root = tmp_path / "formal-library"
    formal_root.mkdir()
    monkeypatch.setattr(thermal_softening_case, "CASE_ROOT", formal_root)
    with pytest.raises(ValueError, match="formal evidence library"):
        thermal_softening_case.publish_softening_case(
            demo.build_synthetic_demo_case(),
            output_root=thermal_softening_case.CASE_ROOT,
            synthetic_demo=True,
        )


def test_formal_path_default_remains_real_research_data(tmp_path: Path) -> None:
    import inspect

    signature = inspect.signature(thermal_softening_case.publish_softening_case)
    assert signature.parameters["synthetic_demo"].default is False

    destination = thermal_softening_case.publish_softening_case(
        _formal_shape_case(), output_root=tmp_path / "formal"
    )
    manifest = load_verified_manifest(destination)
    assert manifest.evidence_class == "real_research_data"
    statuses = {source.source_status for source in manifest.sources}
    assert "human_approved" in statuses and "synthetic_demo_input" not in statuses
    evidence = json.loads((destination / "evidence.json").read_text(encoding="utf-8"))
    assert "evidence_class" not in evidence
    draft = (destination / "analysis_draft.md").read_text(encoding="utf-8")
    assert "合成演示标记" not in draft


def test_demo_cli_refuses_a_formal_output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _load_demo_module()
    formal_root = tmp_path / "formal-library"
    formal_root.mkdir()
    monkeypatch.setattr(demo, "OUTPUTS", formal_root)
    monkeypatch.setattr(demo, "DEFAULT_DEMO_ROOT", formal_root / "synthetic_demo")
    result = demo.main(["--output-root", str(formal_root / "thermal_softening_cases")])
    assert result == 2


def test_synthetic_demo_draft_never_claims_reviewed_work(tmp_path: Path) -> None:
    demo = _load_demo_module()
    root = tmp_path / "demo"
    assert demo.main(["--output-root", str(root)]) == 0
    case = demo.build_synthetic_demo_case()
    draft = (root / case["case_id"] / "analysis_draft.md").read_text(encoding="utf-8")
    for banned in ("已复核数据", "已批准正式结果", "重新计算", "使用 T75 冻结方法"):
        assert banned not in draft, banned
    assert "百分比与 QC 标记直接来自固定合成输入" in draft
    assert "未运行 T75 曲线重算" in draft
    assert "没有已批准的正式结果" in draft
    assert "没有真实文献 PDF 核验" in draft
    assert "没有任何经人工复核的真实数据" in draft
    assert "本包不进入正式证据库" in draft


def test_demo_refuses_any_root_equal_to_or_inside_the_formal_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    formal = tmp_path / "formal-library"
    formal.mkdir()
    monkeypatch.setattr(thermal_softening_case, "CASE_ROOT", formal)
    demo = _load_demo_module()
    case = demo.build_synthetic_demo_case()

    for refused_root in (
        formal,                                       # exactly the formal root
        formal / "demo_child",                        # direct child
        formal.parent / formal.name / "sub" / ".." / "demo_child2",  # ".." alias, resolves inside
    ):
        with pytest.raises(ValueError, match="formal evidence library"):
            thermal_softening_case.publish_softening_case(
                case, output_root=refused_root, synthetic_demo=True
            )
    assert not any(formal.iterdir())  # zero write: the formal library stays untouched


# --- S2R-FIX1: explicit classification vs publish parameter consistency ---------------------


def _explicitly_marked_demo_case() -> dict[str, object]:
    """The public synthetic demo case, EXPLICITLY pre-marked as synthetic_demo_data."""
    demo = _load_demo_module()
    case = demo.build_synthetic_demo_case()
    case["evidence_class"] = "synthetic_demo_data"
    return case


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """Byte-exact recursive snapshot of every file below root (empty if root is absent)."""
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("explicit_flag", [None, False], ids=["omitted", "explicit-false"])
def test_marked_synthetic_case_is_refused_without_the_demo_opt_in(
    tmp_path: Path, explicit_flag: bool | None
) -> None:
    case = _explicitly_marked_demo_case()
    root = tmp_path / "empty-output-root"  # an output root that does not exist yet
    kwargs: dict[str, object] = {"output_root": root}
    if explicit_flag is not None:
        kwargs["synthetic_demo"] = explicit_flag

    with pytest.raises(ValueError, match="synthetic_demo=True opt-in") as excinfo:
        thermal_softening_case.publish_softening_case(case, **kwargs)  # type: ignore[arg-type]

    # Stable, path-free rejection: the error never echoes the caller's local paths.
    assert str(tmp_path) not in str(excinfo.value)
    assert "synthetic_demo_data" in str(excinfo.value)
    # Zero write: an output root that did not exist before is still absent afterwards.
    assert not root.exists()


def test_marked_synthetic_case_refusal_leaves_an_existing_root_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "with-sentinel"
    root.mkdir()
    (root / "sentinel.txt").write_bytes(b"S2R-FIX1 sentinel")
    (root / "kept-dir").mkdir()
    (root / "kept-dir" / "nested.bin").write_bytes(bytes(range(256)))
    before = _tree_snapshot(root)

    with pytest.raises(ValueError, match="synthetic_demo=True opt-in"):
        thermal_softening_case.publish_softening_case(
            _explicitly_marked_demo_case(), output_root=root, synthetic_demo=False
        )

    assert _tree_snapshot(root) == before  # no new, removed or altered file anywhere


def test_marked_synthetic_case_still_publishes_with_the_explicit_opt_in(tmp_path: Path) -> None:
    case = _explicitly_marked_demo_case()
    destination = thermal_softening_case.publish_softening_case(
        case, output_root=tmp_path, synthetic_demo=True
    )

    assert verify_package(destination).status == "passed"
    manifest = load_verified_manifest(destination)
    assert manifest.evidence_class == "synthetic_demo_data"
    assert manifest.sources
    for source in manifest.sources:
        assert source.evidence_class == "synthetic_demo_data"
        assert source.source_status == "synthetic_demo_input"
    evidence = json.loads((destination / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["evidence_class"] == "synthetic_demo_data"
