"""
File Type Router
================

Centralized file type classification and routing for the RAG pipeline.
Determines the appropriate processing method for each document type.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

from deeptutor.logging import get_logger

logger = get_logger("FileTypeRouter")


class DocumentType(Enum):
    """Document type classification."""

    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"
    DOCX = "docx"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class FileClassification:
    """Result of file classification."""

    parser_files: List[str]
    text_files: List[str]
    unsupported: List[str]


class FileTypeRouter:
    """File type router for the RAG pipeline.

    Classifies files before processing to route them to appropriate handlers:
    - PDF files -> PDF parsing
    - Text files -> Direct read (fast, simple)
    - Unsupported -> Skip with warning
    """

    PARSER_EXTENSIONS = {".pdf"}

    TEXT_EXTENSIONS = {
        ".txt",
        ".text",
        ".log",
        ".md",
        ".markdown",
        ".rst",
        ".asciidoc",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        ".tex",
        ".latex",
        ".bib",
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".r",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".html",
        ".htm",
        ".xml",
        ".svg",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".properties",
    }

    DOCX_EXTENSIONS = {".docx", ".doc"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
    TEXT_CONTROL_BYTES = {8, 9, 10, 12, 13}

    @staticmethod
    def extension_for_path(file_path: str) -> str:
        """Return a supported extension, including dotfiles such as .env."""
        name = Path(file_path or "").name.lower()
        if name.startswith(".") and name.count(".") == 1:
            return name
        return Path(name).suffix.lower()

    @classmethod
    def get_document_type(cls, file_path: str) -> DocumentType:
        """Classify a single file by its type."""
        ext = cls.extension_for_path(file_path)
        path_obj = Path(file_path)

        if ext in cls.PARSER_EXTENSIONS:
            return DocumentType.PDF
        elif ext in cls.TEXT_EXTENSIONS:
            if path_obj.is_file() and not cls._is_text_file(file_path):
                return DocumentType.UNKNOWN
            return DocumentType.TEXT
        elif ext in cls.DOCX_EXTENSIONS:
            return DocumentType.DOCX
        elif ext in cls.IMAGE_EXTENSIONS:
            return DocumentType.IMAGE
        else:
            if cls._is_text_file(file_path):
                return DocumentType.TEXT
            return DocumentType.UNKNOWN

    @classmethod
    def _is_text_file(cls, file_path: str, sample_size: int = 8192) -> bool:
        """Detect if a file is text-based by examining its content."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(sample_size)

            if cls.looks_binary(chunk):
                return False

            cls.decode_bytes(chunk)
            return True
        except (UnicodeDecodeError, IOError, OSError):
            return False

    @classmethod
    def classify_files(cls, file_paths: List[str]) -> FileClassification:
        """Classify a list of files by processing method."""
        parser_files = []
        text_files = []
        unsupported = []

        for path in file_paths:
            doc_type = cls.get_document_type(path)

            if doc_type == DocumentType.PDF:
                parser_files.append(path)
            elif doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN):
                text_files.append(path)
            else:
                unsupported.append(path)

        logger.debug(
            f"Classified {len(file_paths)} files: "
            f"{len(parser_files)} parser, {len(text_files)} text, {len(unsupported)} unsupported"
        )

        return FileClassification(
            parser_files=parser_files,
            text_files=text_files,
            unsupported=unsupported,
        )

    TEXT_DECODING_CANDIDATES = (
        "utf-8",
        "utf-8-sig",
        "gbk",
        "gb2312",
        "gb18030",
        "latin-1",
        "cp1252",
    )

    @classmethod
    def looks_binary(cls, data: bytes, sample_size: int = 8192) -> bool:
        """Cheap binary-content sniff for text-like upload guards."""
        sample = data[:sample_size]
        if not sample:
            return False
        if b"\x00" in sample:
            return True
        controls = sum(
            1
            for byte in sample
            if (byte < 32 and byte not in cls.TEXT_CONTROL_BYTES) or byte == 127
        )
        return controls / len(sample) > 0.05

    @classmethod
    def decode_bytes(cls, data: bytes) -> str:
        """Decode raw bytes using the same fallback chain as read_text_file.

        Used by the chat-attachment extractor so path-based and bytes-based
        callers share one source of truth for supported encodings.
        """
        if cls.looks_binary(data):
            raise UnicodeDecodeError(
                "utf-8",
                data,
                0,
                min(len(data), 1),
                "binary-like content",
            )
        for encoding in cls.TEXT_DECODING_CANDIDATES:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @classmethod
    async def read_text_file(cls, file_path: str) -> str:
        """Read a text file with automatic encoding detection."""
        with open(file_path, "rb") as f:
            return cls.decode_bytes(f.read())

    @classmethod
    def needs_parser(cls, file_path: str) -> bool:
        """Quick check if a single file needs parser processing."""
        doc_type = cls.get_document_type(file_path)
        return doc_type in (DocumentType.PDF, DocumentType.DOCX, DocumentType.IMAGE)

    @classmethod
    def is_text_readable(cls, file_path: str) -> bool:
        """Check if a file can be read directly as text."""
        doc_type = cls.get_document_type(file_path)
        return doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN)

    @classmethod
    def get_supported_extensions(cls) -> set[str]:
        """Get the set of all supported file extensions."""
        return cls.PARSER_EXTENSIONS | cls.TEXT_EXTENSIONS

    @classmethod
    def get_glob_patterns(cls) -> list[str]:
        """Get glob patterns for file searching."""
        return [f"*{ext}" for ext in sorted(cls.get_supported_extensions())]
