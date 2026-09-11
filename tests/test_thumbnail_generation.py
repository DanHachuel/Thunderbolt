import base64
import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from hermes_ui import thumbnail_generation
from PIL import Image



def test_thumbnail_requires_a_dedicated_gemini_image_key():
    try:
        thumbnail_generation.generate_thumbnail_image({}, "A thumbnail prompt")
    except thumbnail_generation.ThumbnailGenerationError as exc:
        assert "Configuração API > API Keys > Serviços e modelos" in str(exc)
    else:
        raise AssertionError("A geração deveria exigir a API key Nano Banana")



def test_thumbnail_uses_interactions_api_and_saves_inline_image():
    image_bytes = b"fake-jpeg-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = Mock(status_code=200)
    response.json.return_value = {
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "image", "data": encoded, "mime_type": "image/jpeg"}]}],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        original_storage = thumbnail_generation.STORAGE
        thumbnail_generation.STORAGE = Path(temp_dir)
        try:
            with patch.object(thumbnail_generation.requests, "post", return_value=response) as post:
                output = thumbnail_generation.generate_thumbnail_image(
                    {
                        "gemini_image_api_key": "secret-key",
                        "gemini_image_model": "gemini-3.1-flash-image",
                        "gemini_image_aspect_ratio": "16:9",
                        "gemini_image_size": "1K",
                    },
                    "A cinematic thumbnail prompt",
                    topic="A topic",
                    variant_index=1,
                )
            assert output.read_bytes() == image_bytes
            assert output.suffix == ".jpg"
            assert output.parent == Path(temp_dir) / "thumbnails"
            request = post.call_args.kwargs
            assert request["headers"]["x-goog-api-key"] == "secret-key"
            assert request["json"]["model"] == "gemini-3.1-flash-image"
            assert request["json"]["response_format"] == {
                "type": "image",
                "mime_type": "image/jpeg",
                "aspect_ratio": "16:9",
                "image_size": "1K",
            }
            assert "secret-key" not in json.dumps(request["json"])
        finally:
            thumbnail_generation.STORAGE = original_storage


def test_square_provider_response_is_normalized_to_youtube_thumbnail_size():
    source = BytesIO()
    Image.new("RGB", (1024, 1024), (20, 40, 80)).save(source, format="PNG")
    normalized = thumbnail_generation.normalize_thumbnail_bytes(source.getvalue())
    with Image.open(BytesIO(normalized)) as image:
        assert image.size == (1792, 1024)
        assert image.format == "JPEG"


def test_vertical_prompt_infers_portrait_ratio_and_normalizes_to_vertical_size():
    assert thumbnail_generation.infer_thumbnail_aspect_ratio(
        "Cinematic photorealistic vertical 9:16 frame, 1080x1920"
    ) == "9:16"
    source = BytesIO()
    Image.new("RGB", (1024, 1024), (20, 40, 80)).save(source, format="PNG")
    normalized = thumbnail_generation.normalize_thumbnail_bytes(source.getvalue(), "9:16")
    with Image.open(BytesIO(normalized)) as image:
        assert image.size == (1024, 1792)


def test_blueprint_orientation_overrides_conflicting_prompt_orientation():
    assert thumbnail_generation.infer_thumbnail_aspect_ratio(
        "vertical 9:16 composition",
        {"content": "Landscape 16:9 YouTube thumbnail"},
    ) == "16:9"


def test_vertical_prompt_is_sent_to_nano_as_portrait_ratio():
    image_bytes = b"fake-jpeg-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = Mock(status_code=200)
    response.json.return_value = {
        "status": "completed",
        "steps": [{"content": [{"type": "image", "data": encoded}]}],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        original_storage = thumbnail_generation.STORAGE
        thumbnail_generation.STORAGE = Path(temp_dir)
        try:
            with patch.object(thumbnail_generation.requests, "post", return_value=response) as post:
                thumbnail_generation.generate_thumbnail_image(
                    {"gemini_image_api_key": "secret-key"},
                    "Cinematic photorealistic vertical 9:16 frame, 1080x1920",
                )
            assert post.call_args.kwargs["json"]["response_format"]["aspect_ratio"] == "9:16"
        finally:
            thumbnail_generation.STORAGE = original_storage
