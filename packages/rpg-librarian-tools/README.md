# rpg-librarian-tools

Reusable, atomic operations used by RPG Librarian applications.

The package contains no MCP, database, catalog, directory traversal, or process
management. Callers choose files and pages, persist results, and decide whether to
run native PDF work in an application-owned worker process.

Public modules:

- `rpg_librarian_tools.files.inspect_file(path)` returns the media type, MIME
  type, SHA-256, and byte size for one file.
- `rpg_librarian_tools.identifiers.find_publication_identifiers(text)` returns
  every checksum-valid ISBN or ISSN found in text, in source order.
- `rpg_librarian_tools.pdf.extract_text(path, pages=None)` extracts embedded
  text where available and OCRs the other selected pages.
- `rpg_librarian_tools.pdf.scan_identifiers(path, pages=None)` returns every
  valid ISBN or ISSN barcode found on the selected pages.
- `rpg_librarian_tools.pdf.assess_images(path, pages=None)` classifies selected
  PDF pages as image-only, not image-only, or indeterminate, with a reason.
- `rpg_librarian_tools.dtrpg.search_products(...)` and `search_library(...)`
  perform one authenticated DriveThruRPG request sequence.
- `rpg_librarian_tools.rpggeek.search(...)` and `get_product(...)` perform one
  RPGGeek request sequence.
- `rpg_librarian_tools.google.search(query, api_key, num=5)` performs one Google
  search through Serper.dev and returns the top organic hits (position, title, URL,
  snippet).

Network operations take explicit credentials and an optional immutable
`RequestPolicy`. PDF operations use `pages=None` for all pages; otherwise callers
provide zero-based page indexes. Result objects are immutable.
