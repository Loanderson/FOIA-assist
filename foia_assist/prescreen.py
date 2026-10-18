"""Exemption pre-screen. Flags CANDIDATE FOIA exemptions with the exact text
spans and a reason, so a FOIA officer can review faster. It never decides:
exemption determinations are legal judgments made by agency staff.

Deterministic on purpose: a pattern a reviewer can read beats a model's
opinion when the question is "why was this flagged?"
"""

import re
from dataclasses import dataclass

from .corpus import Document

GOV_EMAIL = re.compile(r"@[a-z0-9.\-]+\.(?:gov|mil)\b", re.I)


@dataclass(frozen=True)
class Flag:
    exemption: str      # e.g. "b(6)"
    reason: str
    text: str = ""      # matched span ("" for document-level flags)
    start: int = -1
    end: int = -1


SPAN_PATTERNS = [
    ("b(6)", "Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("b(6)", "Personal phone number", re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}")),
    ("b(6)", "Date of birth", re.compile(r"(?i)date of birth[:\s]+\d{1,2}/\d{1,2}/\d{4}")),
    ("b(6)", "Home address", re.compile(
        r"\b\d{1,5} [A-Z][a-z]+ (?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct)\b"
        r"(?:, [A-Z][a-z]+(?: [A-Z][a-z]+)*, [A-Z]{2} \d{5})?")),
    ("b(4)", "Confidential commercial or pricing information", re.compile(
        r"(?i)(?:proprietary|confidential commercial)[^.]*")),
    ("b(7)(A)", "Open law-enforcement matter", re.compile(r"(?i)(?:criminal investigation|OIG case [\w\-]+)")),
    ("b(7)(E)", "Investigative techniques or detection methods", re.compile(
        r"(?i)(?:investigative techniques|detection rules|network indicators)[^.]*")),
]
EMAIL = re.compile(r"\b[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+\b")


def screen(doc: Document) -> list[Flag]:
    flags: list[Flag] = []
    text = doc.body
    for ex, reason, rx in SPAN_PATTERNS:
        for m in rx.finditer(text):
            flags.append(Flag(ex, reason, m.group(0), m.start(), m.end()))
    for m in EMAIL.finditer(text):
        if not GOV_EMAIL.search(m.group(0)):
            flags.append(Flag("b(6)", "Personal email address", m.group(0), m.start(), m.end()))
    if doc.status == "draft" or re.search(r"(?i)predecisional|deliberative", text):
        flags.append(Flag("b(5)", "Draft or predecisional/deliberative material: review whole document"))
    if doc.marking == "CUI":
        flags.append(Flag("review", f"Document is marked {doc.marking}; requires CUI/originator review before release"))
    return sorted(flags, key=lambda f: (f.start, f.exemption))


def redact(doc: Document, flags: list[Flag]) -> str:
    """Preview with span-level flags replaced by their exemption code."""
    spans = sorted((f for f in flags if f.start >= 0), key=lambda f: f.start)
    out, pos = [], 0
    for f in spans:
        if f.start < pos:
            continue  # overlapping match already covered
        out += [doc.body[pos:f.start], f"[{f.exemption}]"]
        pos = f.end
    out.append(doc.body[pos:])
    return "".join(out)
