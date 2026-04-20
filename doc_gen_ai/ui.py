import base64
import logging
import threading
import traceback
import uuid
from datetime import datetime

import ipywidgets as widgets
from IPython.display import HTML, Javascript, clear_output, display

from . import config
from .parsing import _get_uploaded_files, extract_text
from .llm import _discover_template, _research_inputs, _generate_section, _assemble_docx
from .storage import load_folder_templates

logger = logging.getLogger(__name__)

_CSS = """
<style>
.dg-app { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }

.dg-header {
    background: #1e293b;
    color: #f8fafc;
    border-radius: 10px 10px 0 0;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 0;
}
.dg-header h1 { font-size: 18px; font-weight: 700; margin: 0; color: #f8fafc; }
.dg-header p  { font-size: 12px; color: #94a3b8; margin: 0; }

.dg-body {
    background: #f1f5f9;
    border-radius: 0 0 10px 10px;
    padding: 20px;
    border: 1px solid #e2e8f0;
    border-top: none;
}

.dg-panel {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 20px;
    min-width: 0;
}

.dg-section-title {
    font-size: 14px;
    font-weight: 700;
    color: #1e293b;
    margin: 0 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid #e2e8f0;
}

.dg-upload-label {
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    margin-bottom: 4px;
}
.dg-hint { font-size: 12px; color: #64748b; margin-bottom: 8px; }

.dg-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 20px;
    margin-left: 6px;
    vertical-align: middle;
}
.dg-badge-blue   { background: #dbeafe; color: #1d4ed8; }
.dg-badge-purple { background: #ede9fe; color: #6d28d9; }

.dg-file-item {
    display: flex;
    align-items: center;
    gap: 8px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 5px 8px;
    margin-bottom: 4px;
    font-size: 13px;
}
.dg-file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #334155; }
.dg-file-size { font-size: 11px; color: #94a3b8; flex-shrink: 0; }

.dg-divider { border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }

.dg-job {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 10px;
    background: #f8fafc;
    font-size: 13px;
}
.dg-job-complete { border-color: #86efac; background: #f0fdf4; }
.dg-job-error    { border-color: #fca5a5; background: #fff5f5; }

.dg-job-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.dg-job-type   { font-weight: 600; color: #1e293b; }

.dg-status-badge {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 20px;
    text-transform: uppercase;
}
.dg-status-queued   { background: #e2e8f0; color: #475569; }
.dg-status-running  { background: #dbeafe; color: #1e40af; }
.dg-status-complete { background: #dcfce7; color: #15803d; }
.dg-status-error    { background: #fee2e2; color: #b91c1c; }

.dg-progress-text { font-size: 12px; color: #64748b; margin-top: 4px; }
.dg-error-text    { font-size: 12px; color: #dc2626; margin-top: 4px; }

.dg-empty {
    text-align: center;
    color: #94a3b8;
    font-size: 13px;
    padding: 24px 12px;
    border: 1px dashed #cbd5e1;
    border-radius: 8px;
}

.widget-button.dg-btn-generate {
    background: #2563eb !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
}
.widget-button.dg-btn-generate:disabled {
    background: #93c5fd !important;
    cursor: not-allowed !important;
}
.widget-button.dg-btn-download {
    background: #16a34a !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
    font-size: 12px !important;
}
</style>
"""


def _human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"


def _file_emoji(name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"pdf": "📕", "docx": "📘", "doc": "📘",
            "xlsx": "📗", "xls": "📗", "pptx": "📙", "ppt": "📙"}.get(ext, "📄")


def launch_app(llm_connection_id: str = None, serp_api_key: str = None, managed_folder_id: str = None):
    """Build and display the V&V Document Generator UI.

    Args:
        llm_connection_id: Dataiku LLM Mesh connection ID. Falls back to config default.
        serp_api_key: SerpAPI key for web search augmentation.
        managed_folder_id: Dataiku managed folder containing doc type template subfolders.
                           Falls back to config default ("doc_templates").
    """
    if llm_connection_id:
        config.DEFAULT_LLM_CONNECTION_ID = llm_connection_id
    if serp_api_key:
        config.SERP_API_KEY = serp_api_key
    if managed_folder_id:
        config.MANAGED_FOLDER_ID = managed_folder_id

    _state = {
        "input_files": {},
        "jobs": {},
    }
    _lock = threading.Lock()

    FULL_WIDTH  = widgets.Layout(width="100%")
    UPLOAD_BTN  = widgets.Layout(width="100%", margin="4px 0")
    OUTPUT_AREA = widgets.Layout(width="100%", min_height="40px")

    out_input_files = widgets.Output(layout=OUTPUT_AREA)
    out_jobs        = widgets.Output(layout=OUTPUT_AREA)

    # ── File list renderer ────────────────────────────────────────────────────

    def _render_file_list(file_type: str):
        out = out_input_files
        with _lock:
            files = dict(_state[f"{file_type}_files"])

        out.clear_output(wait=True)
        with out:
            if not files:
                display(HTML('<div class="dg-hint" style="margin:4px 0">No files uploaded yet.</div>'))
                return
            for fid, info in files.items():
                icon = _file_emoji(info["name"])
                size = _human_size(len(info["content_bytes"]))
                remove_btn = widgets.Button(
                    description="✕",
                    layout=widgets.Layout(width="28px", height="26px", padding="0"),
                    style=widgets.ButtonStyle(button_color="#fee2e2"),
                )

                def _make_handler(file_id, ft):
                    def _handler(b):
                        with _lock:
                            _state[f"{ft}_files"].pop(file_id, None)
                        _render_file_list(ft)
                        _update_generate_btn()
                    return _handler

                remove_btn.on_click(_make_handler(fid, file_type))
                row = widgets.HBox(
                    [
                        widgets.HTML(
                            f'<div class="dg-file-item">'
                            f'{icon} <span class="dg-file-name" title="{info["name"]}">{info["name"]}</span>'
                            f'<span class="dg-file-size">{size}</span>'
                            f"</div>",
                            layout=widgets.Layout(flex="1"),
                        ),
                        remove_btn,
                    ],
                    layout=widgets.Layout(align_items="center", margin="0 0 4px 0"),
                )
                display(row)

    # ── Jobs renderer ─────────────────────────────────────────────────────────

    def _render_jobs():
        out_jobs.clear_output(wait=True)
        with _lock:
            jobs = {jid: dict(j) for jid, j in _state["jobs"].items()}

        with out_jobs:
            if not jobs:
                display(HTML('<div class="dg-empty">No documents generated yet.</div>'))
                return

            for jid, job in sorted(jobs.items(), key=lambda x: x[1].get("created_at", ""), reverse=True):
                status = job["status"]
                status_cls = f"dg-status-{status}"
                status_label = {
                    "queued": "Queued", "running": "Running…",
                    "complete": "Complete", "error": "Error",
                }.get(status, status)

                job_cls = "dg-job"
                if status == "complete":
                    job_cls += " dg-job-complete"
                elif status == "error":
                    job_cls += " dg-job-error"

                progress_html = ""
                if status in ("queued", "running"):
                    progress_html = f'<div class="dg-progress-text">{job.get("progress", "")}</div>'
                elif status == "error":
                    progress_html = f'<div class="dg-error-text">⚠ {job.get("error", "Unknown error")}</div>'

                display(HTML(
                    f'<div class="{job_cls}">'
                    f'  <div class="dg-job-header">'
                    f'    <span class="dg-job-type">{job["doc_type"]}</span>'
                    f'    <span class="dg-status-badge {status_cls}">{status_label}</span>'
                    f"  </div>"
                    f"  {progress_html}"
                    f"</div>"
                ))

                if status == "complete":
                    dl_btn = widgets.Button(
                        description="⬇ Download .docx",
                        layout=widgets.Layout(width="160px", height="30px"),
                    )
                    dl_btn.add_class("dg-btn-download")

                    def _make_dl(job_id):
                        def _dl(b):
                            with _lock:
                                j = _state["jobs"].get(job_id)
                            if j and j.get("result_bytes"):
                                b64 = base64.b64encode(j["result_bytes"]).decode()
                                slug = j["doc_type"].lower().replace(" ", "_")
                                fname = f"{slug}_{datetime.now().strftime('%Y%m%d')}.docx"
                                display(Javascript(
                                    f"var a=document.createElement('a');"
                                    f"a.href='data:application/octet-stream;base64,{b64}';"
                                    f"a.download='{fname}';"
                                    f"document.body.appendChild(a);a.click();"
                                    f"document.body.removeChild(a);"
                                ))
                        return _dl

                    dl_btn.on_click(_make_dl(jid))
                    display(dl_btn)

    # ── Generate button state ─────────────────────────────────────────────────

    def _update_generate_btn():
        with _lock:
            has_input = bool(_state["input_files"])
        btn_generate.disabled = not (has_input and w_doc_type.value)

    # ── File upload handler ───────────────────────────────────────────────────

    def _handle_upload(upload_widget, status_out: widgets.Output):
        files = _get_uploaded_files(upload_widget)
        if not files:
            return
        with status_out:
            clear_output(wait=True)
            display(HTML(f'<span style="color:#2563eb;font-size:12px">↑ Uploading {len(files)} file(s)…</span>'))

        added = 0
        for f in files:
            if f["content_bytes"]:
                fid = str(uuid.uuid4())
                with _lock:
                    _state["input_files"][fid] = {
                        "name": f["name"],
                        "content_bytes": f["content_bytes"],
                    }
                added += 1

        with status_out:
            clear_output(wait=True)
            if added:
                display(HTML(f'<span style="color:#16a34a;font-size:12px">✓ {added} file(s) added</span>'))

        _render_file_list("input")
        _update_generate_btn()
        upload_widget.value = {} if isinstance(upload_widget.value, dict) else ()

    # ── Generation job runner ─────────────────────────────────────────────────

    def _run_job(job_id: str, doc_type: str, connection_id: str):
        def _set(status, **kw):
            with _lock:
                _state["jobs"][job_id].update({"status": status, **kw})
            _render_jobs()

        try:
            _set("running", progress="Extracting text from input documents…")
            with _lock:
                input_files = list(_state["input_files"].values())

            input_texts = [extract_text(f["name"], f["content_bytes"]) for f in input_files]

            _set("running", progress=f"Loading templates from '{config.MANAGED_FOLDER_ID}/{doc_type}'…")
            raw_templates = load_folder_templates(doc_type)
            if not raw_templates:
                raise ValueError(
                    f"No template files found under '{doc_type}/' in managed folder '{config.MANAGED_FOLDER_ID}'. "
                    "Upload at least one example document to that subfolder before generating."
                )
            template_texts = [extract_text(fname, fbytes) for fname, fbytes in raw_templates]

            _set("running", progress="Analysing template documents…")
            structure = _discover_template(template_texts, doc_type, connection_id=connection_id)

            _set("running", progress="Deep-researching input documents…")
            research  = _research_inputs(input_texts, doc_type, connection_id=connection_id)

            style    = structure.get("style_notes", "")
            reg_lang = structure.get("regulatory_language", [])
            sections = structure.get("sections", [])
            total    = len(sections)
            sections_out = []

            for i, section in enumerate(sections, 1):
                _set("running", progress=f"Generating section {i}/{total}: {section['heading']}…")
                content = _generate_section(
                    doc_type, section, research, style, reg_lang, connection_id=connection_id
                )
                sections_out.append((section["heading"], content))

            _set("running", progress="Assembling Word document…")
            docx_bytes = _assemble_docx(doc_type, sections_out)

            _set("complete", progress="Done", result_bytes=docx_bytes, error=None)

        except Exception as exc:
            logger.error("Job %s failed:\n%s", job_id, traceback.format_exc())
            _set("error", progress="Failed", error=str(exc))

    # ── Widgets ───────────────────────────────────────────────────────────────

    w_input_upload = widgets.FileUpload(
        accept=".docx,.doc,.pdf,.xlsx,.xls,.pptx,.ppt",
        multiple=True,
        description="Add Files",
        layout=UPLOAD_BTN,
    )
    out_input_status = widgets.Output()

    def _on_input_upload(change):
        _handle_upload(w_input_upload, out_input_status)

    w_input_upload.observe(_on_input_upload, names="value")

    w_doc_type = widgets.Dropdown(
        options=[""] + config.DOC_TYPES,
        value="",
        description="",
        layout=FULL_WIDTH,
        style={"description_width": "0"},
    )
    w_doc_type.observe(lambda c: _update_generate_btn(), names="value")

    w_llm_conn = widgets.Text(
        value="",
        placeholder=config.DEFAULT_LLM_CONNECTION_ID,
        description="",
        layout=FULL_WIDTH,
        style={"description_width": "0"},
    )

    btn_generate = widgets.Button(
        description="⚡  Generate Document",
        disabled=True,
        layout=FULL_WIDTH,
    )
    btn_generate.add_class("dg-btn-generate")
    out_generate_status = widgets.Output()

    def _on_generate(b):
        out_generate_status.clear_output(wait=True)
        doc_type = w_doc_type.value
        if not doc_type:
            with out_generate_status:
                display(HTML('<span style="color:#dc2626;font-size:12px">⚠ Please select a document type.</span>'))
            return

        connection_id = w_llm_conn.value.strip() or None
        job_id = str(uuid.uuid4())

        with _lock:
            _state["jobs"][job_id] = {
                "status": "queued",
                "doc_type": doc_type,
                "progress": "Queued",
                "result_bytes": None,
                "error": None,
                "created_at": datetime.now().isoformat(),
            }

        _render_jobs()

        threading.Thread(
            target=_run_job,
            args=(job_id, doc_type, connection_id),
            daemon=True,
        ).start()

        with out_generate_status:
            display(HTML(
                f'<span style="color:#2563eb;font-size:12px">'
                f'✓ Job started for <b>{doc_type}</b>. '
                f'Progress shown in the Generated Documents panel below.'
                f'</span>'
            ))

    btn_generate.on_click(_on_generate)

    # ── Layout assembly ───────────────────────────────────────────────────────

    left_panel = widgets.VBox([
        widgets.HTML('<p class="dg-section-title">1. Upload Input Documents</p>'),
        widgets.HTML(
            '<p class="dg-upload-label">Input Documents'
            '<span class="dg-badge dg-badge-blue">Source files</span></p>'
            '<p class="dg-hint">Design specs, business docs, configs — .docx .pdf .xlsx .pptx</p>'
        ),
        w_input_upload,
        out_input_status,
        out_input_files,
        widgets.HTML('<hr class="dg-divider">'),
        widgets.HTML(
            f'<p class="dg-upload-label">Templates'
            f'<span class="dg-badge dg-badge-purple">Managed folder</span></p>'
            f'<p class="dg-hint">Loaded automatically from <code>{config.MANAGED_FOLDER_ID}/&lt;Doc Type&gt;/</code></p>'
        ),
    ], layout=widgets.Layout(width="50%", padding="0 10px 0 0"))

    right_panel = widgets.VBox([
        widgets.HTML('<p class="dg-section-title">2. Generate Document</p>'),
        widgets.HTML('<p class="dg-upload-label">Document Type</p>'),
        w_doc_type,
        widgets.HTML(
            '<p class="dg-upload-label" style="margin-top:10px">LLM Connection ID '
            '<span style="font-weight:400;color:#64748b;font-size:12px">(leave blank for default)</span></p>'
        ),
        w_llm_conn,
        widgets.HTML('<div style="height:10px"></div>'),
        btn_generate,
        out_generate_status,
        widgets.HTML('<hr class="dg-divider">'),
        widgets.HTML('<p class="dg-section-title">3. Generated Documents</p>'),
        out_jobs,
    ], layout=widgets.Layout(width="50%", padding="0 0 0 10px"))

    app = widgets.VBox([
        widgets.HTML("""
            <div class="dg-header dg-app">
                <span style="font-size:28px">📄</span>
                <div>
                    <h1>V&amp;V Document Generator</h1>
                    <p>ISO 13485 Software Verification &amp; Validation — Dataiku LLM Mesh</p>
                </div>
            </div>
        """),
        widgets.HBox(
            [left_panel, right_panel],
            layout=widgets.Layout(
                width="100%",
                padding="16px",
                background="#f1f5f9",
                border="1px solid #e2e8f0",
                border_radius="0 0 10px 10px",
            ),
        ),
    ], layout=widgets.Layout(width="100%", max_width="1200px"))

    display(HTML(_CSS))
    display(app)
    _render_file_list("input")
    _render_jobs()
