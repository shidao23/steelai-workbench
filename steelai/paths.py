import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROCESSED = DATA / "processed"
INDEX = DATA / "index"
PROJECT_LOG = ROOT / "project_log"
OUTPUTS = ROOT / "outputs"
REPORTS = OUTPUTS / "reports"
PORTFOLIO = OUTPUTS / "portfolio"
MODEL_LAB = OUTPUTS / "model_lab"
RESEARCH_CASES = OUTPUTS / "research_cases"
AGENT_EVALUATIONS = OUTPUTS / "agent_evaluations"


def ensure_runtime_dirs() -> None:
    for path in (
        PROCESSED, INDEX, PROJECT_LOG, REPORTS, PORTFOLIO, MODEL_LAB,
        RESEARCH_CASES, AGENT_EVALUATIONS,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _local_root(environment_key: str, setting_key: str, fallback: Path) -> Path:
    """Resolve a trusted local project root without storing machine paths in Git.

    Precedence: environment variable, then the ignored ``config/settings.toml``
    ``[tools]`` table, then the pre-migration sibling layout. The owners moved to
    the Life knowledge container while the shared platform stayed in place, so
    each root is resolved independently instead of from one shared parent.
    """
    value = (os.environ.get(environment_key) or "").strip()
    if not value:
        try:
            from steelai.settings import load_settings

            value = str(load_settings().get("tools", {}).get(setting_key) or "").strip()
        except (OSError, ValueError):
            value = ""
    return Path(value).expanduser() if value else fallback


LEGACY_PROJECTS_ROOT = ROOT.parent


def life_knowledge_root() -> Path:
    """Container holding the migrated ``LifeAgents`` and ``AI_assistant`` owners."""
    return _local_root("PAOS_LIFE_KNOWLEDGE_ROOT", "life_knowledge_root", LEGACY_PROJECTS_ROOT)


def agent_platform_root() -> Path:
    """Shared Shidao platform directory; not migrated and kept in place."""
    return _local_root("SHIDAO_PLATFORM", "agent_platform_root", LEGACY_PROJECTS_ROOT / "_agent_platform")


# SteelData moved from a plain sibling directory to a numbered one inside the
# Engineering container. The legacy name stays first so a pre-migration
# checkout still resolves, and the numbered name covers the migrated layout.
STEELDATA_SIBLING_NAMES = ("SteelData", "02_SteelData")


def legacy_steeldata_project() -> Path | None:
    """First existing sibling SteelData checkout, legacy name then migrated name.

    Returns ``None`` when neither layout is present, so callers can report the
    project as unavailable instead of pointing at a directory that never exists.
    This is only the fallback: an explicit ``tools.steeldata_project`` wins.
    """
    for name in STEELDATA_SIBLING_NAMES:
        candidate = LEGACY_PROJECTS_ROOT / name
        if candidate.is_dir():
            return candidate.resolve()
    return None


# The Life knowledge container prefixes each owner directory with a two-digit
# number. The import identity stays the pre-migration name so existing
# ``import LifeAgents`` / ``from AI_assistant...`` call sites keep working.
LIFE_OWNER_DIRECTORIES = {
    "LifeAgents": "01_LifeAgents",
    "AI_assistant": "02_Life_Assistant",
}


def life_owner_directory(alias: str) -> Path:
    """Real directory of a Life owner, prefixed name first then the legacy name."""
    root = life_knowledge_root()
    directory = root / LIFE_OWNER_DIRECTORIES.get(alias, alias)
    return directory if directory.is_dir() else root / alias


def import_life_owner(alias: str):
    """Load a migrated Life owner package under its stable, pre-migration name.

    The package is loaded straight from its real directory so submodule imports
    such as ``LifeAgents.catalog`` or ``AI_assistant.life_data.records`` keep one
    module identity. An already-imported package is reused unchanged.
    """
    import importlib.util
    import sys

    existing = sys.modules.get(alias)
    if existing is not None:
        return existing
    directory = life_owner_directory(alias)
    spec = importlib.util.spec_from_file_location(
        alias, directory / "__init__.py", submodule_search_locations=[str(directory)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Life owner package is unavailable: {alias}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module
