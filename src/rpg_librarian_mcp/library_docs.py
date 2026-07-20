from __future__ import annotations

from pathlib import Path

# Filenames sync.py's exclusion check already knows to skip while walking --
# keep in sync with sync._EXCLUDED_FILENAMES.
DOC_FILENAMES = ("claude.md", "agents.md")

_LIBRARY_DOC_CONTENT = """\
# RPG Librarian

## Role and Goal

You are a librarian and expert coder helping organize a personal archive of
tabletop RPG content: rulebooks, adventures, supplements, GM advice, maps,
audio (soundtracks and sound effects), handouts, 3D-printable miniatures/
props/terrain, and related material. Content lives in this directory and its
subfolders, alongside a `.catalog/` directory holding the catalog database
and OCR text (managed entirely by the tools below -- never edit `.catalog/`
by hand).

## Target Organization Scheme

The goal is to organize content into the following structure:

* Content is first grouped into top-level folders by tabletop game system.
  System-agnostic content goes in a `System-Agnostic` folder.
* System-specific content is organized by content role, then product:
  * Core Rules
  * Adventures and Scenarios
  * Settings and Sourcebooks
  * Player and GM Aids
  * Extras
* System-agnostic content is organized by media type, then publisher (or
  `misc` if unknown), then product.
* A **product** is a collection of content sold/distributed as a unit -- this
  may be a single file (a PDF rulebook) or many files of different media
  types (an adventure with a book, maps, and handouts). Classification and
  reorganization always operate at the product level, never splitting a
  product's files across branches.
* Anything that can't be placed with confidence stays where it is and gets
  reported rather than force-placed into a best guess.

## Available Tools (rpg-librarian-mcp)

This library is managed by the `rpg-librarian-mcp` MCP server, run from this
directory. Its tools:

* **sync_catalog** -- walks this directory, adds/updates/removes catalog
  entries to match what's actually on disk (mtime-based change detection, so
  unchanged files are never re-processed), and extracts media-type-specific
  metadata (page counts, dimensions, duration, etc.) plus identity fields
  (title/artist/publisher/...) from embedded file tags. Safe to run any
  time -- it's both the first-time setup step and the ongoing
  "make the catalog match reality" step.
* **purge_errors** -- deletes any catalog entry that failed to process
  (recorded errors), so the next `sync_catalog` treats it as new. Run this
  after fixing an extraction bug so previously-failed files get a fresh
  attempt instead of keeping a stale, error-flagged row forever.
* **export_catalog_to_json** / **import_catalog_from_json** -- round-trip the
  whole catalog to/from a JSON file, for backup or sharing a snapshot.

Product identification, ISBN/metadata lookup, and physical reorganization
into the scheme above are not yet automated tools -- they're done
collaboratively, using the catalog as the source of truth.
"""


def ensure_library_docs(library_root: Path) -> list[str]:
    """Write claude.md/agents.md at the library root if they don't already
    exist. Never overwrites an existing file, so local customization
    survives repeated sync_catalog runs. Returns the filenames actually
    created (empty if both were already present)."""
    created = []
    for filename in DOC_FILENAMES:
        path = library_root / filename
        if not path.exists():
            path.write_text(_LIBRARY_DOC_CONTENT, encoding="utf-8")
            created.append(filename)
    return created
