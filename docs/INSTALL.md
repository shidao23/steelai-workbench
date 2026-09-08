# 从零安装

## 支持范围

- Python 3.12（CI 与本次公开候选验收版本；主依赖已固定到本次验收版本）
- Windows 10/11、macOS 或 Linux
- 核心界面和离线测试不需要 GPU，也不需要 API 密钥

## Windows PowerShell

```powershell
git clone <发布后的仓库地址> SteelAI-Workbench
cd SteelAI-Workbench
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m steelai.public_workspace
python -m steelai.public_release_audit
python -m unittest discover -s tests -v
streamlit run app.py
```

浏览器打开 `http://127.0.0.1:8501`。也可以在 Windows 中双击 `Start_SteelAI.bat`。

## macOS / Linux

```bash
git clone <发布后的仓库地址> SteelAI-Workbench
cd SteelAI-Workbench
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m steelai.public_workspace
python -m steelai.public_release_audit
python -m unittest discover -s tests -v
streamlit run app.py
```

## 可选云模型

没有密钥时核心数据处理、物理公式、质量门禁、统计和 T40 演示仍可使用。只有明确启用 Research Agent 时才需要在当前终端设置所选供应商的 API 密钥；密钥只放在环境变量中，不写入配置文件或仓库。

## 独立模块说明

SteelData 与 SteelStats 在完整本地研发环境中保持同级独立项目和独立虚拟环境。公开候选仓库可以单独安装、浏览界面和运行离线测试；跨项目 T40 完整重放需要另外取得相应模块，并按各模块文档配置路径。这一限制不会被安装脚本隐藏。
