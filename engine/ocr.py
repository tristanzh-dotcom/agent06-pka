import base64
import importlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import httpx

from engine.quality import assess_pdf_quality, clean_pdf_text
from engine.models import ParseQuality


PDF_OCR_PROMPT = (
    "请逐页逐行转写图片中的可见文字。只输出原文文字，不要总结，不要解释，不要改写，"
    "不要翻译，不要补全看不清的内容。无法识别的字符用 [unclear] 标记。"
    "保留数字、小数点、百分号、单位、公司名和标题。"
)


class OCRProvider(Protocol):
    name: str

    def available(self) -> bool:
        ...

    async def extract_pdf(self, pdf_path: str, max_pages: int = 50) -> str:
        ...


@dataclass(frozen=True)
class OCRAttempt:
    provider: str
    status: str
    error: str = ""
    quality: Optional[ParseQuality] = None


@dataclass(frozen=True)
class OCRChainResult:
    text: str
    quality: ParseQuality
    provider: str
    attempts: List[OCRAttempt]
    source_page_count: int = 0
    pages_processed: int = 0
    page_limit_reached: bool = False
    partial: bool = False


class OCRProviderChain:
    def __init__(self, providers: List[OCRProvider]):
        self.providers = providers

    def available(self) -> bool:
        return any(provider.available() for provider in self.providers)

    async def extract(self, image_paths: List[str], prompt: str = "") -> str:
        for provider in self.providers:
            extract = getattr(provider, "extract", None)
            if provider.available() and extract is not None:
                return await extract(image_paths, prompt=prompt)
        return ""

    async def extract_pdf_until_usable(
        self,
        pdf_path: str,
        *,
        page_count: int,
        max_pages: int,
    ) -> Optional[OCRChainResult]:
        attempts: List[OCRAttempt] = []
        processed_pages = max(1, min(page_count or max_pages or 1, max_pages or page_count or 1))
        page_limit_reached = bool(page_count and max_pages and page_count > max_pages)
        for provider in self.providers:
            if not provider.available():
                attempts.append(OCRAttempt(provider=provider.name, status="unavailable"))
                continue
            try:
                raw_text = await provider.extract_pdf(pdf_path, max_pages=max_pages)
                cleaned_text = clean_pdf_text(raw_text)
                quality = assess_pdf_quality(
                    raw_text,
                    cleaned_text,
                    page_count=processed_pages,
                    non_empty_pages=processed_pages if raw_text.strip() else 0,
                )
                if quality.status != "needs_ocr":
                    attempts.append(OCRAttempt(provider=provider.name, status="accepted", quality=quality))
                    return OCRChainResult(
                        text=cleaned_text,
                        quality=quality,
                        provider=provider.name,
                        attempts=attempts,
                        source_page_count=page_count,
                        pages_processed=processed_pages,
                        page_limit_reached=page_limit_reached,
                        partial=page_limit_reached,
                    )
                attempts.append(OCRAttempt(provider=provider.name, status="needs_ocr", quality=quality))
            except Exception as exc:
                attempts.append(OCRAttempt(provider=provider.name, status="failed", error=str(exc)))
        return None


class PaddleOCRProvider:
    name = "paddle"

    def __init__(self, lang: str = "ch", use_angle_cls: bool = True, dpi: int = 150, enabled: bool = True):
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.dpi = dpi
        self.enabled = enabled
        self._ocr = None
        self._import_error: Optional[Exception] = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._ocr is not None:
            return True
        try:
            importlib.import_module("paddleocr")
            return True
        except Exception as exc:
            self._import_error = exc
            return False

    async def extract_pdf(self, pdf_path: str, max_pages: int = 50) -> str:
        if not self.available():
            return ""
        image_paths = _render_pdf_pages(pdf_path, max_pages=max_pages, dpi=self.dpi)
        try:
            if self._ocr is None:
                module = importlib.import_module("paddleocr")
                self._ocr = module.PaddleOCR(lang=self.lang, use_textline_orientation=self.use_angle_cls)
            page_texts = []
            for image_path in image_paths:
                result = self._ocr.ocr(image_path)
                text = _paddle_result_to_text(result)
                if text.strip():
                    page_texts.append(text)
            return "\n".join(page_texts).strip()
        finally:
            _cleanup_rendered_pages(image_paths)


class VolcengineOCR:
    name = "volcengine"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        max_images_per_request: int = 10,
        enabled: bool = True,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.max_images_per_request = max_images_per_request
        self.enabled = enabled

    def available(self) -> bool:
        return bool(self.enabled and self.endpoint and self.api_key and self.model)

    async def extract(self, image_paths: List[str], prompt: str = "") -> str:
        selected = image_paths[: self.max_images_per_request]
        if not self.available():
            return ""
        content = [
            {
                "type": "text",
                "text": prompt or "请逐张识别图片中的文字，按图片顺序输出纯文本。",
            }
        ]
        for image_path in selected:
            path = Path(image_path)
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{path.suffix.lstrip('.')};base64,{encoded}"},
                }
            )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error = None
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(self.endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                    return body["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"OCR failed after 3 retries: {last_error}")

    async def extract_pdf(self, pdf_path: str, max_pages: int = 50) -> str:
        image_paths = _render_pdf_pages(pdf_path, max_pages=max_pages, dpi=150)
        try:
            if not image_paths:
                return ""
            return await self.extract(image_paths, prompt=PDF_OCR_PROMPT)
        finally:
            _cleanup_rendered_pages(image_paths)


def build_ocr_provider_chain(config: Dict[str, Any]) -> OCRProviderChain:
    ocr_config = config.get("ocr", {})
    providers: List[OCRProvider] = []
    for provider_name in ocr_config.get("provider_order", ["paddle", "volcengine"]):
        if provider_name == "paddle":
            paddle_config = ocr_config.get("paddle", {})
            providers.append(
                PaddleOCRProvider(
                    enabled=bool(paddle_config.get("enabled", True)),
                    lang=str(paddle_config.get("lang", "ch")),
                    use_angle_cls=bool(paddle_config.get("use_angle_cls", True)),
                    dpi=int(paddle_config.get("dpi", 150)),
                )
            )
        elif provider_name == "volcengine":
            volcengine_config = ocr_config.get("volcengine", {})
            providers.append(
                VolcengineOCR(
                    endpoint=str(volcengine_config.get("endpoint", ocr_config.get("endpoint", ""))),
                    api_key=str(volcengine_config.get("api_key", ocr_config.get("api_key", ""))),
                    model=str(volcengine_config.get("model", ocr_config.get("model", ""))),
                    max_images_per_request=int(
                        volcengine_config.get(
                            "max_images_per_request",
                            ocr_config.get("max_images_per_request", 10),
                        )
                    ),
                    enabled=bool(volcengine_config.get("enabled", True)),
                )
            )
    return OCRProviderChain(providers)


def _render_pdf_pages(pdf_path: str, max_pages: int, dpi: int) -> List[str]:
    import fitz

    document = fitz.open(pdf_path)
    tmp_dir = tempfile.mkdtemp(prefix="pka_ocr_pdf_")
    image_paths: List[str] = []
    try:
        page_limit = min(document.page_count, max_pages)
        for page_index in range(page_limit):
            page = document[page_index]
            pixmap = page.get_pixmap(dpi=dpi)
            image_path = str(Path(tmp_dir) / f"page_{page_index + 1:03d}.png")
            pixmap.save(image_path)
            image_paths.append(image_path)
        return image_paths
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    finally:
        document.close()


def _cleanup_rendered_pages(image_paths: List[str]) -> None:
    if not image_paths:
        return
    tmp_dir = Path(image_paths[0]).parent
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _paddle_result_to_text(result) -> str:
    lines: List[str] = []
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        if not page:
            continue
        if hasattr(page, "get"):
            rec_texts = page.get("rec_texts")
            if isinstance(rec_texts, list):
                lines.extend(str(text) for text in rec_texts if str(text).strip())
                continue
        for item in page:
            if not item:
                continue
            if isinstance(item, str):
                lines.append(item)
                continue
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                candidate = item[1]
                if isinstance(candidate, str):
                    lines.append(candidate)
                elif isinstance(candidate, (list, tuple)) and candidate:
                    lines.append(str(candidate[0]))
    return "\n".join(line for line in lines if line.strip())
