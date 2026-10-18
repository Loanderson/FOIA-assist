"""Load agency records: markdown files with a small front-matter header."""

from dataclasses import dataclass
from pathlib import Path

from . import policy

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus"


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    date: str
    office: str
    type: str
    marking: str
    status: str
    body: str

    @property
    def year(self) -> int:
        return int(self.date[:4])


def parse(text: str) -> Document:
    if not text.startswith("---\n"):
        raise ValueError("missing front matter")
    header, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    policy.rank(meta["marking"])  # reject unknown markings at load time
    return Document(body=body.strip(), **{k: meta[k] for k in
                    ("id", "title", "date", "office", "type", "marking", "status")})


def load(directory: str | Path = DEFAULT_CORPUS) -> list[Document]:
    docs = [parse(p.read_text(encoding="utf-8")) for p in sorted(Path(directory).glob("*.md"))]
    if not docs:
        raise FileNotFoundError(f"no documents in {directory}")
    return docs
