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
