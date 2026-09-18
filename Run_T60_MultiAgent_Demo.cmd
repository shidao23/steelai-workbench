@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
python -m steelai.multi_agent_orchestrator success
python -m steelai.multi_agent_orchestrator insufficient_evidence
python -m steelai.multi_agent_orchestrator tool_failure
python -m steelai.multi_agent_orchestrator offline_success
endlocal
