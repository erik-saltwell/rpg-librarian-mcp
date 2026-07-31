from __future__ import annotations

from enum import StrEnum, auto


class ProcessingStage(StrEnum):
    populate_file_data = auto()
    extract_metadata = auto()
    read_pdfs = auto()
    link_product = auto()
