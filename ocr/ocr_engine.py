from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from utils.settings import SettingsManager


class OCREngine:
    def __init__(self, settings: SettingsManager) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.get_openai_api_key())

    def extract_text(self, image_bytes: bytes, options: dict[str, Any] | None = None) -> str:
        options = options or {}
        api_key = self.settings.get_openai_api_key()
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured")

        client = OpenAI(api_key=api_key)
        model = str(self.settings.get("ocr", "model", default="gpt-4o"))

        preserve = bool(options.get("preserve_formatting", True))
        translate_to = options.get("translate_to")

        system_prompt = (
            "You are a precise OCR engine. Extract all visible text from the image. "
            "Return only the extracted text."
        )
        if preserve:
            system_prompt += " Preserve original line breaks and layout when possible."
        if translate_to:
            system_prompt += f" After extraction, translate the text to {translate_to}."

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        }
                    ],
                },
            ],
        )

        content = response.choices[0].message.content
        return content.strip() if isinstance(content, str) else ""
