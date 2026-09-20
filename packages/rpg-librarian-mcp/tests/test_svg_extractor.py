from rpg_librarian_mcp.metadata.extractors.svg_extractor import SvgExtractor
from rpg_librarian_mcp.model import ImageMetadata


def test_extract_custom_metadata_returns_svg_dimensions_alpha_and_pixel_count(tmp_path):
    svg_path = tmp_path / "map.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8"></svg>'
    )

    metadata = SvgExtractor(svg_path).extract_custom_metadata()

    assert isinstance(metadata, ImageMetadata)
    assert metadata.width == 12
    assert metadata.height == 8
    assert metadata.has_alpha is True
    assert metadata.pixel_count == 96


def test_extract_custom_metadata_uses_view_box_when_dimensions_are_missing(tmp_path):
    svg_path = tmp_path / "token.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 48"></svg>'
    )

    metadata = SvgExtractor(svg_path).extract_custom_metadata()

    assert metadata.width == 32
    assert metadata.height == 48
    assert metadata.pixel_count == 1536
