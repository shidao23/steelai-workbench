from __future__ import annotations

import runpy
from pathlib import Path

import streamlit as st


VIEW_ROOT = Path(__file__).resolve().parent / "views"


def render_view(filename: str) -> None:
    """Render one legacy feature view inside a consolidated navigation page."""
    target = (VIEW_ROOT / Path(filename).name).resolve()
    if target.parent != VIEW_ROOT.resolve() or not target.exists():
        raise FileNotFoundError(f"Unknown workbench view: {filename}")
    st.session_state["_steelai_embedded_view"] = True
    try:
        runpy.run_path(str(target), run_name=f"steelai_embedded_{target.stem}")
    finally:
        st.session_state.pop("_steelai_embedded_view", None)
