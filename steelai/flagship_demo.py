"""Frozen T40 end-to-end showcase over public synthetic tensile data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from steelai.paths import OUTPUTS, ROOT
from steelai.steeldata_bridge import SteelDataClient, inspect_run, mapping_rows
from steelai.steelstats_bridge import SteelStatsClient, run_statistics_from_steeldata


CONTRACT_VERSION = "1.0"
FIXTURES = ROOT / "demo_data" / "flagship_v1"
FIXTURE_FILES = (
    "SYN-T40-tensile.csv",
    "SYN-T40-unknown-unit.csv",
    "success_suggestion.json",
    "unknown_unit_suggestion.json",
    "review_fixture.json",
    "expected_summary.json",
)
MANIFEST_NAME = "demo_manifest.json"
COMPLETE_NAME = "COMPLETE"


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _publish_directory(staging: Path, destination: Path) -> None:
    for attempt in range(5):
        try:
            staging.rename(destination)
            return
        except PermissionError:
            if attempt == 4 or destination.exists():
                raise
            time.sleep(0.1 * (attempt + 1))


def _relative_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path not in {root / MANIFEST_NAME, root / COMPLETE_NAME}
    }


def _code_fingerprint() -> dict[str, str]:
    sources = {
        "steelai/flagship_demo.py": Path(__file__),
        "steelai/steeldata_bridge.py": ROOT / "steelai" / "steeldata_bridge.py",
        "steelai/steelstats_bridge.py": ROOT / "steelai" / "steelstats_bridge.py",
        "SteelData/steeldata.module.json": ROOT.parent / "SteelData" / "steeldata.module.json",
        "SteelStats/steelstats.module.json": ROOT.parent / "SteelStats" / "steelstats.module.json",
    }
    for project_name, package_name in (("SteelData", "steeldata"), ("SteelStats", "steelstats")):
        package = ROOT.parent / project_name / package_name
        for path in sorted(package.rglob("*.py")):
            sources[f"{project_name}/{path.relative_to(ROOT.parent / project_name).as_posix()}"] = path
    return {name: _sha256(path) for name, path in sources.items()}


def demo_identity() -> tuple[str, dict[str, Any]]:
    missing = [name for name in FIXTURE_FILES if not (FIXTURES / name).is_file()]
    if missing:
        raise ValueError("T40 冻结资料不完整：" + "、".join(missing))
    contract = {
        "contract_version": CONTRACT_VERSION,
        "fixture_sha256": {name: _sha256(FIXTURES / name) for name in FIXTURE_FILES},
        "code_sha256": _code_fingerprint(),
    }
    digest = hashlib.sha256(json.dumps(
        contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return "T40-" + digest[:20].upper(), contract


def verify_flagship_demo(package: str | Path) -> dict[str, Any]:
    root = Path(package).resolve()
    problems: list[str] = []
    manifest_path = root / MANIFEST_NAME
    complete_path = root / COMPLETE_NAME
    if not root.is_dir():
        return {"status": "failed", "problems": ["演示包不存在。"]}
    if not complete_path.is_file():
        problems.append("缺少 COMPLETE 完成标记。")
    try:
        manifest = _json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "failed", "problems": problems + ["演示 manifest 无法读取。"]}
    if manifest.get("contract_version") != CONTRACT_VERSION:
        problems.append("演示契约版本不匹配。")
    if complete_path.is_file():
        expected_marker = f"demo_manifest_sha256={_sha256(manifest_path)}\n"
        try:
            if complete_path.read_text(encoding="utf-8") != expected_marker:
                problems.append("COMPLETE 未绑定当前 demo manifest。")
        except OSError:
            problems.append("COMPLETE 无法读取。")
    if manifest.get("demo_id") != root.name:
        problems.append("目录名与 demo_id 不一致。")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        problems.append("manifest 缺少 artifacts 摘要表。")
        artifacts = {}
    actual_names = set(_relative_files(root))
    declared_names = set(artifacts)
    if actual_names != declared_names:
        problems.append("演示包文件集合与 manifest 不一致。")
    for name, expected in artifacts.items():
        path = PurePosixPath(str(name))
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            problems.append(f"artifact 路径不安全：{name}")
            continue
        target = (root / Path(*path.parts)).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            problems.append(f"artifact 不存在：{name}")
        elif not isinstance(expected, str) or len(expected) != 64 or _sha256(target) != expected:
            problems.append(f"artifact 摘要不匹配：{name}")
    expected_status = manifest.get("acceptance", {}).get("status")
    if expected_status != "passed":
        problems.append("冻结语义验收未通过。")
    return {
        "status": "passed" if not problems else "failed",
        "demo_id": manifest.get("demo_id"),
        "problems": problems,
        "artifact_count": len(artifacts),
    }


def _stage_fixtures(stage: Path) -> tuple[Path, Path]:
    workspace = stage / "workspace"
    inbox = workspace / "inbox_v2" / "flagship_v1"
    fixtures = stage / "fixture_inputs"
    inbox.mkdir(parents=True)
    fixtures.mkdir()
    for name in FIXTURE_FILES:
        shutil.copy2(FIXTURES / name, fixtures / name)
    shutil.copy2(FIXTURES / "SYN-T40-tensile.csv", inbox / "SYN-T40-tensile.csv")
    shutil.copy2(FIXTURES / "SYN-T40-unknown-unit.csv", inbox / "SYN-T40-unknown-unit.csv")
    return workspace, fixtures


def _assert_expected(result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    groups = result.get("groups", [])
    actual_means: dict[str, float] = {}
    actual_ns: set[int] = set()
    for item in groups:
        group = item.get("group", {})
        key = f"{group.get('sample_id')}|{group.get('quantity')}"
        actual_means[key] = float(item.get("statistics", {}).get("mean"))
        actual_ns.add(int(item.get("statistics", {}).get("n")))
    success = expected["success"]
    checks = {
        "group_count": len(groups) == success["groups"],
        "group_n": actual_ns == {success["group_n"]},
        "means": set(actual_means) == set(success["means"]) and all(
            abs(actual_means[key] - float(value)) < 1e-12
            for key, value in success["means"].items()
        ),
    }
    if not all(checks.values()):
        raise ValueError("统计结果与冻结预期不一致：" + json.dumps(checks, ensure_ascii=False))
    return {"status": "passed", "checks": checks, "actual_means": actual_means}


def _render_interpretation(result: dict[str, Any]) -> str:
    by_key = {
        (item["group"]["sample_id"], item["group"]["quantity"]): item["statistics"]
        for item in result["groups"]
    }
    lines = [
        "# SteelAI 描述性解释（公开合成演示）",
        "",
        "> 数据全部为公开合成值；此处只做描述性总结，不做显著性检验、因果判断或工艺推荐。",
        "",
    ]
    labels = (("ys_mpa", "屈服强度", "MPa"), ("uts_mpa", "抗拉强度", "MPa"),
              ("elongation_pct", "伸长率", "%"))
    for quantity, label, unit in labels:
        b = by_key[("SYN-SAMPLE-B", quantity)]
        r = by_key[("SYN-SAMPLE-R", quantity)]
        delta = b["mean"] - r["mean"]
        lines.append(
            f"- {label}：B 组均值 {b['mean']:.3f} {unit}，R 组均值 {r['mean']:.3f} {unit}，"
            f"B−R 为 {delta:+.3f} {unit}；两组均为 n=3。"
        )
    lines += [
        "",
        "所有组级统计由 SteelStats 从逐试样观测计算；QC 未删值、未填补缺失值。",
        "未知单位案例停在 `needs_human`，没有生成标准化结果或统计报告。",
        "",
    ]
    return "\n".join(lines)


def _render_summary(manifest: dict[str, Any]) -> str:
    stages = manifest["stages"]
    return "\n".join([
        "# SteelAI T40 端到端旗舰演示",
        "",
        "> 这是公开合成数据演示，不含真实实验数据或企业机密。",
        "",
        "## 成功链路",
        "",
        f"1. Agent 建议：`{stages['agent_suggestion']['status']}`",
        f"2. 人工决定夹具：`{stages['human_review']['status']}`（明确标记 synthetic fixture）",
        f"3. SteelData 标准化与 QC：`{stages['steeldata']['qc_status']}`",
        f"4. SteelStats 可追溯报告：`{stages['steelstats']['status']}`，6 组，每组 n=3",
        "5. SteelAI 描述性解释：见 `steelai_interpretation.md`",
        "",
        "## 失败链路",
        "",
        "`YS` 没有可信单位，建议状态为 `needs_human`；系统实际尝试执行并被拒绝，未生成结果。",
        "",
        "## 复核",
        "",
        "运行 `Run_Flagship_Demo.cmd` 可重放；manifest 为包内所有成果记录 SHA-256。",
        "",
    ])


def run_flagship_demo(
    output_root: str | Path = OUTPUTS / "flagship_demo", *,
    steeldata: SteelDataClient | None = None,
    steelstats: SteelStatsClient | None = None,
) -> dict[str, Any]:
    demo_id, contract = demo_identity()
    output = Path(output_root).resolve()
    destination = output / demo_id
    if destination.exists():
        verification = verify_flagship_demo(destination)
        if verification["status"] != "passed":
            raise ValueError("同名演示包已存在但未通过完整性复核；系统不会覆盖。")
        return {"status": "complete", "demo_id": demo_id, "demo_dir": str(destination),
                "summary": str(destination / "summary.md"), "reused": True,
                "verification": verification}

    data_client = steeldata or SteelDataClient()
    stats_client = steelstats or SteelStatsClient()
    if not data_client.availability()["ready"] or not stats_client.availability()["ready"]:
        raise ValueError("T40 需要同级 SteelData、SteelStats 项目及其各自独立 .venv。")
    output.mkdir(parents=True, exist_ok=True)
    stage = output / f".tmp-{demo_id}-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        workspace, fixtures = _stage_fixtures(stage)
        review_fixture = _json(fixtures / "review_fixture.json")
        expected = _json(fixtures / "expected_summary.json")

        created = data_client.submit_suggestion(workspace, fixtures / "success_suggestion.json")
        if created.get("status") != "candidate" or created.get("approval_created") is not False:
            raise ValueError("成功案例的 Agent 建议没有停在待人工审核边界。")
        reviewed = data_client.review_suggestion(
            created, "approve", review_fixture["reviewer"], review_fixture["note"],
            workspace=workspace,
        )
        if reviewed.get("status") != "approved":
            raise ValueError("冻结的人工作决定夹具未产生 approved 状态。")
        executed = data_client.execute_suggestion(
            created["suggestion_id"], created["suggestion_sha256"],
            synthetic_demo=True, workspace=workspace,
        )
        run_dir = Path(executed["run_dir"])
        inspection = inspect_run(run_dir)
        if inspection.manifest.get("synthetic") is not True:
            raise ValueError("T40 结果必须明确标记 synthetic=true。")
        fixture_bindings = review_fixture["sample_bindings"]
        rows = mapping_rows(inspection)
        if {row["specimen_id"] for row in rows} != set(fixture_bindings):
            raise ValueError("标准化结果中的试样与冻结人工对应关系不一致。")
        bindings = {row["mapping_key"]: fixture_bindings[row["specimen_id"]] for row in rows}
        statistics = run_statistics_from_steeldata(
            run_dir, bindings, review_fixture["method_version"], review_fixture["reviewer"],
            review_fixture["reviewed_at"], input_root=stage / "steelstats_inputs",
            report_root=stage / "steelstats_reports", client=stats_client,
            allow_synthetic=True,
        )
        statistics_result = _json(Path(statistics["result"]))
        expected_check = _assert_expected(statistics_result, expected)
        (stage / "steelai_interpretation.md").write_text(
            _render_interpretation(statistics_result), encoding="utf-8",
        )

        blocked = data_client.submit_suggestion(workspace, fixtures / "unknown_unit_suggestion.json")
        if blocked.get("status") != expected["failure"]["status"]:
            raise ValueError("未知单位案例没有停在 needs_human。")
        try:
            data_client.execute_suggestion(
                blocked["suggestion_id"], blocked["suggestion_sha256"],
                synthetic_demo=True, workspace=workspace,
            )
        except ValueError as exc:
            rejection = str(exc)
        else:
            raise ValueError("未知单位案例未批准却被执行。")
        if "execution_not_approved" not in rejection:
            raise ValueError("未知单位案例没有返回稳定的未批准拒绝代码。")

        manifest = {
            "contract_version": CONTRACT_VERSION,
            "demo_id": demo_id,
            "title": "SteelAI T40 frozen end-to-end flagship demo",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "privacy": {"public_synthetic_only": True, "real_or_confidential_data": False},
            "identity_contract": contract,
            "stages": {
                "agent_suggestion": {"status": created["status"], "approval_created": False},
                "human_review": {"status": reviewed["status"], "fixture": True,
                                 "fixture_id": review_fixture["fixture_id"]},
                "steeldata": {"status": executed["execution_status"],
                              "qc_status": inspection.manifest["qc_status"], "synthetic": True,
                              "specimens": len(rows)},
                "steelstats": {"status": statistics["statistics"]["verification"],
                               "quality_status": statistics["quality_status"],
                               "group_count": statistics_result["group_count"]},
                "steelai": {"status": "descriptive_only"},
                "unknown_unit_guardrail": {
                    "status": blocked["status"],
                    "uncertainty_fields": blocked["uncertainty_fields"],
                    "execution_started": False,
                    "result_created": False,
                    "rejection_code": "execution_not_approved",
                },
            },
            "acceptance": expected_check,
            "artifacts": {},
        }
        (stage / "summary.md").write_text(_render_summary(manifest), encoding="utf-8")
        manifest["artifacts"] = _relative_files(stage)
        _write_json(stage / MANIFEST_NAME, manifest)
        (stage / COMPLETE_NAME).write_text(
            f"demo_manifest_sha256={_sha256(stage / MANIFEST_NAME)}\n", encoding="utf-8",
        )
        _publish_directory(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    verification = verify_flagship_demo(destination)
    if verification["status"] != "passed":
        raise ValueError("新生成的 T40 演示包未通过完整性复核：" + "；".join(verification["problems"]))
    return {"status": "complete", "demo_id": demo_id, "demo_dir": str(destination),
            "summary": str(destination / "summary.md"), "reused": False,
            "verification": verification}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or verify the frozen SteelAI T40 flagship demo.")
    parser.add_argument("--output", type=Path, default=OUTPUTS / "flagship_demo")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_flagship_demo(args.verify) if args.verify else run_flagship_demo(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"complete", "passed"} else 2
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
