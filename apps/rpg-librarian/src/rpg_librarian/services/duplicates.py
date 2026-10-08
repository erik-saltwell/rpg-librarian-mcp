"""Stable winner ordering shared by scan and quick duplicate cleanup."""


def duplicate_rank(
    pack_id: int | None,
    root_id: int,
    file_id: int,
    library_root_id: int | None,
    *,
    orphan_duplicate: bool = False,
) -> tuple[int, int, int, int]:
    """Unlinked duplicates lose; otherwise packs, library, then earliest row win.

    Quick cleanup cannot catalog its inbox survivor. Its extra copies enter trash
    without an original id, and must not displace that survivor when scan finds it.
    """
    return (
        1 if orphan_duplicate else 0,
        0 if pack_id is not None else 1,
        0 if root_id == library_root_id else 1,
        file_id,
    )
