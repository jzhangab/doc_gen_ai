import io
import json
import logging
from datetime import datetime

from . import config

logger = logging.getLogger(__name__)


def _trunc(text: str) -> str:
    return text[:config._MAX_CHARS] + "\n...[truncated]" if len(text) > config._MAX_CHARS else text


def _llm_call(messages: list, connection_id: str = None) -> str:
    import dataiku
    conn = connection_id or config.DEFAULT_LLM_CONNECTION_ID
    api_client = dataiku.api_client()
    project = api_client.get_project(dataiku.default_project_key())
    llm = project.get_llm(conn)
    completion = llm.new_completion()
    for msg in messages:
        completion.with_message(msg["content"], msg["role"])
    try:
        completion.with_max_output_tokens(8192)
    except Exception:
        pass
    return completion.execute().text


def _llm_json(messages: list, connection_id: str = None) -> dict:
    raw = _llm_call(messages, connection_id=connection_id).strip()
    if raw.startswith("```"):
        raw = "\n".join(
            ln for ln in raw.splitlines() if not ln.strip().startswith("```")
        ).strip()
    return json.loads(raw)


def select_relevant_templates(filenames: list, doc_type: str, connection_id: str = None) -> str:
    """Return the single filename most consistent with doc_type."""
    file_list = "\n".join(f"- {f}" for f in filenames)
    result = _llm_json([
        {
            "role": "system",
            "content": (
                "You are an expert in ISO 13485 software V&V documentation. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f'I need to generate a "{doc_type}" document.\n\n'
                f"Available files in the templates folder:\n{file_list}\n\n"
                f'Choose the single file whose name most closely matches a "{doc_type}". '
                "Consider abbreviations, version numbers, and partial name matches. "
                'Return JSON: {"selected": "filename"}'
            ),
        },
    ], connection_id=connection_id)
    return result.get("selected", "")


def discover_template_structure(template_texts: list, doc_type: str, connection_id: str = None) -> dict:
    """Analyse example documents and extract section structure, style, and regulatory language."""
    combined = "\n\n---\n\n".join(
        f"[Example {i+1}]\n{_trunc(t)}" for i, t in enumerate(template_texts)
    )
    return _llm_json([
        {
            "role": "system",
            "content": (
                "You are an expert in ISO 13485 software V&V documentation. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f'Analyse these example "{doc_type}" documents and extract their structure.\n\n'
                f"{combined}\n\n"
                "Return JSON:\n"
                '{"sections":[{"heading":"...","description":"...","required_elements":["..."]}],'
                '"style_notes":"...","regulatory_language":["..."]}'
            ),
        },
    ], connection_id=connection_id)


def deep_research(doc_texts: list, doc_type: str, connection_id: str = None) -> dict:
    """Extract comprehensive project intelligence needed to write doc_type."""
    combined = "\n\n---\n\n".join(
        f"[Document {i+1}]\n{_trunc(t)}" for i, t in enumerate(doc_texts)
    )
    return _llm_json([
        {
            "role": "system",
            "content": (
                "You are an expert technical analyst for ISO 13485 regulated software. "
                "Conduct deep research on the provided project documentation and extract "
                "every piece of information that will be needed to author a compliance document. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f'Conduct deep research on these project documents to extract everything '
                f'needed to write a "{doc_type}" per ISO 13485.\n\n'
                f"{combined}\n\n"
                "Return a comprehensive JSON object:\n"
                '{\n'
                '  "system_name": "...",\n'
                '  "system_description": "...",\n'
                '  "purpose": "...",\n'
                '  "requirements": [],\n'
                '  "design_specifications": {},\n'
                '  "testing_methodology": {},\n'
                '  "infrastructure": {},\n'
                '  "stakeholders": [],\n'
                '  "regulatory_context": "...",\n'
                '  "key_decisions": [],\n'
                '  "assumptions": [],\n'
                '  "constraints": [],\n'
                '  "discovered_artifacts": {}\n'
                '}'
            ),
        },
    ], connection_id=connection_id)


def generate_section(
    doc_type: str, section: dict, research: dict,
    style: str, reg_lang: list, connection_id: str = None,
) -> str:
    required = "\n".join(f"- {e}" for e in section.get("required_elements", []))
    reg = "\n".join(f"- {p}" for p in reg_lang[:10])
    return _llm_call([
        {
            "role": "system",
            "content": (
                "You are an expert technical writer for ISO 13485 regulated "
                "software V&V documentation. "
                "Format your response using the following conventions so it renders "
                "correctly in Microsoft Word:\n"
                "- Use ## for sub-headings\n"
                "- Use - for bullet list items\n"
                "- Use 1. 2. 3. for numbered list items\n"
                "- Use **text** for bold\n"
                "- Separate paragraphs with a blank line\n"
                "Do not use any other markdown syntax."
            ),
        },
        {
            "role": "user",
            "content": (
                f'Write the "{section["heading"]}" section for a "{doc_type}" '
                f"document per ISO 13485.\n\n"
                f"Purpose: {section['description']}\n"
                f"Required elements:\n{required}\n\n"
                f"Project research:\n{json.dumps(research, indent=2)[:6000]}\n\n"
                f"Style notes: {style}\n"
                f"Regulatory language to use:\n{reg}\n\n"
                "Write professional, complete content. Do not repeat the section heading."
            ),
        },
    ], connection_id=connection_id)


def assemble_docx(doc_type: str, sections: list) -> bytes:
    import re
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()

    # Margins
    for sec in doc.sections:
        sec.top_margin    = Inches(1)
        sec.bottom_margin = Inches(1)
        sec.left_margin   = Inches(1.25)
        sec.right_margin  = Inches(1.25)

    # Cover
    t = doc.add_heading(doc_type, level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta = doc.add_paragraph(f"Standard: ISO 13485  |  Generated: {datetime.now().strftime('%Y-%m-%d')}")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in meta.runs:
        run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        run.font.size = Pt(10)

    doc.add_page_break()

    for heading, content in sections:
        doc.add_heading(heading, level=1)
        _render_content(doc, content)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _render_content(doc, content: str) -> None:
    import re
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:].strip(), level=3)
            i += 1
            continue

        if stripped.startswith("## "):
            doc.add_heading(stripped[3:].strip(), level=2)
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            para = doc.add_paragraph(style="List Bullet")
            _add_runs(para, stripped[2:])
            i += 1
            continue

        if re.match(r"^\d+\.\s", stripped):
            para = doc.add_paragraph(style="List Number")
            _add_runs(para, re.sub(r"^\d+\.\s+", "", stripped))
            i += 1
            continue

        # Regular paragraph — collect consecutive plain lines
        block = []
        while i < len(lines):
            s = lines[i].strip()
            if not s:
                break
            if s.startswith(("## ", "### ", "- ", "* ")) or re.match(r"^\d+\.\s", s):
                break
            block.append(s)
            i += 1
        if block:
            para = doc.add_paragraph()
            _add_runs(para, " ".join(block))


def _add_runs(para, text: str) -> None:
    import re
    # Split on **bold** tokens
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = para.add_run(part[2:-2])
            run.bold = True
        else:
            para.add_run(part)
