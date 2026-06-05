import pytest

from engine.ocr import VolcengineOCR


class FailingClient:
    async def post(self, *args, **kwargs):
        raise TimeoutError("network timeout")


class FailingClientFactory:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return FailingClient()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_ocr_raises_after_retries(monkeypatch, tmp_path):
    import engine.ocr as ocr_module

    image = tmp_path / "image.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setattr(ocr_module.httpx, "AsyncClient", FailingClientFactory)

    client = VolcengineOCR("https://ocr.example.test", "secret", "vision-model")

    with pytest.raises(RuntimeError, match="OCR failed after 3 retries"):
        await client.extract([str(image)])
