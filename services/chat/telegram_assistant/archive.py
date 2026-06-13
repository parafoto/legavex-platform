from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree


@dataclass
class ExtractedDocumentText:
    text: str
    status: str
    extractor: str
    error: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)


def sanitize_filename(name: str) -> str:
    cleaned = Path(name or "telegram_document").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("._")
    return cleaned or "telegram_document"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive_path(
    project_root: Path,
    original_name: str,
    chat_id: str,
    message_id: str,
    ts: datetime,
) -> Path:
    safe_name = sanitize_filename(original_name)
    safe_chat_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(chat_id)).strip("_") or "chat"
    safe_message_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(message_id)).strip("_") or "message"
    folder = project_root / "data" / "archive" / "telegram" / ts.strftime("%Y") / ts.strftime("%m") / ts.strftime("%d")
    prefix = f"{ts.strftime('%H%M%S')}_{safe_chat_id}_{safe_message_id}"
    return folder / f"{prefix}_{safe_name}"


def write_metadata(path: Path, metadata: dict) -> Path:
    metadata_path = path.with_name(f"{path.name}.metadata.json")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata_path


def extract_document_text(path: Path, mime_type: str = "", max_chars: int = 12000) -> ExtractedDocumentText:
    suffix = path.suffix.lower()
    mime = (mime_type or "").lower()
    try:
        if suffix == ".pdf" or mime == "application/pdf":
            return _extract_pdf_text(path, max_chars=max_chars)
        if suffix == ".docx" or mime.endswith("wordprocessingml.document"):
            return _extract_docx_text(path, max_chars=max_chars)
        if suffix in {".txt", ".md", ".csv"} or mime.startswith("text/"):
            return _extract_plain_text(path, max_chars=max_chars)
    except Exception as exc:  # extraction must not block archive/HITL creation
        return ExtractedDocumentText(text="", status="failed", extractor="auto", error=str(exc))
    return ExtractedDocumentText(text="", status="unsupported", extractor="none")


def _extract_pdf_text(path: Path, max_chars: int) -> ExtractedDocumentText:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractedDocumentText(
            text="",
            status="dependency_missing",
            extractor="pypdf",
            error="Install pypdf to extract PDF text.",
        )

    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    text = _normalize_text("\n".join(chunks))[:max_chars]
    return ExtractedDocumentText(text=text, status="ok" if text else "empty", extractor="pypdf")


def _extract_docx_text(path: Path, max_chars: int) -> ExtractedDocumentText:
    with zipfile.ZipFile(path) as archive:
        xml_payload = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_payload)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        if parts:
            paragraphs.append("".join(parts))
        if sum(len(item) for item in paragraphs) >= max_chars:
            break
    text = _normalize_text("\n".join(paragraphs))[:max_chars]
    return ExtractedDocumentText(text=text, status="ok" if text else "empty", extractor="docx-xml")


def _extract_plain_text(path: Path, max_chars: int) -> ExtractedDocumentText:
    text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    text = _normalize_text(text)
    return ExtractedDocumentText(text=text, status="ok" if text else "empty", extractor="plain-text")


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x00", "").splitlines()]
    return "\n".join(line for line in lines if line).strip()
