import pytest

import engine.ocr as ocr_module
from engine.ocr import OCRProviderChain, PaddleOCRProvider, _paddle_result_to_text


def _usable_ocr_text() -> str:
    line = "OCR 转写正文包含 2026 年市场规模、23.7% 渗透率、供应链能力和企业战略变化。"
    return "\n".join([line] * 12)


def test_paddle_result_to_text_reads_paddleocr_3_rec_texts():
    result = [{"rec_texts": ["PKA OCR smoke test", "2026 23.7%"]}]

    assert _paddle_result_to_text(result) == "PKA OCR smoke test\n2026 23.7%"


class FakeProvider:
    def __init__(self, name, result="", available=True, error=None):
        self.name = name
        self.result = result
        self._available = available
        self.error = error
        self.calls = 0

    def available(self):
        return self._available

    async def extract_pdf(self, pdf_path, max_pages=50):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_paddle_provider_unavailable_when_package_missing(monkeypatch):
    real_import_module = ocr_module.importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "paddleocr":
            raise ImportError("paddleocr is not installed")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(ocr_module.importlib, "import_module", fake_import_module)

    provider = PaddleOCRProvider()

    assert provider.available() is False


@pytest.mark.asyncio
async def test_paddle_provider_uses_paddleocr_3_compatible_ocr_call(monkeypatch, tmp_path):
    image_path = tmp_path / "page_001.png"
    image_path.write_bytes(b"image")
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def ocr(self, image, **kwargs):
            captured["ocr_image"] = image
            captured["ocr_kwargs"] = kwargs
            if "cls" in kwargs:
                raise TypeError("predict() got an unexpected keyword argument 'cls'")
            return [[[None, ("PKA OCR smoke test 2026 23.7%", 0.99)]]]

    class FakeModule:
        PaddleOCR = FakePaddleOCR

    monkeypatch.setattr(ocr_module.importlib, "import_module", lambda name: FakeModule())
    monkeypatch.setattr(ocr_module, "_render_pdf_pages", lambda pdf_path, max_pages, dpi: [str(image_path)])
    monkeypatch.setattr(ocr_module, "_cleanup_rendered_pages", lambda image_paths: None)
    provider = PaddleOCRProvider()

    text = await provider.extract_pdf(str(tmp_path / "scan.pdf"), max_pages=1)

    assert text == "PKA OCR smoke test 2026 23.7%"
    assert captured["ocr_image"] == str(image_path)
    assert captured["ocr_kwargs"] == {}
    assert captured["init_kwargs"]["lang"] == "ch"


@pytest.mark.asyncio
async def test_paddle_provider_extracts_image_file_with_paddleocr(monkeypatch, tmp_path):
    image_path = tmp_path / "screen.jpeg"
    image_path.write_bytes(b"image")
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def ocr(self, image, **kwargs):
            captured.setdefault("ocr_images", []).append(image)
            captured["ocr_kwargs"] = kwargs
            return [{"rec_texts": ["截图标题", "按钮文字", "2026 23.7%"]}]

    class FakeModule:
        PaddleOCR = FakePaddleOCR

    monkeypatch.setattr(ocr_module.importlib, "import_module", lambda name: FakeModule())
    provider = PaddleOCRProvider()

    text = await provider.extract([str(image_path)])

    assert text == "截图标题\n按钮文字\n2026 23.7%"
    assert captured["ocr_images"] == [str(image_path)]
    assert captured["ocr_kwargs"] == {}
    assert captured["init_kwargs"]["lang"] == "ch"


@pytest.mark.asyncio
async def test_provider_chain_tries_paddle_before_volcengine(tmp_path):
    paddle = FakeProvider("paddle", result=_usable_ocr_text())
    volcengine = FakeProvider("volcengine", result=_usable_ocr_text())
    chain = OCRProviderChain([paddle, volcengine])

    result = await chain.extract_pdf_until_usable(str(tmp_path / "scan.pdf"), page_count=3, max_pages=3)

    assert result is not None
    assert result.provider == "paddle"
    assert paddle.calls == 1
    assert volcengine.calls == 0
    assert result.quality.status != "needs_ocr"
    assert result.attempts[0].provider == "paddle"
    assert result.attempts[0].status == "accepted"


@pytest.mark.asyncio
async def test_provider_chain_assesses_ocr_text_against_processed_pages(tmp_path):
    text = "\n".join(
        [
            "OCR 转写正文包含 2026 年市场规模、23.7% 渗透率、供应链能力、智能座舱功能升级、"
            "品牌竞争格局、渠道变化和企业战略调整，文本长度足以代表一页有效正文。"
        ]
        * 12
    )
    paddle = FakeProvider("paddle", result=text)
    chain = OCRProviderChain([paddle])

    result = await chain.extract_pdf_until_usable(str(tmp_path / "scan.pdf"), page_count=40, max_pages=10)

    assert result is not None
    assert result.provider == "paddle"
    assert result.quality.status != "needs_ocr"
    assert result.quality.page_count == 10
    assert result.source_page_count == 40
    assert result.pages_processed == 10
    assert result.page_limit_reached is True
    assert result.partial is True


@pytest.mark.asyncio
async def test_provider_chain_falls_back_when_paddle_fails(tmp_path):
    paddle = FakeProvider("paddle", error=RuntimeError("paddle failed"))
    volcengine = FakeProvider("volcengine", result=_usable_ocr_text())
    chain = OCRProviderChain([paddle, volcengine])

    result = await chain.extract_pdf_until_usable(str(tmp_path / "scan.pdf"), page_count=3, max_pages=3)

    assert result is not None
    assert result.provider == "volcengine"
    assert [attempt.status for attempt in result.attempts] == ["failed", "accepted"]
    assert "paddle failed" in result.attempts[0].error


@pytest.mark.asyncio
async def test_provider_chain_falls_back_when_paddle_result_still_needs_ocr(tmp_path):
    paddle = FakeProvider("paddle", result="Page 1\nPage 2\nPage 3")
    volcengine = FakeProvider("volcengine", result=_usable_ocr_text())
    chain = OCRProviderChain([paddle, volcengine])

    result = await chain.extract_pdf_until_usable(str(tmp_path / "scan.pdf"), page_count=3, max_pages=3)

    assert result is not None
    assert result.provider == "volcengine"
    assert [attempt.status for attempt in result.attempts] == ["needs_ocr", "accepted"]


@pytest.mark.asyncio
async def test_provider_chain_returns_none_when_all_providers_unusable(tmp_path):
    paddle = FakeProvider("paddle", available=False)
    volcengine = FakeProvider("volcengine", result="Page 1\nPage 2\nPage 3")
    chain = OCRProviderChain([paddle, volcengine])

    result = await chain.extract_pdf_until_usable(str(tmp_path / "scan.pdf"), page_count=3, max_pages=3)

    assert result is None
    assert paddle.calls == 0
    assert volcengine.calls == 1
