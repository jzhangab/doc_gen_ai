import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

from . import config
from .llm import (
    assemble_docx, assemble_summary_docx, critique_document, deduplicate_sections,
    deep_research, discover_template_structure, extract_writing_context,
    fix_section_content, gdp_check, generate_section, generate_summary,
    select_relevant_templates,
)
from .parsing import extract_text
from .storage import list_folder_filenames, load_all_files, load_files_by_name, save_file


def _normalize_heading(h: str) -> str:
    """Return a canonical form of a heading for duplicate detection.

    Strips leading section numbers, punctuation, and lowercases so that
    headings like '1. Scope', 'Document Scope', and 'scope' all collapse
    to the same key.
    """
    h = re.sub(r'^[\d\.]+\s*', '', h.strip())          # strip leading numbers
    h = re.sub(r'\bdocument\b', '', h, flags=re.I)      # strip common filler word
    h = re.sub(r'[^\w\s]', '', h)                       # strip punctuation
    return re.sub(r'\s+', ' ', h.lower()).strip()


def run(
    doc_type: str,
    connection_id: str = None,
    project_docs_folder: str = None,
    templates_folder: str = None,
    context_examples_folder: str = None,
    output_folder: str = None,
) -> bytes:
    """Generate a V&V document from project documentation.

    Reads all files from project_docs_folder, conducts deep research,
    loads matching templates, generates each section, assembles a .docx,
    and saves it to output_folder.

    Returns the raw docx bytes.
    """
    if connection_id:
        config.DEFAULT_LLM_CONNECTION_ID = connection_id
    if project_docs_folder:
        config.PROJECT_DOCS_FOLDER = project_docs_folder
    if templates_folder:
        config.TEMPLATES_FOLDER = templates_folder
    if context_examples_folder:
        config.CONTEXT_EXAMPLES_FOLDER = context_examples_folder
    if output_folder:
        config.OUTPUT_FOLDER = output_folder

    conn = config.DEFAULT_LLM_CONNECTION_ID

    # ── Step 1: Load project documentation ───────────────────────────────────
    print(f"[1/6] Loading project documentation from '{config.PROJECT_DOCS_FOLDER}'…")
    raw_docs = load_all_files(config.PROJECT_DOCS_FOLDER)
    if not raw_docs:
        raise ValueError(
            f"No documents found in managed folder '{config.PROJECT_DOCS_FOLDER}'. "
            "Upload your project documentation files there first."
        )
    print(f"      {len(raw_docs)} file(s): {', '.join(n for n, _ in raw_docs)}")
    doc_texts = [extract_text(fname, data) for fname, data in raw_docs]

    # ── Step 2: Load context examples ────────────────────────────────────────
    print(f"[2/6] Loading context examples from '{config.CONTEXT_EXAMPLES_FOLDER}'…")
    writing_context = None
    raw_examples = load_all_files(config.CONTEXT_EXAMPLES_FOLDER)
    if raw_examples:
        print(f"      {len(raw_examples)} example(s): {', '.join(n for n, _ in raw_examples)}")
        example_texts = [extract_text(fname, data) for fname, data in raw_examples]
        writing_context = extract_writing_context(example_texts, connection_id=conn)
        print("      Writing context synthesised.")
    else:
        print("      No context examples found — proceeding without style reference.")

    # ── Step 3: Discover relevant templates ──────────────────────────────────
    print(f"[3/6] Discovering templates for '{doc_type}' in '{config.TEMPLATES_FOLDER}'…")
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

    # ── Step 4: Deep research ─────────────────────────────────────────────────
    print(f"[4/6] Conducting deep research on project documentation…")
    research = deep_research(doc_texts, doc_type, connection_id=conn)
    populated = [k for k, v in research.items() if v]
    print(f"      Extracted fields: {', '.join(populated)}")

    # ── Step 5: Analyse template structure ────────────────────────────────────
    print(f"[5/6] Analysing template structure…")
    structure = discover_template_structure(template_texts, doc_type, connection_id=conn)
    sections = structure.get("sections", [])
    style = structure.get("style_notes", "")
    reg_lang = structure.get("regulatory_language", [])
    print(f"      {len(sections)} section(s) identified")

    # Pre-generation dedup: drop template sections whose normalised headings collide
    seen_pre: dict = {}
    unique_sections = []
    for sec in sections:
        key = _normalize_heading(sec["heading"])
        if key in seen_pre:
            print(f"      Merged near-duplicate template section '{sec['heading']}' → '{seen_pre[key]}'")
        else:
            seen_pre[key] = sec["heading"]
            unique_sections.append(sec)
    if len(unique_sections) < len(sections):
        print(f"      {len(sections) - len(unique_sections)} template section(s) merged; "
              f"{len(unique_sections)} unique section(s) remain.")
    sections = unique_sections

    # ── Step 6: Generate sections and assemble ────────────────────────────────
    print(f"[6/7] Generating {len(sections)} section(s)…")
    sections_out = []
    for i, section in enumerate(sections, 1):
        print(f"      [{i}/{len(sections)}] {section['heading']}")
        content = generate_section(
            doc_type, section, research, style, reg_lang,
            writing_context=writing_context, connection_id=conn,
        )
        sections_out.append((section["heading"], content))

    # ── Step 7: Critique, fix, and deduplicate ───────────────────────────────
    print("[7/7] Critiquing document…")

    # Pass 1: hard Python dedup on normalised headings
    seen_headings: dict = {}
    deduped: list = []
    for heading, content in sections_out:
        key = _normalize_heading(heading)
        if key in seen_headings:
            print(f"      Removed duplicate heading: '{heading}' (matches '{seen_headings[key]}')")
        else:
            seen_headings[key] = heading
            deduped.append((heading, content))
    sections_out = deduped

    # Pass 2: LLM critique — fix formatting/incomplete/GDP issues; defer duplicates to dedup
    issues = critique_document(doc_type, sections_out, connection_id=conn)
    fixable = [i for i in issues if i.get("type") != "duplicate"]

    if fixable:
        print(f"      {len(fixable)} fixable issue(s) found — fixing…")
        if len(issues) > len(fixable):
            print(f"      {len(issues) - len(fixable)} duplicate issue(s) deferred to dedup pass.")
        for issue in fixable:
            idx = issue.get("index")
            if idx is None or not (0 <= idx < len(sections_out)):
                continue
            heading, content = sections_out[idx]
            desc = issue.get("description", "")
            itype = issue.get("type", "")
            print(f"      [{itype}] '{heading}': {desc}")
            other_headings = [h for j, (h, _) in enumerate(sections_out) if j != idx]
            fixed = fix_section_content(
                doc_type, heading, content, desc,
                other_headings=other_headings, connection_id=conn,
            )
            sections_out[idx] = (heading, fixed)
    else:
        print("      No fixable issues found.")

    # Pass 3: LLM dedup — run until convergence (max 3 iterations)
    print("      Deduplication pass…")
    for pass_num in range(1, 4):
        before = len(sections_out)
        sections_out = deduplicate_sections(doc_type, sections_out, connection_id=conn)
        removed = before - len(sections_out)
        if removed:
            print(f"      Pass {pass_num}: removed {removed} redundant section(s), "
                  f"{len(sections_out)} remain.")
        else:
            print(f"      Pass {pass_num}: no redundant sections found.")
            break

    # Pass 4: final hard Python dedup by normalised heading (catches anything the LLM missed)
    seen_final: dict = {}
    final_sections: list = []
    for heading, content in sections_out:
        key = _normalize_heading(heading)
        if key in seen_final:
            print(f"      Final pass removed: '{heading}' (matches '{seen_final[key]}')")
        else:
            seen_final[key] = heading
            final_sections.append((heading, content))
    sections_out = final_sections

    print("      Assembling Word document…")
    docx_bytes = assemble_docx(doc_type, sections_out)

    # ── Save output ───────────────────────────────────────────────────────────
    slug = doc_type.lower().replace(" ", "_")
    filename = f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    save_file(config.OUTPUT_FOLDER, filename, docx_bytes)
    print(f"\n✓ Document — '{filename}' saved to '{config.OUTPUT_FOLDER}'")
    _display_download_link(filename, config.OUTPUT_FOLDER)

    # ── Generate 1-page summary ───────────────────────────────────────────────
    print("\nGenerating 1-page executive summary…")
    summary_text = generate_summary(doc_type, sections_out, connection_id=conn)
    summary_bytes = assemble_summary_docx(doc_type, summary_text)
    summary_filename = f"{slug}_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    save_file(config.OUTPUT_FOLDER, summary_filename, summary_bytes)
    print(f"✓ Summary  — '{summary_filename}' saved to '{config.OUTPUT_FOLDER}'")
    _display_download_link(summary_filename, config.OUTPUT_FOLDER)

    return docx_bytes


def run_gdp_check(
    gdp_check_folder: str = None,
    connection_id: str = None,
) -> list:
    """Run a GDP audit on all documents in gdp_check_folder.

    Prints a formatted report and returns the raw issues list.
    """
    if connection_id:
        config.DEFAULT_LLM_CONNECTION_ID = connection_id
    if gdp_check_folder:
        config.GDP_CHECK_FOLDER = gdp_check_folder

    conn = config.DEFAULT_LLM_CONNECTION_ID

    print(f"Loading documents from '{config.GDP_CHECK_FOLDER}'…")
    raw_docs = load_all_files(config.GDP_CHECK_FOLDER)
    if not raw_docs:
        raise ValueError(
            f"No documents found in managed folder '{config.GDP_CHECK_FOLDER}'. "
            "Upload documents to audit there first."
        )
    filenames = [n for n, _ in raw_docs]
    print(f"  {len(raw_docs)} file(s): {', '.join(filenames)}")

    doc_texts = [extract_text(fname, data) for fname, data in raw_docs]

    print("Running GDP audit…")
    issues = gdp_check(doc_texts, connection_id=conn)

    if not issues:
        print("\n✓ No GDP violations found.")
        return []

    print(f"\n{len(issues)} GDP violation(s) found:\n")
    for i, issue in enumerate(issues, 1):
        doc = issue.get("document", "—")
        rule = issue.get("rule", "—")
        location = issue.get("location", "—")
        desc = issue.get("description", "—")
        print(f"  [{i}] {doc} | {rule}")
        print(f"       Location : {location}")
        print(f"       Issue    : {desc}\n")

    return issues


def _display_download_link(filename: str, folder_name: str) -> None:
    try:
        import base64
        import dataiku
        from IPython.display import HTML, display

        folder = dataiku.Folder(folder_name)
        with folder.get_download_stream(f"/{filename}") as stream:
            data = stream.read()

        b64 = base64.b64encode(data).decode("ascii")
        mime = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        display(HTML(
            f'<a href="data:{mime};base64,{b64}" download="{filename}" '
            f'style="display:inline-block;margin-top:8px;padding:8px 16px;'
            f'background:#2563eb;color:#fff;border-radius:6px;'
            f'text-decoration:none;font-family:sans-serif;font-size:13px;">'
            f'⬇ Download {filename}</a>'
        ))
    except Exception as exc:
        logger.warning("Could not create download link for %s: %s", filename, exc)
        print(f"Saved: {filename}  (open the '{folder_name}' folder to download)")
