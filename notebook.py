"""
doc_gen_ai — V&V Document Generator (Dataiku Notebook, Python 3.9)

Paste each cell into a separate Dataiku notebook cell and run them in order.

Required packages (install once in your Dataiku code env):
    python-docx  PyMuPDF  openpyxl  python-pptx  ipywidgets

Library setup:
    Place the lib/python/doc_gen_ai/ package from this repo into your
    Dataiku project's lib/python/ directory so it is importable.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CELL 1 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Dataiku LLM Mesh connection ID.
# Leave as "" to use the library default: azureopenai:Azure-OpenAi:gpt-5.2
LLM_CONNECTION_ID = ""

# SerpAPI key for web search augmentation. Leave as "" to disable.
SERP_API_KEY = ""

print("✓ Cell 1 complete — configuration set")


# ══════════════════════════════════════════════════════════════════════════════
# CELL 2 — Launch
# ══════════════════════════════════════════════════════════════════════════════

from doc_gen_ai import launch_app

launch_app(
    llm_connection_id=LLM_CONNECTION_ID or None,
    serp_api_key=SERP_API_KEY or None,
)
