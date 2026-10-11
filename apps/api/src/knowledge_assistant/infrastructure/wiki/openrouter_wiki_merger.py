import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from knowledge_assistant.domain.wiki.compiler import WikiPageDraft
from knowledge_assistant.domain.wiki.entities import WikiPage
from knowledge_assistant.domain.wiki.merger import (
    WikiConflictDraft,
    WikiMergeResult,
    WikiPageMerger,
)
from knowledge_assistant.infrastructure.openrouter_errors import (
    raise_openrouter_request_error,
    raise_openrouter_response_error,
)


class ConflictPayload(BaseModel):
    existing_statement: str = Field(min_length=1)
    incoming_statement: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class MergePayload(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1)
    content_markdown: str = Field(min_length=1)
    conflicts: list[ConflictPayload] = Field(default_factory=list)


class OpenRouterWikiPageMerger(WikiPageMerger):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout_seconds: float = 180.0,
    ) -> None:
        cleaned_api_key = api_key.strip()
        cleaned_model = model.strip()

        if not cleaned_api_key:
            raise ValueError("OpenRouter API key cannot be empty.")

        if not cleaned_model:
            raise ValueError("OpenRouter model cannot be empty.")

        self._api_key = cleaned_api_key
        self._model = cleaned_model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    async def merge(
        self,
        *,
        existing_page: WikiPage,
        incoming_draft: WikiPageDraft,
        document_title: str,
    ) -> WikiMergeResult:
        response_payload = {
            "model": self._model,
            "temperature": 0.0,
            "max_tokens": 12000,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": self._user_prompt(
                        existing_page=existing_page,
                        incoming_draft=incoming_draft,
                        document_title=document_title,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "wiki_page_merge",
                    "strict": True,
                    "schema": MergePayload.model_json_schema(),
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    self._base_url,
                    headers=headers,
                    content=json.dumps(
                        response_payload,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise_openrouter_request_error(
                error,
                operation="wiki merge",
            )

        try:
            raw_content = self._extract_content(response.json())
        except ValueError as error:
            raise_openrouter_response_error(
                error,
                operation="wiki merge",
            )

        try:
            payload = MergePayload.model_validate_json(raw_content)
        except ValidationError as error:
            raise ValueError(
                "The LLM returned an invalid Wiki merge structure."
            ) from error

        return WikiMergeResult(
            title=payload.title.strip(),
            summary=payload.summary.strip(),
            content_markdown=payload.content_markdown.strip(),
            conflicts=tuple(
                WikiConflictDraft(
                    existing_statement=item.existing_statement.strip(),
                    incoming_statement=item.incoming_statement.strip(),
                    explanation=item.explanation.strip(),
                )
                for item in payload.conflicts
            ),
        )

    @staticmethod
    def _extract_content(response_data: dict[str, Any]) -> str:
        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(
                "OpenRouter returned an unexpected Wiki merge response."
            ) from error

        if isinstance(content, str) and content.strip():
            return content.strip()

        raise ValueError("OpenRouter returned an empty Wiki merge response.")

    @staticmethod
    def _system_prompt() -> str:
        return """
You maintain a long-lived internal Wiki from traceable source documents.
Merge the incoming draft into the existing page without deleting valid,
source-supported knowledge. Keep the page concise, structured and neutral.
Do not invent facts. Do not silently choose one side when two sources make
materially incompatible claims. Preserve both claims in the merged article
with cautious wording and return each contradiction in the conflicts array.
Preserve every existing and incoming Markdown citation link whose target starts
with citation:. Do not rename, remove, or invent citation identifiers. Place the
citation link at the end of the factual paragraph it supports. A conflict is a
factual disagreement, not merely a difference in wording or level of detail.
Return valid JSON matching the supplied schema only.
""".strip()

    @staticmethod
    def _user_prompt(
        *,
        existing_page: WikiPage,
        incoming_draft: WikiPageDraft,
        document_title: str,
    ) -> str:
        return f"""
EXISTING WIKI PAGE
Title: {existing_page.title}
Slug: {existing_page.slug}
Summary: {existing_page.summary}
Content:
{existing_page.content_markdown}

INCOMING SOURCE DOCUMENT
{document_title}

INCOMING WIKI DRAFT
Title: {incoming_draft.title}
Slug: {incoming_draft.slug}
Summary: {incoming_draft.summary}
Content:
{incoming_draft.content_markdown}

Produce one merged page. Keep the existing page identity and topic. Report
only genuine factual conflicts in conflicts.
""".strip()
