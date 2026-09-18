@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
python -m steelai.research_mcp_server --self-test
python -c "from steelai.research_protocol import run_t61_handoff_demo; import json; print(json.dumps(run_t61_handoff_demo(), ensure_ascii=False, indent=2))"
endlocal
