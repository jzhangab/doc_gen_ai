"""
doc_gen_ai — V&V Document Generator (Dataiku Notebook, Python 3.9)

Required packages (install once in your Dataiku code env):
    python-docx  PyMuPDF  openpyxl  python-pptx

Managed folder setup:
    project_documentation/   ← upload all project docs here (any mix of .docx .pdf .xlsx .pptx)
    doc_templates/
        Administration Guide/          ← one subfolder per doc type
        User Guide/
        System Test Protocol/
        ...                            ← add subfolders only for types you intend to generate
    generated_docs/                    ← output folder (created automatically by Dataiku)

Place the doc_gen_ai/ package from this repo into your Dataiku project's
lib/python/ directory so it is importable.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CELL 1 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Document type to generate. Must match one of:
#   Administration Guide | Infrastructure Configuration Specification
#   Installation Checklist Protocol | Requirement and Design Specification
#   System Support Plan | System Test Protocol | User Guide | Verification Plan
DOC_TYPE = "User Guide"

# Dataiku LLM Mesh connection ID. Leave blank to use the library default.
LLM_CONNECTION_ID = ""

# Managed folder names. Change only if you named yours differently.
PROJECT_DOCS_FOLDER      = "project_documentation"
TEMPLATES_FOLDER         = "doc_templates"
CONTEXT_EXAMPLES_FOLDER  = "context_examples"
OUTPUT_FOLDER            = "generated_docs"

print("✓ Configuration set")


# ══════════════════════════════════════════════════════════════════════════════
# CELL 2 — Run
# ══════════════════════════════════════════════════════════════════════════════

import importlib
import sys

# Flush any cached doc_gen_ai modules so Dataiku always loads the latest code.
for _mod in list(sys.modules):
    if _mod.startswith("doc_gen_ai"):
        del sys.modules[_mod]

from doc_gen_ai.pipeline import run

run(
    doc_type=DOC_TYPE,
    connection_id=LLM_CONNECTION_ID or None,
    project_docs_folder=PROJECT_DOCS_FOLDER,
    templates_folder=TEMPLATES_FOLDER,
    context_examples_folder=CONTEXT_EXAMPLES_FOLDER,
    output_folder=OUTPUT_FOLDER,
)
