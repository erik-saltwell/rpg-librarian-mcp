"""Metadata ownership assumptions, followed by local freshness checks before
skipping."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path, PurePosixPath

QUERY = """
SELECT f.id,f.root_id,f.relative_path,f.size_bytes,f.sha256,f.mtime,r.path root_path,
COALESCE(p1.product_line_id,p2.product_line_id) line_id,
COALESCE(p1.name,p2.name) product_title,COALESCE(p1.year,p2.year) product_year
FROM file f JOIN root r ON r.id=f.root_id
LEFT JOIN entry e1 ON e1.file_id=f.id LEFT JOIN product p1 ON p1.id=e1.product_id
LEFT JOIN entry e2 ON e2.pack_id=f.pack_id LEFT JOIN product p2 ON p2.id=e2.product_id
WHERE f.missing_since IS NULL"""
GENERIC = {
    "core rulebook",
    "rulebook",
    "rules",
    "character sheet",
    "character sheets",
    "players guide",
    "player guide",
    "map",
    "readme",
    "license",
    "index",
    "cover",
    "tokens",
    "preview",
    "quickstart",
    "printable map",
}


def norm(value: str) -> str:
    return re.sub(
        r"[\s_-]+", " ", unicodedata.normalize("NFKC", value).casefold()
    ).strip()


def line_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    value = re.sub(r"[!\u2018\u2019']", "", value)
    for n, ordinal in [
        ("1", "1st"),
        ("2", "2nd"),
        ("3", "3rd"),
        ("4", "4th"),
        ("5", "5th"),
        ("6", "6th"),
        ("7", "7th"),
    ]:
        value = re.sub(r"\b" + ordinal + r"\s+(?:edition|ed)\b", n + "e", value)
    value = re.sub(r"\bfirst edition\b", "1e", value)
    value = re.sub(r"\bsecond edition\b", "2e", value)
    return re.sub(r"\s+", " ", re.sub(r"[^\w.]+", " ", value)).strip()


def distinctive(filename: str) -> bool:
    stem = PurePosixPath(filename).stem
    return (
        norm(stem) not in GENERIC
        and len(re.sub(r"\W", "", stem)) >= 6
        and not re.fullmatch(r"[\d\s._-]+", stem)
    )


def fingerprint(value: str, line: str) -> str:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    words = [
        x
        for x in re.sub(
            r"[^\w.]+", " ", unicodedata.normalize("NFKC", value).casefold()
        ).split()
        if x not in {"and", "the", "a", "an"}
    ]
    prefix = [
        x
        for x in re.sub(r"[^\w.]+", " ", line.casefold()).split()
        if x not in {"and", "the", "a", "an"}
    ]
    if prefix and words[: len(prefix)] == prefix:
        words = words[len(prefix) :]
    return "".join(words)


def fresh(row: dict) -> bool:
    try:
        stat = (Path(row["root_path"]) / row["relative_path"]).stat()
        return stat.st_size == row["size_bytes"] and int(stat.st_mtime) == row["mtime"]
    except OSError:
        return False


class Matcher:
    def __init__(
        self, catalog: Path, remote: list[dict], catalog_seed: dict | None = None
    ):
        self.local = sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True)
        self.local.row_factory = sqlite3.Row
        self.lines = {
            r[0]: r[1] for r in self.local.execute("SELECT id,name FROM product_line")
        }
        self.aliases = defaultdict(set)
        for identity, name in self.lines.items():
            self.aliases[identity].add(norm(name))
        for identity, alias in self.local.execute(
            "SELECT product_line_id,alias FROM product_line_alias"
        ):
            self.aliases[identity].add(norm(alias))
        self.remote_lines = {
            norm(x["path"].split("/")[0]) for x in remote if "/" in x["path"]
        }
        names = {norm(x["name"]) for x in remote}
        sizes = {
            x["size"]
            for x in remote
            if x["name"].casefold().endswith(".pdf") and distinctive(x["name"])
        }
        self.by_name, self.by_size = defaultdict(list), defaultdict(list)
        for record in self.local.execute(QUERY):
            row = dict(record)
            parts = PurePosixPath(row["relative_path"]).parts
            if not parts:
                continue
            row["filename"] = parts[-1]
            key = norm(parts[-1])
            if key not in names:
                continue
            explicit = set(self.aliases.get(row["line_id"], set()))
            row["lines"] = explicit or {
                norm(p) for p in parts[:-1] if norm(p) in self.remote_lines
            }
            if key in names:
                self.by_name[key].append(row)

        pair_names = defaultdict(set)
        for item in remote:
            line = item["path"].split("/")[0] if "/" in item["path"] else ""
            if not distinctive(item["name"]):
                continue
            for match in self.by_name[norm(item["name"])]:
                if match["line_id"] and match["size_bytes"] == item["size"]:
                    pair_names[(line, match["line_id"])].add(norm(item["name"]))
        mapped = defaultdict(set)
        for (line, identity), shared in pair_names.items():
            key, candidates = (
                line_key(line),
                {line_key(a) for a in self.aliases[identity]},
            )
            if key in candidates or (
                len(shared) >= 3 and any(k.startswith(key + " ") for k in candidates)
            ):
                mapped[identity].add(norm(line))
        for matches in self.by_name.values():
            for row in matches:
                row["lines"] |= mapped[row["line_id"]]
        # Stream a second pass for renamed PDFs; do not retain other media or
        # unrelated product lines merely because a common byte size overlaps.
        for record in self.local.execute(QUERY):
            if record["size_bytes"] not in sizes:
                continue
            row = dict(record)
            parts = PurePosixPath(row["relative_path"]).parts
            if not parts or not parts[-1].casefold().endswith(".pdf"):
                continue
            row["filename"] = parts[-1]
            row["lines"] = (
                set(self.aliases.get(row["line_id"], set())) | mapped[row["line_id"]]
            )
            if not row["lines"]:
                row["lines"] = {
                    norm(p) for p in parts[:-1] if norm(p) in self.remote_lines
                }
            if row["lines"] & self.remote_lines:
                self.by_size[row["size_bytes"]].append(row)
        self.titles = defaultdict(list)
        for item in (catalog_seed or {}).get("items", []):
            if all(isinstance(item.get(k), str) for k in ("system", "file", "title")):
                self.titles[(norm(item["system"]), norm(item["file"]))].append(
                    item["title"]
                )

    def match(self, item: dict) -> tuple[str | None, dict | None]:
        line = norm(item["path"].split("/")[0]) if "/" in item["path"] else ""
        matches = [
            m
            for m in self.by_name[norm(item["name"])]
            if m["size_bytes"] == item["size"]
        ]
        same = [m for m in matches if line in m["lines"]]
        method = (
            "line_filename_size"
            if same
            else "filename_size"
            if matches and distinctive(item["name"])
            else None
        )
        if method:
            for row in same or matches:
                if fresh(row):
                    return method, row
        if item["name"].casefold().endswith(".pdf") and distinctive(item["name"]):
            keys = {fingerprint(PurePosixPath(item["name"]).stem, line)}
            keys.update(
                fingerprint(t, line) for t in self.titles[(line, norm(item["name"]))]
            )
            keys = {k for k in keys if len(k) >= 10}
            candidates = []
            for row in self.by_size[item["size"]]:
                if line not in row["lines"] or not row["filename"].casefold().endswith(
                    ".pdf"
                ):
                    continue
                context = self.lines.get(row["line_id"], line)
                local_keys = {fingerprint(PurePosixPath(row["filename"]).stem, context)}
                if row["product_title"]:
                    local_keys.add(fingerprint(row["product_title"], context))
                    if row["product_year"] and re.fullmatch(
                        r"\d{4}", row["product_year"]
                    ):
                        local_keys.add(
                            fingerprint(
                                row["product_title"] + " " + row["product_year"],
                                context,
                            )
                        )
                if keys & local_keys:
                    candidates.append(row)
            if (
                candidates
                and all(m["sha256"] for m in candidates)
                and len({m["sha256"] for m in candidates}) == 1
            ):
                for row in candidates:
                    if fresh(row):
                        return "renamed_line_title_size", row
        return None, None

    def exact(self, digest: str) -> dict | None:
        for record in self.local.execute(QUERY + " AND f.sha256=?", (digest,)):
            row = dict(record)
            if fresh(row):
                return row
        return None

    def close(self) -> None:
        self.local.close()
