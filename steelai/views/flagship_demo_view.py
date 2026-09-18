"""T40 flagship demo control and evidence view."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from steelai.flagship_demo import MANIFEST_NAME, run_flagship_demo, verify_flagship_demo
from steelai.paths import OUTPUTS
from steelai.steeldata_bridge import SteelDataClient
from steelai.steelstats_bridge import SteelStatsClient
from steelai.ui import next_step_buttons, setup_page


OUTPUT_ROOT = OUTPUTS / "flagship_demo"


def _latest_verified() -> tuple[Path, dict] | None:
    if not OUTPUT_ROOT.is_dir():
        return None
    for path in sorted(OUTPUT_ROOT.glob("T40-*"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            verification = verify_flagship_demo(path)
        except (OSError, ValueError, json.JSONDecodeError):
            # A stale local package may be unreadable because of Windows ACLs
            # or a partial copy. Keep the page usable and treat it as invalid.
            continue
        if verification["status"] == "passed":
            try:
                return path, json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return None


setup_page(st, "T40 · 端到端旗舰演示", "🏁")
st.caption("公开合成拉伸数据 · 可重放 · 全链路留痕 · 不调用本地 AI")
st.info("演示中的人工批准是明确标记的冻结合成决定夹具，不代表真实实验审核。")

data_ready = SteelDataClient().availability()["ready"]
stats_ready = SteelStatsClient().availability()["ready"]
c1, c2, c3 = st.columns(3)
c1.metric("SteelData", "就绪" if data_ready else "未就绪")
c2.metric("SteelStats", "就绪" if stats_ready else "未就绪")
c3.metric("演示数据", "公开合成")

st.subheader("冻结流程")
st.markdown(
    "陌生 CSV → Agent 字段建议 → 人工决定夹具 → 标准化与 QC → "
    "SteelStats 组级统计 → SteelAI 描述性解释"
)

if st.button("运行 / 复用旗舰演示", type="primary", disabled=not (data_ready and stats_ready)):
    try:
        with st.spinner("正在跨三个独立模块执行并复核完整性……"):
            result = run_flagship_demo(OUTPUT_ROOT)
        st.success("演示通过；复用了已有完整包。" if result["reused"] else "演示通过；已生成新的完整包。")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        st.error(str(exc))

latest = _latest_verified()
if latest is None:
    st.warning("还没有通过完整性复核的 T40 演示包。")
else:
    package, manifest = latest
    stages = manifest["stages"]
    st.subheader("最近一次通过结果")
    a, b, c, d = st.columns(4)
    a.metric("标准化试样", stages["steeldata"]["specimens"])
    b.metric("SteelData QC", stages["steeldata"]["qc_status"])
    c.metric("统计组", stages["steelstats"]["group_count"])
    d.metric("完整性", "passed")
    st.success("成功链路已走通：建议、批准、QC、统计和解释均有审计证据。")
    st.error("失败链路已验证：YS 未知单位 → needs_human → 未批准执行被拒绝 → 无结果。")
    st.code(package.name, language=None)
    st.markdown((package / "steelai_interpretation.md").read_text(encoding="utf-8"))

next_step_buttons(
    st,
    [
        {
            "label": "查看可追溯统计",
            "url": "/analysis?module=statistics",
        },
        {"label": "进入证据验证", "url": "/analysis?module=validation"},
    ],
    key_prefix="flagship",
    note="演示结束后，可以查看统计模块的正式边界，或继续检查允许表述的研究结论。",
)
