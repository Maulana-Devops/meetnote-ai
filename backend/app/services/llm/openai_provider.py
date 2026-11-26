"""Provider AI memakai OpenAI Responses API + Structured Outputs.

Dokumentasi resmi diperiksa 23 Nov 2026:
    POST {LLM_API_BASE_URL}/responses
    Authorization: Bearer {LLM_API_KEY}
    text.format = {type: "json_schema", name: ..., schema: ..., strict: true}

Structured Outputs menjamin bentuk JSON, tetapi aplikasi TETAP memvalidasi
aturan bisnis (referensi segmen, speaker, deadline) di workflow sebelum
menyimpan. Tidak ada SDK baru: HTTP dipakai lewat httpx dari Sprint 4.

Sprint 7 memakai schema ``meeting_summary``; Sprint 8 memakai schema
``action_items`` pada endpoint dan provider yang SAMA.
"""

import json
from typing import Any

import httpx

from ...core.config import settings
from ..summary.prompts import build_summary_system_prompt
from .base import (
    ACTION_ITEMS_FORMAT_NAME,
    ACTION_ITEMS_JSON_SCHEMA,
    ACTION_ITEMS_SYSTEM_PROMPT,
    SUMMARY_FORMAT_NAME,
    SUMMARY_JSON_SCHEMA,
    ActionItemExtractionResult,
    ActionItemInput,
    SummaryInput,
    SummaryResult,
    format_action_items_input,
    format_transcript,
    parse_action_items_payload,
    parse_summary_payload,
)
from .errors import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmInvalidResultError,
    LlmProviderError,
    LlmRateLimitError,
    LlmTimeoutError,
)

class OpenAiLlmProvider:
    """Provider OpenAI untuk ringkasan dan action items terstruktur."""

    name = "openai"

    @property
    def model(self) -> str:
        return settings.LLM_MODEL

    def validate_configuration(self) -> None:
        if not settings.LLM_API_KEY.get_secret_value().strip():
            raise LlmConfigurationError(
                "LLM_API_KEY belum diisi. Isi di backend/.env atau pakai LLM_PROVIDER=mock."
            )
        if not settings.LLM_API_BASE_URL.strip():
            raise LlmConfigurationError("LLM_API_BASE_URL tidak boleh kosong.")
        if not settings.LLM_MODEL.strip():
            raise LlmConfigurationError("LLM_MODEL tidak boleh kosong.")
        if settings.LLM_TIMEOUT_SECONDS <= 0:
            raise LlmConfigurationError("LLM_TIMEOUT_SECONDS harus lebih besar dari 0.")
        if settings.LLM_MAX_INPUT_CHARACTERS <= 0:
            raise LlmConfigurationError("LLM_MAX_INPUT_CHARACTERS harus lebih besar dari 0.")

    def summarize(self, data: SummaryInput) -> SummaryResult:
        payload, response_model = self._request_json(
            schema_name=SUMMARY_FORMAT_NAME,
            schema=SUMMARY_JSON_SCHEMA,
            system_prompt=build_summary_system_prompt(
                data, default_language=settings.LLM_OUTPUT_LANGUAGE
            ),
            user_prompt=format_transcript(data),
        )
        return parse_summary_payload(payload, provider=self.name, model=response_model)

    def extract_action_items(self, data: ActionItemInput) -> ActionItemExtractionResult:
        payload, response_model = self._request_json(
            schema_name=ACTION_ITEMS_FORMAT_NAME,
            schema=ACTION_ITEMS_JSON_SCHEMA,
            system_prompt=ACTION_ITEMS_SYSTEM_PROMPT,
            user_prompt=format_action_items_input(data),
        )
        return parse_action_items_payload(payload, provider=self.name, model=response_model)

    def _request_json(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict[str, Any], str]:
        """Satu jalur HTTP untuk kedua schema; kirim secret hanya ke provider."""
        self.validate_configuration()
        url = f"{settings.LLM_API_BASE_URL.rstrip('/')}/responses"
        request_payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }

        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(
                f"Provider LLM tidak merespons dalam {settings.LLM_TIMEOUT_SECONDS:.0f} detik."
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmProviderError(
                f"Gagal menghubungi provider LLM: {exc.__class__.__name__}"
            ) from exc

        return OpenAiLlmProvider._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> tuple[dict[str, Any], str]:
        status = response.status_code
        if status in (401, 403):
            raise LlmAuthenticationError(
                "Provider LLM menolak kredensial (periksa LLM_API_KEY)."
            )
        if status == 429:
            raise LlmRateLimitError("Provider LLM membatasi permintaan. Coba lagi nanti.")
        if status in (408, 504):
            raise LlmTimeoutError("Provider LLM mengalami timeout.")
        if status >= 400:
            raise LlmProviderError(f"Provider LLM gagal (HTTP {status}).")

        try:
            payload = response.json()
        except ValueError as exc:
            raise LlmProviderError("Provider LLM mengembalikan respons bukan JSON.") from exc
        if not isinstance(payload, dict):
            raise LlmProviderError("Format respons provider LLM tidak dikenali.")

        response_status = payload.get("status")
        if isinstance(response_status, str) and response_status not in {
            "completed",
            "queued",
            "in_progress",
        }:
            raise LlmProviderError(
                f"Respons provider LLM tidak selesai (status: {response_status})."
            )

        raw_text = OpenAiLlmProvider._extract_output_text(payload)
        if not raw_text:
            raise LlmInvalidResultError(
                "Provider LLM tidak mengembalikan teks hasil (mungkin menolak permintaan)."
            )

        try:
            parsed = json.loads(raw_text)
        except (TypeError, ValueError) as exc:
            raise LlmInvalidResultError("Provider LLM mengembalikan JSON tidak valid.") from exc
        if not isinstance(parsed, dict):
            raise LlmInvalidResultError("Provider LLM mengembalikan JSON bukan objek.")
        model_name = str(payload.get("model") or settings.LLM_MODEL)
        return parsed, model_name

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        """Ambil output_text dari item message Responses API."""
        chunks: list[str] = []

        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "refusal":
                    raise LlmInvalidResultError("Provider LLM menolak permintaan.")
                if item.get("type") != "message":
                    continue
                if item.get("status") == "incomplete":
                    raise LlmInvalidResultError("Respons provider LLM terpotong (incomplete).")
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "refusal":
                        raise LlmInvalidResultError("Provider LLM menolak permintaan.")
                    if part.get("type") == "output_text":
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            chunks.append(text)

        if chunks:
            return "\n".join(chunks).strip()

        # Beberapa endpoint kompatibel menyediakan output_text ringkas.
        direct = payload.get("output_text")
        return direct.strip() if isinstance(direct, str) else ""
