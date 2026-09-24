"""Fill {keywords} into a template and produce .docx or .pdf.

Word templates keep their formatting: a keyword Word split across several runs
("{con" + "tract_no}") is joined into the run where it starts, the other runs
keep their own text and style. Built-on-site templates are HTML. LibreOffice
(headless) turns HTML into .docx / .pdf and .docx into .pdf.
"""

import html
import io
import re
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

KEY_RE = re.compile(r"\{([a-z][a-z0-9_]{0,29})\}")


class RenderError(Exception):
    pass


# ------------------------------------------------------------------ Word


def _fill_paragraph(paragraph, values: dict[str, str]) -> None:
    runs = paragraph.runs
    if not runs:
        return
    text = "".join(r.text for r in runs)
    if "{" not in text:
        return
    matches = [m for m in KEY_RE.finditer(text) if m.group(1) in values]
    if not matches:
        return
    # Where each run starts in the joined text.
    starts, pos = [], 0
    for r in runs:
        starts.append(pos)
        pos += len(r.text)

    def run_at(offset: int) -> int:
        i = 0
        while i + 1 < len(starts) and starts[i + 1] <= offset:
            i += 1
        return i

    # Right to left, so earlier offsets stay valid.
    for m in reversed(matches):
        a, b = m.start(), m.end()
        first, last = run_at(a), run_at(b - 1)
        value = values[m.group(1)]
        if first == last:
            r = runs[first]
            s = a - starts[first]
            r.text = r.text[:s] + value + r.text[s + (b - a) :]
        else:
            r0 = runs[first]
            r0.text = r0.text[: a - starts[first]] + value
            for i in range(first + 1, last):
                runs[i].text = ""
            rl = runs[last]
            rl.text = rl.text[b - starts[last] :]
        # Offsets after this match are unchanged (we go right to left); runs
        # before it too. Nothing to recompute.


def _paragraphs(container):
    yield from container.paragraphs
    for table in getattr(container, "tables", []):
        for row in table.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def fill_docx(template: bytes, values: dict[str, str]) -> bytes:
    from docx import Document

    try:
        doc = Document(io.BytesIO(template))
    except Exception as e:  # noqa: BLE001 - a broken upload
        raise RenderError(f"This isn't a Word (.docx) file Word can open: {e}") from e
    parts = [doc]
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            if part is not None:
                parts.append(part)
    for part in parts:
        for p in _paragraphs(part):
            _fill_paragraph(p, values)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def docx_keywords(template: bytes) -> list[str]:
    """Keywords used in an uploaded template (for the site's checklist)."""
    from docx import Document

    doc = Document(io.BytesIO(template))
    found: list[str] = []
    parts = [doc] + [s.header for s in doc.sections] + [s.footer for s in doc.sections]
    for part in parts:
        for p in _paragraphs(part):
            for key in KEY_RE.findall("".join(r.text for r in p.runs)):
                if key not in found:
                    found.append(key)
    return found


# ------------------------------------------------------------------ HTML


def docx_to_html(data: bytes) -> str:
    """An uploaded Word template as editor HTML: headings, lists, tables and images come along."""
    import mammoth

    try:
        result = mammoth.convert_to_html(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 - a broken upload
        raise RenderError(f"Couldn't read this Word file: {e}") from e
    return result.value or "<p></p>"

PAGE_CSS = """
@page { size: A4; margin: 20mm 18mm; }
body { font-family: "Times New Roman", serif; font-size: 12pt; line-height: 1.45; color: #000; }
h1 { font-size: 18pt; } h2 { font-size: 15pt; } h3 { font-size: 13pt; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #555; padding: 4pt 6pt; vertical-align: top; }
img { max-width: 100%; }
"""


def fill_html(template: str, values: dict[str, str]) -> str:
    def sub(m):
        key = m.group(1)
        return html.escape(values[key]) if key in values else m.group(0)

    body = KEY_RE.sub(sub, template)
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{PAGE_CSS}</style></head><body>{body}</body></html>'
    )


def html_keywords(template: str) -> list[str]:
    found: list[str] = []
    for key in KEY_RE.findall(template):
        if key not in found:
            found.append(key)
    return found


# ------------------------------------------------------------------ LibreOffice


def _soffice(src: Path, target: str, *, infilter: str | None = None) -> bytes:
    """Convert `src` with LibreOffice; `target` is e.g. 'pdf' or 'docx:MS Word 2007 XML'."""
    out_dir = src.parent / "out"
    out_dir.mkdir()
    # Own profile per call so conversions can run side by side.
    profile = (src.parent / "profile").as_uri()
    cmd = [settings.SOFFICE_BIN, f"-env:UserInstallation={profile}", "--headless", "--norestore"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", target, "--outdir", str(out_dir), str(src)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=settings.SOFFICE_TIMEOUT)
    except FileNotFoundError as e:
        raise RenderError("LibreOffice isn't installed on the server, so PDF can't be made.") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError("Making the document took too long.") from e
    except subprocess.CalledProcessError as e:
        raise RenderError(f"LibreOffice couldn't convert the document: {e.stderr.decode(errors='ignore')[:200]}") from e
    produced = list(out_dir.iterdir())
    if not produced:
        raise RenderError("LibreOffice produced no file.")
    return produced[0].read_bytes()


def docx_to_pdf(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.docx"
        src.write_bytes(data)
        return _soffice(src, "pdf")


def html_to(fmt: str, page: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(page, encoding="utf-8")
        # Open as a Writer document (not Writer/Web), which can save .docx.
        target = "pdf:writer_pdf_Export" if fmt == "pdf" else "docx:MS Word 2007 XML"
        return _soffice(src, target, infilter="HTML (StarWriter)")


def render(template, fmt: str, values: dict[str, str]) -> bytes:
    """The finished document for a DocTemplate, as .docx or .pdf bytes."""
    if template.kind == "docx":
        if not template.docx:
            raise RenderError("Upload the Word file of this template first.")
        filled = fill_docx(bytes(template.docx), values)
        return filled if fmt == "docx" else docx_to_pdf(filled)
    if not (template.html or "").strip():
        raise RenderError("This template is empty.")
    return html_to(fmt, fill_html(template.html, values))
