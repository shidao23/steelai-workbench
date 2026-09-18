"""T64 governed portfolio and public-release package preparation."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from steelai.governance import (
    EvidenceClass,
    GovernanceError,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    build_manifest,
    create_staging_directory,
    digest_value,
    publish_append_only,
    seal_package,
    utc_now,
    verify_package,
    write_json_atomic,
)
from steelai.paths import OUTPUTS, ROOT


CONFIG_PATH = ROOT / "config" / "portfolio_release_v1.0.json"
OUTPUT_ROOT = OUTPUTS / "portfolio_releases"


def _safe_repo_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in value or ":" in value:
        return None
    return value


def load_release_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("GOV-INTEGRITY-001", "blocked", "T64 release config is unreadable") from exc
    if not isinstance(payload, dict):
        raise GovernanceError("GOV-SCHEMA-001", "blocked", "T64 release config must be an object")
    return payload


def validate_release_config(path: Path = CONFIG_PATH, repository: Path = ROOT) -> dict[str, Any]:
    problems: list[str] = []
    payload = load_release_config(path)
    if payload.get("schema_version") != "1.0":
        problems.append("schema_version must be 1.0")
    if payload.get("release_id") != "SteelAI-Workbench-Portfolio-v0.3.0-candidate":
        problems.append("release_id mismatch")
    dependencies = payload.get("dependencies", [])
    if dependencies != ["T57", "T60", "T61", "T62", "T63"]:
        problems.append("T64 dependencies must remain frozen")

    required_assets = payload.get("required_public_assets", [])
    if not isinstance(required_assets, list) or not required_assets:
        problems.append("required_public_assets must be non-empty")
        required_assets = []
    missing: list[str] = []
    asset_paths: set[str] = set()
    for item in required_assets:
        if not isinstance(item, Mapping) or set(item) != {"path", "purpose"}:
            problems.append("required asset fields mismatch")
            continue
        relative = _safe_repo_path(item.get("path"))
        if relative is None:
            problems.append(f"unsafe required asset path: {item.get('path')}")
            continue
        if relative in asset_paths:
            problems.append(f"duplicate required asset: {relative}")
        asset_paths.add(relative)
        if not (repository / Path(*PurePosixPath(relative).parts)).is_file():
            missing.append(relative)
    if missing:
        problems.append("missing required assets: " + ", ".join(sorted(missing)))

    claims = payload.get("capability_claims", [])
    if not isinstance(claims, list) or not claims:
        problems.append("capability_claims must be non-empty")
        claims = []
    claim_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping) or set(claim) != {"claim_id", "claim", "evidence"}:
            problems.append("capability claim fields mismatch")
            continue
        claim_id = str(claim.get("claim_id", ""))
        if not claim_id or claim_id in claim_ids:
            problems.append("claim IDs must be unique and non-empty")
        claim_ids.add(claim_id)
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            problems.append(f"{claim_id} has no evidence")
            continue
        for raw_path in evidence:
            relative = _safe_repo_path(raw_path)
            target = repository / Path(*PurePosixPath(relative).parts) if relative else None
            if target is None or not target.exists():
                problems.append(f"{claim_id} evidence is unavailable: {raw_path}")

    acceptance = payload.get("acceptance", {})
    required_acceptance = {
        "new_environment_replay_required", "video_required", "technical_report_required",
        "t63_measurements_required", "privacy_audit_required", "license_audit_required",
        "claim_to_evidence_mapping_required", "release_and_resume_must_use_same_version",
    }
    if not isinstance(acceptance, Mapping) or set(acceptance) != required_acceptance or not all(acceptance.values()):
        problems.append("T64 acceptance gates must all be explicit and required")

    privacy = payload.get("privacy", {})
    if not isinstance(privacy, Mapping) or any(
        privacy.get(field) is not False
        for field in (
            "raw_private_research_data_allowed", "absolute_local_paths_allowed",
            "secrets_allowed", "unverified_agent_answers_allowed",
        )
    ) or privacy.get("portfolio_status_before_human_review") != "needs_human":
        problems.append("T64 public privacy boundary mismatch")

    return {
        "schema_version": "1.0",
        "status": "passed" if not problems else "failed",
        "release_id": payload.get("release_id"),
        "config_sha256": digest_value(payload),
        "required_asset_count": len(required_assets),
        "claim_count": len(claims),
        "missing_assets": missing,
        "problems": problems,
    }


def _checklist(validation: Mapping[str, Any]) -> str:
    return "\n".join([
        "# T64 岗位作品集与公开发布检查清单",
        "",
        "当前状态：`needs_human`。此包冻结材料和检查规则，不把未完成的视频、清洁环境复现、技术报告或 T63 实测包装成已完成。",
        "",
        "## 发布前必须完成",
        "",
        "- [ ] 在全新环境按 README 启动系统，并重放公开 T40/T62 案例。",
        "- [ ] 完成 24 条 T63 同题实测，保留失败、阻断和无优势结果。",
        "- [ ] 录制约三分钟演示，版本和指标与仓库一致。",
        "- [ ] 完成技术报告或软件型论文初稿，并引用真实数据来源和限制。",
        "- [ ] 完成许可证、隐私、路径、密钥和夸大表述终审。",
        "- [ ] README、演示视频、报告和简历使用同一个 release 版本。",
        "",
        "## 当前机器校验",
        "",
        f"- 发布契约：`{validation['release_id']}`",
        f"- 必需公开资产：{validation['required_asset_count']} 项",
        f"- 能力—证据映射：{validation['claim_count']} 项",
        f"- 配置校验：`{validation['status']}`",
        "",
        "## 能力表述边界",
        "",
        "T62 是公开钢板缺陷分类案例，不是成分—性能模型；T63 在真实测量完成前不能声称智能体提高效率；合成 T40 只能展示工程链路。",
        "",
    ])


def prepare_release_package(*, output_root: Path = OUTPUT_ROOT, config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    validation = validate_release_config(config_path)
    if validation["status"] != "passed":
        raise GovernanceError(
            "GOV-SCHEMA-001", "blocked", "T64 release config failed validation", details=validation,
        )
    config = load_release_config(config_path)
    content = {"config_sha256": validation["config_sha256"], "validation": validation}
    publication_id = "T64-PORTFOLIO-" + digest_value(content)[:20].upper()
    destination = output_root.resolve() / publication_id
    if destination.exists():
        verification = verify_package(destination)
        if verification.status != "passed":
            raise GovernanceError("GOV-INTEGRITY-001", "blocked", "existing T64 package is invalidated")
        return {
            "status": "needs_human", "publication_id": publication_id,
            "package": str(destination), "reused": True,
            "manifest_sha256": verification.manifest_digest, "validation": validation,
        }

    timestamp = utc_now()
    stage = create_staging_directory(output_root, publication_id)
    try:
        write_json_atomic(stage / "release_contract.json", config)
        write_json_atomic(stage / "release_validation.json", validation)
        (stage / "release_checklist.md").write_text(_checklist(validation), encoding="utf-8")
        identity = ResearchObjectIdentity(
            object_type="portfolio_release", object_id=publication_id, revision=1,
            content_digest=digest_value(content), created_at=timestamp,
            created_by="steelai.portfolio_release",
        )
        source = SourceReference(
            source_id="T64-RELEASE-CONTRACT", source_revision=1,
            source_digest=validation["config_sha256"],
            evidence_class=EvidenceClass.HUMAN_CONCLUSION.value,
            source_status="public_release_checklist_requires_human_completion",
            relative_locator="release_contract.json",
        )
        manifest = build_manifest(
            stage, publication_id=publication_id, identity=identity,
            state="needs_human", result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.HUMAN_CONCLUSION, sources=(source,),
            generated_by="steelai.portfolio_release", generated_at=timestamp,
            metadata={
                "feature": "T64", "human_review_required": True,
                "video_and_report_pending": True, "t63_measurements_pending": True,
                "portfolio_eligible": False,
            },
        )
        seal_package(stage, manifest)
        publication = publish_append_only(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return {
        "status": "needs_human", "publication_id": publication_id,
        "package": publication.destination, "reused": publication.reused,
        "manifest_sha256": publication.manifest_digest, "validation": validation,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the governed T64 portfolio release package")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--validate-config", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = validate_release_config() if args.validate_config else prepare_release_package(output_root=args.output_root)
    except GovernanceError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"passed", "needs_human"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
