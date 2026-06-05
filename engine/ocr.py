import base64
from pathlib import Path
from typing import List

import httpx


class VolcengineOCR:
    def __init__(self, endpoint: str, api_key: str, model: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model

    async def extract(self, image_paths: List[str]) -> str:
        selected = image_paths[:10]
        if not self.endpoint or not self.api_key:
            return ""
        content = [
            {
                "type": "text",
                "text": "请逐张识别图片中的文字，按图片顺序输出纯文本。",
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
