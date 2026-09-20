from PIL import Image

from rpg_librarian_mcp.metadata.extractors.image_extractor import ImageExtractor
from rpg_librarian_mcp.model import ImageMetadata


def test_extract_custom_metadata_returns_image_dimensions_alpha_and_pixel_count(
    tmp_path,
):
    image_path = tmp_path / "map.png"
    Image.new("RGBA", (7, 5), (1, 2, 3, 4)).save(image_path)

    metadata = ImageExtractor(image_path).extract_custom_metadata()

    assert isinstance(metadata, ImageMetadata)
    assert metadata.width == 7
    assert metadata.height == 5
    assert metadata.has_alpha is True
    assert metadata.pixel_count == 35
