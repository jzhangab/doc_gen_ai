from datetime import datetime

from . import config
from .llm import (
    assemble_docx, critique_document, deep_research,
    discover_template_structure, fix_section_content,
    generate_section, select_relevant_templates,
)
from .parsing import extract_text
from .storage import get_file_url, list_folder_filenames, load_all_files, load_files_by_name, save_file


def run(
    doc_type: str,
    connection_id: str = None,
    project_docs_folder: str = None,
    templates_folder: str = None,
    output_folder: str = None,
) -> bytes:
    """Generate a V&V document from project documentation.

    Reads all files from project_docs_folder, conducts deep research,
    loads matching templates, generates each section, assembles a .docx,
    and saves it to output_folder.

    Returns the raw docx bytes.
    """
    if doc_type not in config.DOC_TYPES:
        raise ValueError(
            f"Unknown doc_type '{doc_type}'. Valid types:\n  " + "\n  ".join(config.DOC_TYPES)
        )
    if connection_id:
        config.DEFAULT_LLM_CONNECTION_ID = connection_id
    if project_docs_folder:
        config.PROJECT_DOCS_FOLDER = project_docs_folder
    if templates_folder:
        config.TEMPLATES_FOLDER = templates_folder
    if output_folder:
        config.OUTPUT_FOLDER = output_folder

    conn = config.DEFAULT_LLM_CONNECTION_ID

    # ── Step 1: Load project documentation ───────────────────────────────────
    print(f"[1/5] Loading project documentation from '{config.PROJECT_DOCS_FOLDER}'…")
    raw_docs = load_all_files(config.PROJECT_DOCS_FOLDER)
    if not raw_docs:
        raise ValueError(
            f"No documents found in managed folder '{config.PROJECT_DOCS_FOLDER}'. "
            "Upload your project documentation files there first."
        )
    print(f"      {len(raw_docs)} file(s): {', '.join(n for n, _ in raw_docs)}")
    doc_texts = [extract_text(fname, data) for fname, data in raw_docs]

    # ── Step 2: Discover relevant templates ──────────────────────────────────
    print(f"[2/5] Discovering templates for '{doc_type}' in '{config.TEMPLATES_FOLDER}'…")
    all_filenames = list_folder_filenames(config.TEMPLATES_FOLDER)
    if not all_filenames:
        raise ValueError(
            f"Managed folder '{config.TEMPLATES_FOLDER}' is empty or inaccessible. "
            "Upload template documents there first."
        )
    print(f"      {len(all_filenames)} file(s) available: {', '.join(all_filenames)}")
    selected = select_relevant_templates(all_filenames, doc_type, connection_id=conn)
    if not selected:
        raise ValueError(
            f"The LLM could not identify a template for '{doc_type}' among: {', '.join(all_filenames)}"
        )
    print(f"      Selected template: {selected}")
    raw_templates = load_files_by_name(config.TEMPLATES_FOLDER, [selected])
    template_texts = [extract_text(fname, data) for fname, data in raw_templates]

    # ── Step 3: Deep research ─────────────────────────────────────────────────
    print(f"[3/5] Conducting deep research on project documentation…")
    research = deep_research(doc_texts, doc_type, connection_id=conn)
    populated = [k for k, v in research.items() if v]
    print(f"      Extracted fields: {', '.join(populated)}")

    # ── Step 4: Analyse template structure ────────────────────────────────────
    print(f"[4/5] Analysing template structure…")
    structure = discover_template_structure(template_texts, doc_type, connection_id=conn)
    sections = structure.get("sections", [])
    style = structure.get("style_notes", "")
    reg_lang = structure.get("regulatory_language", [])
    print(f"      {len(sections)} section(s) identified")

    # ── Step 5: Generate sections and assemble ────────────────────────────────
    print(f"[5/5] Generating {len(sections)} section(s)…")
    sections_out = []
    for i, section in enumerate(sections, 1):
        print(f"      [{i}/{len(sections)}] {section['heading']}")
        content = generate_section(doc_type, section, research, style, reg_lang, connection_id=conn)
        sections_out.append((section["heading"], content))

    # ── Step 6: Critique and fix ──────────────────────────────────────────────
    print("[6/6] Critiquing document…")

    # Remove structural duplicates (same heading) before LLM critique
    seen_headings: set = set()
    deduped: list = []
    for heading, content in sections_out:
        key = heading.strip().lower()
        if key in seen_headings:
            print(f"      Removed duplicate section: '{heading}'")
        else:
            seen_headings.add(key)
            deduped.append((heading, content))
    sections_out = deduped

    issues = critique_document(doc_type, sections_out, connection_id=conn)

    if issues:
        print(f"      {len(issues)} issue(s) found — fixing…")
        for issue in issues:
            idx = issue.get("index")
            if idx is None or not (0 <= idx < len(sections_out)):
                continue
            heading, content = sections_out[idx]
            desc = issue.get("description", "")
            itype = issue.get("type", "")
            print(f"      [{itype}] '{heading}': {desc}")
            fixed = fix_section_content(
                doc_type, heading, content, desc, connection_id=conn
            )
            sections_out[idx] = (heading, fixed)
    else:
        print("      No issues found.")

    print("      Assembling Word document…")
    docx_bytes = assemble_docx(doc_type, sections_out)

    # ── Save output ───────────────────────────────────────────────────────────
    slug = doc_type.lower().replace(" ", "_")
    filename = f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    save_file(config.OUTPUT_FOLDER, filename, docx_bytes)

    print(f"\n✓ Done — '{filename}' saved to '{config.OUTPUT_FOLDER}'")
    _display_download_link(filename, config.OUTPUT_FOLDER)

    return docx_bytes


def _display_download_link(filename: str, folder_name: str) -> None:
    url = get_file_url(folder_name, filename)
    try:
        from IPython.display import HTML, display
        if url:
            display(HTML(
                f'<a href="{url}" target="_blank" '
                f'style="display:inline-block;margin-top:8px;padding:8px 16px;'
                f'background:#2563eb;color:#fff;border-radius:6px;'
                f'text-decoration:none;font-family:sans-serif;font-size:13px;">'
                f'⬇ Download {filename}</a>'
            ))
        else:
            display(HTML(
                f'<span style="font-family:sans-serif;font-size:13px;color:#64748b">'
                f'Saved: {filename} (open the {folder_name} folder to download)</span>'
            ))
    except Exception:
        if url:
            print(f"Download: {url}")
        else:
            print(f"Saved: {filename}")
