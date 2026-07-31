from __future__ import annotations

from enum import StrEnum, auto


class ProcessingStage(StrEnum):
    populate_file_data = auto()
    extract_metadata = auto()
    read_pdfs = auto()
    link_product = auto()
    classify_content_role = auto()
    remove = auto()
    flag_for_review = auto()
    resolve_review_flag = auto()
