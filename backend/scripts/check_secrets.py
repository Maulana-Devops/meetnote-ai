"""Pemeriksa secret lokal tanpa dependency tambahan.

Script ini dipakai CI dan bisa dijalankan manual:

    python backend/scripts/check_secrets.py

Ia hanya membaca file teks dan mencari pola kredensial yang jelas. Placeholder
seperti ``STT_API_KEY=`` atau contoh dokumentasi tidak dianggap temuan.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    "storage",
    "test_storage",
    "backups",
    "models",
}

SKIP_SUFFIXES = {
    ".db",
    ".db-journal",
    ".db-wal",
    ".db-shm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".m4a",
    ".mp3",
    ".webm",
    ".wav",
    ".pyc",
}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("openai token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("huggingface token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("slack token", re.compile(r"\bxox[bpors]-[A-Za-z0-9-]{20,}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("json web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "bearer credential",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{24,}"),
    ),
    (
        "database uri credential",
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
            r"[^\s:/@]+:[^\s@]+@"
        ),
    ),
    (
        "assigned credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*"
            r"[\"']?(?!\s*$|<|\[MOCK\]|your|changeme|placeholder|example)"
            r"[A-Za-z0-9_\-]{16,}"
        ),
    ),
)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def scan() -> list[str]:
    findings: list[str] = []
    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    relative = path.relative_to(ROOT).as_posix()
                    findings.append(f"{relative}:{line_number}: {label}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Potensi kredensial ditemukan:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1
    print("Secret scan bersih.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
