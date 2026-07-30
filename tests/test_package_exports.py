from enum import StrEnum

from rpg_librarian_mcp.metadata import MetadataExtractor
from rpg_librarian_mcp.model import MediaType


def test_model_package_exports_media_type_enum():
    assert issubclass(MediaType, StrEnum)
    assert MediaType.pdf == "pdf"


def test_metadata_package_exports_metadata_extractor_class():
    assert MetadataExtractor.__name__ == "MetadataExtractor"
    assert hasattr(MetadataExtractor, "extract_value")
    assert hasattr(MetadataExtractor, "extract_custom_metadata")
