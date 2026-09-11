# Dependencies and sources

Clara uses the following upstream components. The distribution contains Clara source, dependency specifications and a browser package lock; it does not vendor these projects' source or account data. Installers download their published packages, which retain their upstream terms and license notices.

| Component | Pinned version | Role / source |
|---|---|---|
| Claude Agent SDK | 0.2.152 | Agent loop and native Claude runtime; https://github.com/anthropics/claude-agent-sdk-python |
| Chrome DevTools MCP | 1.9.0 | General Chrome tool connector; https://github.com/ChromeDevTools/chrome-devtools-mcp |
| Windows-MCP | 0.8.5 | Native Windows accessibility/screenshot/action tools; https://github.com/CursorTouch/Windows-MCP |
| FastAPI | 0.141.1 | Local HTTP application; https://github.com/fastapi/fastapi |
| Uvicorn | 0.52.4 | Local ASGI server; https://github.com/encode/uvicorn |
| pypdf | 6.18.0 | PDF reading/manipulation; https://github.com/py-pdf/pypdf |
| python-docx | 1.2.0 | Word documents; https://github.com/python-openxml/python-docx |
| python-pptx | 1.0.2 | Presentations; https://github.com/scanny/python-pptx |
| openpyxl | 3.1.5 | Excel files; https://openpyxl.readthedocs.io/ |
| pip (portable setup helper) | 26.2.1 | Pinned wheel with SHA-256 verification; https://pypi.org/project/pip/26.2.1/ |

The Claude executable is unmodified and distributed by the official SDK, under Anthropic's applicable terms. Login completes through that executable's native flow. The product/billing conditions are linked in README.md.

`requirements.lock` contains the resolved Mac runtime dependency snapshot. `requirements-windows-desktop.txt` pins Windows-MCP separately because its native stack must be installed and checked on Windows. Python's installer resolves platform-specific wheels and conditional dependencies there. Do not describe this archive as a fully offline or Windows-certified installer.
