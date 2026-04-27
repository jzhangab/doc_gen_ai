"""
doc_gen_ai — V&V Document Generator (Dataiku Notebook, Python 3.9)

Required packages (install once in your Dataiku code env):
    python-docx  PyMuPDF  openpyxl  python-pptx

Managed folder setup:
    project_documentation/   ← upload all project docs here (any mix of .docx .pdf .xlsx .pptx)
    doc_templates/           ← upload one template file per document type
    context_examples/        ← (optional) example documents for writing style reference
    generated_docs/          ← output folder (created automatically by Dataiku)

Place the doc_gen_ai/ package from this repo into your Dataiku project's
lib/python/ directory so it is importable.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CELL 1 — Discover available templates
# ══════════════════════════════════════════════════════════════════════════════

# Set this to your Dataiku managed folder name, then run this cell to see
# which document types are available before configuring Cell 2.
TEMPLATES_FOLDER = "doc_templates"

import sys

for _mod in list(sys.modules):
    if _mod.startswith("doc_gen_ai"):
        del sys.modules[_mod]

from doc_gen_ai.storage import list_folder_filenames

_available = list_folder_filenames(TEMPLATES_FOLDER)
if _available:
    print(f"Templates available in '{TEMPLATES_FOLDER}':")
    for _f in _available:
        print(f"  • {_f}")
    print(f"\nSet DOC_TYPE in Cell 2 to match one of these files.")
else:
    print(f"⚠  No files found in '{TEMPLATES_FOLDER}'. Check the folder name and try again.")


# ══════════════════════════════════════════════════════════════════════════════
# CELL 2 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Document type to generate — must correspond to a template file listed by Cell 1.
DOC_TYPE = "User Guide"

# Dataiku LLM Mesh connection ID. Leave blank to use the library default.
LLM_CONNECTION_ID = ""

# Managed folder names. TEMPLATES_FOLDER is set in Cell 1; change the others
# only if you named your folders differently.
PROJECT_DOCS_FOLDER     = "project_documentation"
CONTEXT_EXAMPLES_FOLDER = "context_examples"
OUTPUT_FOLDER           = "generated_docs"

print("✓ Configuration set")


# ══════════════════════════════════════════════════════════════════════════════
# CELL 3 — Run
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# CELL 4 — GDP Check (run independently of document generation)
# ══════════════════════════════════════════════════════════════════════════════

# Folder containing documents to audit. Upload any .docx/.pdf/.xlsx/.pptx files.
GDP_CHECK_FOLDER = "gdp_check"

for _mod in list(sys.modules):
    if _mod.startswith("doc_gen_ai"):
        del sys.modules[_mod]

from doc_gen_ai.pipeline import run_gdp_check

run_gdp_check(
    gdp_check_folder=GDP_CHECK_FOLDER,
    connection_id=LLM_CONNECTION_ID or None,
)
