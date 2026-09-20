# rpg-librarian-tools

Reusable, atomic operations used by RPG Librarian applications.

The package has no MCP, database, catalog, or workflow dependencies. Callers own
orchestration and persistence; these functions and service clients accept explicit
inputs and return plain values.

Primary atomic operations include `extract_pdf_text`,
`find_isbn_or_issn_barcode`, `detect_mime_type`, `generate_sha256`,
`search_dtrpg_products`, `search_dtrpg_library`, `search_rpggeek`, and
`get_rpggeek_product`.
