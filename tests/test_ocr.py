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


@pytest.mark.asyncio
async def test_extract_pdf_renders_pages_and_uses_faithful_prompt(monkeypatch, tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(path)
    document.close()
    captured = {}
    client = VolcengineOCR("https://ocr.example.test", "secret", "vision-model")

    async def fake_extract(image_paths, prompt=None):
        captured["image_paths"] = image_paths
        captured["prompt"] = prompt
        return "第一页文字\n第二页文字"

    monkeypatch.setattr(client, "extract", fake_extract)

    text = await client.extract_pdf(str(path))

    assert text == "第一页文字\n第二页文字"
    assert len(captured["image_paths"]) == 2
    assert all(image_path.endswith(".png") for image_path in captured["image_paths"])
    assert "不要总结" in captured["prompt"]
    assert "不要改写" in captured["prompt"]
    assert "不要补全" in captured["prompt"]


@pytest.mark.asyncio
async def test_extract_pdf_respects_max_pages(monkeypatch, tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "scan.pdf"
    document = fitz.open()
    for _ in range(3):
        document.new_page()
    document.save(path)
    document.close()
    captured = {}
    client = VolcengineOCR("https://ocr.example.test", "secret", "vision-model")

    async def fake_extract(image_paths, prompt=None):
        captured["page_count"] = len(image_paths)
        return "两页文字"

    monkeypatch.setattr(client, "extract", fake_extract)

    await client.extract_pdf(str(path), max_pages=2)

    assert captured["page_count"] == 2
