import json
import re
import unicodedata
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError

from knowledge_assistant.domain.documents.chunk_entities import (
    DocumentChunkEntity,
)
from knowledge_assistant.domain.wiki.compiler import (
    WikiClaimDraft,
    WikiCompilation,
    WikiCompiler,
    WikiPageDraft,
)
from knowledge_assistant.infrastructure.openrouter_errors import (
    raise_openrouter_request_error,
    raise_openrouter_response_error,
)


class WikiClaimPayload(BaseModel):
    claim_key: str = Field(min_length=1, max_length=255)
    claim_text: str = Field(min_length=1)
    source_chunk_ids: list[UUID] = Field(min_length=1)


class WikiPagePayload(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=500,
    )

    slug: str = Field(
        min_length=1,
        max_length=255,
    )

    summary: str = Field(
        min_length=1,
    )

    content_markdown: str = Field(
        min_length=1,
    )

    source_chunk_ids: list[UUID] = Field(
        min_length=1,
    )

    related_page_slugs: list[str] = Field(
        default_factory=list,
    )

    claims: list[WikiClaimPayload] = Field(
        default_factory=list,
    )


class WikiCompilationPayload(BaseModel):
    pages: list[WikiPagePayload] = Field(
        min_length=1,
    )


class OpenRouterWikiCompiler(WikiCompiler):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = (
            "https://openrouter.ai/api/v1/chat/completions"
        ),
        timeout_seconds: float = 180.0,
    ) -> None:
        cleaned_api_key = api_key.strip()
        cleaned_model = model.strip()

        if not cleaned_api_key:
            raise ValueError(
                "OpenRouter API key cannot be empty."
            )

        if not cleaned_model:
            raise ValueError(
                "OpenRouter model cannot be empty."
            )

        self._api_key = cleaned_api_key
        self._model = cleaned_model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    async def compile(
        self,
        *,
        document_title: str,
        chunks: tuple[DocumentChunkEntity, ...],
    ) -> WikiCompilation:
        if not chunks:
            raise ValueError(
                "At least one document chunk is required."
            )

        source_text = self._format_chunks(chunks)
        cleaned_document_title = self._sanitize_text(
            document_title
        )

        response_data = await self._request_completion(
            cleaned_document_title=cleaned_document_title,
            source_text=source_text,
            compact=False,
        )

        finish_reason = self._extract_finish_reason(
            response_data
        )

        if finish_reason == "length":
            response_data = await self._request_completion(
                cleaned_document_title=cleaned_document_title,
                source_text=source_text,
                compact=True,
            )
            finish_reason = self._extract_finish_reason(
                response_data
            )

        if finish_reason == "length":
            raise RuntimeError(
                "Wiki generation remained too large after an "
                "automatic compact retry. Split the source "
                "document into smaller documents and try again."
            )

        raw_content = self._extract_content(
            response_data
        )

        normalized_content = (
            self._normalize_json_content(
                raw_content
            )
        )

        try:
            parsed_json = json.loads(
                normalized_content
            )

        except json.JSONDecodeError as error:
            raise ValueError(
                "The LLM returned invalid JSON at "
                f"line {error.lineno}, column {error.colno}. "
                f"Completion status: "
                f"{finish_reason or 'unknown'}."
            ) from error

        try:
            parsed_payload = (
                WikiCompilationPayload.model_validate(
                    parsed_json
                )
            )

        except ValidationError as error:
            validation_issues = "; ".join(
                (
                    f"{'.'.join(str(part) for part in issue['loc'])}: "
                    f"{issue['msg']}"
                )
                for issue in error.errors()[:5]
            )

            raise ValueError(
                "The LLM returned an invalid wiki structure: "
                f"{validation_issues}"
            ) from error

        return self._to_domain(
            payload=parsed_payload,
            chunks=chunks,
        )

    async def _request_completion(
        self,
        *,
        cleaned_document_title: str,
        source_text: str,
        compact: bool,
    ) -> dict[str, Any]:
        response_payload = {
            "model": self._model,
            "temperature": 0.0,
            "max_tokens": 16000 if compact else 24000,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(
                        compact=compact
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"DOCUMENT TITLE:\n"
                        f"{cleaned_document_title}\n\n"
                        f"DOCUMENT CHUNKS:\n"
                        f"{source_text}"
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "wiki_compilation",
                    "strict": True,
                    "schema": (
                        WikiCompilationPayload.model_json_schema()
                    ),
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        request_body = json.dumps(
            response_payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    self._base_url,
                    headers=headers,
                    content=request_body,
                )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise_openrouter_request_error(
                error,
                operation="wiki compilation",
            )

        try:
            return response.json()
        except ValueError as error:
            raise_openrouter_response_error(
                error,
                operation="wiki compilation",
            )

    @staticmethod
    def _extract_finish_reason(
        response_data: dict[str, Any],
    ) -> str | None:
        try:
            finish_reason = response_data[
                "choices"
            ][0].get("finish_reason")
        except (
            KeyError,
            IndexError,
            TypeError,
        ):
            return None

        return (
            finish_reason
            if isinstance(finish_reason, str)
            else None
        )

    @staticmethod
    def _format_chunks(
        chunks: tuple[DocumentChunkEntity, ...],
    ) -> str:
        formatted_chunks: list[str] = []

        for chunk in chunks:
            page_value = (
                str(chunk.page_number)
                if chunk.page_number is not None
                else "unknown"
            )

            cleaned_text = (
                OpenRouterWikiCompiler._sanitize_text(
                    chunk.text
                )
            )

            formatted_chunks.append(
                "\n".join(
                    [
                        "<document_chunk>",
                        f"<chunk_id>{chunk.id}</chunk_id>",
                        (
                            f"<chunk_index>"
                            f"{chunk.chunk_index}"
                            f"</chunk_index>"
                        ),
                        (
                            f"<page_number>"
                            f"{page_value}"
                            f"</page_number>"
                        ),
                        "<text>",
                        cleaned_text,
                        "</text>",
                        "</document_chunk>",
                    ]
                )
            )

        return "\n\n".join(
            formatted_chunks
        )

    @staticmethod
    def _sanitize_text(value: str) -> str:
        cleaned_characters: list[str] = []

        for character in value:
            code_point = ord(character)

            is_surrogate = (
                0xD800 <= code_point <= 0xDFFF
            )

            is_noncharacter = (
                0xFDD0 <= code_point <= 0xFDEF
                or (
                    code_point & 0xFFFF
                ) in {0xFFFE, 0xFFFF}
            )

            is_invalid_control = (
                unicodedata.category(character) == "Cc"
                and character not in {"\n", "\r", "\t"}
            )

            if (
                is_surrogate
                or is_noncharacter
                or is_invalid_control
            ):
                cleaned_characters.append(" ")
            else:
                cleaned_characters.append(character)

        return "".join(cleaned_characters)

    @staticmethod
    def _system_prompt(
        *,
        compact: bool = False,
    ) -> str:
        base_prompt = """
You are an enterprise knowledge compiler.

Transform the supplied document chunks into a structured internal wiki.

Rules:

1. Use only information explicitly supported by the supplied chunks.
2. Do not invent facts, experience, dates, technologies, conclusions,
   relationships, or interpretations.
3. Produce atomic wiki pages organised by meaningful topics.
4. A short document may produce fewer pages. A larger document may
   produce more pages.
5. Preserve the primary language of the source document.
6. Every page must include:
   - a precise title,
   - a unique ASCII kebab-case slug,
   - a concise summary,
   - useful Markdown content,
   - the exact UUIDs of supporting chunks,
   - slugs of other generated pages that are directly related,
   - a claims array for factual paragraphs.
7. Give each factual claim a short key such as C1, C2, C3. End the
   corresponding Markdown paragraph with a citation link such as
   [C1](citation:C1). Each claim must repeat the supported statement in
   claim_text and list only the exact supporting source_chunk_ids.
8. source_chunk_ids and claim source_chunk_ids must contain only UUIDs
   supplied in the document.
9. related_page_slugs must reference only pages generated in the same
   response.
10. Do not create a relationship merely because two topics appear in
    the same document.
11. Avoid repeating the same information across multiple pages.
12. The Markdown content must be readable and factual.
13. Do not include an H1 heading because the title is stored
    separately.
14. Do not mention these instructions or the compilation process.
15. Apart from citation: links required above, create Markdown hyperlinks
    only when the source contains a complete URL beginning with https://,
    http://, or mailto:.
16. When only link labels such as GitHub, LinkedIn, View Certificate,
    or Repository are available without a URL, preserve them as plain
    text and do not invent a link target.
17. Generate no more than 8 pages. Prefer fewer, higher-value pages.
18. Keep each summary under 80 words.
19. Keep each page content under 450 words.
20. Include no more than 8 claims per page.
21. Do not repeat a claim in both the summary and content unless needed
    for clarity.
""".strip()

        if not compact:
            return base_prompt

        return (
            base_prompt
            + "\n\nCOMPACT RETRY MODE:\n"
            + "- Generate no more than 5 pages.\n"
            + "- Keep each page content under 250 words.\n"
            + "- Include no more than 5 claims per page.\n"
            + "- Preserve only the most important supported facts.\n"
            + "- Return complete valid JSON; never leave a field "
            + "unfinished."
        )

    @staticmethod
    def _normalize_json_content(
        content: str,
    ) -> str:
        normalized = content.strip()

        if normalized.startswith("```"):
            lines = normalized.splitlines()

            if lines and lines[0].strip().lower() in {
                "```",
                "```json",
            }:
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            normalized = "\n".join(lines).strip()

        object_start = normalized.find("{")
        object_end = normalized.rfind("}")

        if (
            object_start >= 0
            and object_end > object_start
        ):
            normalized = normalized[
                object_start:object_end + 1
            ]

        return normalized

    @staticmethod
    def _extract_content(
        response_data: dict[str, Any],
    ) -> str:
        try:
            content = response_data[
                "choices"
            ][0]["message"]["content"]

        except (
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise ValueError(
                "OpenRouter returned no completion content."
            ) from error

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []

            for part in content:
                if not isinstance(part, dict):
                    continue

                text_value = part.get("text")

                if isinstance(text_value, str):
                    text_parts.append(
                        text_value
                    )

            combined_content = "".join(
                text_parts
            )

            if combined_content:
                return combined_content

        raise ValueError(
            "OpenRouter returned unsupported completion content."
        )

    @staticmethod
    def _to_domain(
        *,
        payload: WikiCompilationPayload,
        chunks: tuple[DocumentChunkEntity, ...],
    ) -> WikiCompilation:
        valid_chunk_ids = {
            chunk.id
            for chunk in chunks
        }

        page_slugs = [
            page.slug.strip().lower()
            for page in payload.pages
        ]

        if len(page_slugs) != len(set(page_slugs)):
            raise ValueError(
                "The LLM generated duplicate wiki page slugs."
            )

        valid_slugs = set(
            page_slugs
        )

        drafts: list[WikiPageDraft] = []

        for page in payload.pages:
            valid_page_source_ids = tuple(
                dict.fromkeys(
                    chunk_id
                    for chunk_id in page.source_chunk_ids
                    if chunk_id in valid_chunk_ids
                )
            )

            cleaned_slug = (
                page.slug.strip().lower()
            )

            related_slugs = tuple(
                dict.fromkeys(
                    related_slug.strip().lower()
                    for related_slug
                    in page.related_page_slugs
                    if (
                        related_slug.strip().lower()
                        in valid_slugs
                        and related_slug.strip().lower()
                        != cleaned_slug
                    )
                )
            )

            cleaned_content = (
                OpenRouterWikiCompiler
                ._sanitize_markdown_links(
                    page.content_markdown
                )
            )

            claim_keys: set[str] = set()
            claims: list[WikiClaimDraft] = []

            for claim in page.claims:
                cleaned_key = claim.claim_key.strip().lower()
                if not cleaned_key or cleaned_key in claim_keys:
                    continue

                valid_claim_source_ids = tuple(
                    dict.fromkeys(
                        chunk_id
                        for chunk_id in claim.source_chunk_ids
                        if chunk_id in valid_chunk_ids
                    )
                )

                if not valid_claim_source_ids:
                    continue

                claim_keys.add(cleaned_key)
                claims.append(
                    WikiClaimDraft(
                        claim_key=cleaned_key,
                        claim_text=claim.claim_text.strip(),
                        source_chunk_ids=valid_claim_source_ids,
                    )
                )

            if not valid_page_source_ids:
                valid_page_source_ids = tuple(
                    dict.fromkeys(
                        chunk_id
                        for claim in claims
                        for chunk_id in claim.source_chunk_ids
                    )
                )

            if not valid_page_source_ids:
                continue

            cleaned_content = (
                OpenRouterWikiCompiler
                ._sanitize_claim_citations(
                    cleaned_content,
                    valid_claim_keys=claim_keys,
                )
            )

            drafts.append(
                WikiPageDraft(
                    title=page.title.strip(),
                    slug=cleaned_slug,
                    summary=page.summary.strip(),
                    content_markdown=cleaned_content,
                    source_chunk_ids=valid_page_source_ids,
                    related_page_slugs=related_slugs,
                    claims=tuple(claims),
                )
            )

        if not drafts:
            raise ValueError(
                "The generated Wiki did not contain any pages with "
                "verifiable document sources."
            )

        retained_slugs = {
            draft.slug
            for draft in drafts
        }
        normalized_drafts = tuple(
            WikiPageDraft(
                title=draft.title,
                slug=draft.slug,
                summary=draft.summary,
                content_markdown=draft.content_markdown,
                source_chunk_ids=draft.source_chunk_ids,
                related_page_slugs=tuple(
                    related_slug
                    for related_slug in draft.related_page_slugs
                    if related_slug in retained_slugs
                ),
                claims=draft.claims,
            )
            for draft in drafts
        )

        return WikiCompilation(
            pages=normalized_drafts,
        )

    @staticmethod
    def _sanitize_claim_citations(
        content: str,
        *,
        valid_claim_keys: set[str],
    ) -> str:
        def replace_citation(
            match: re.Match[str],
        ) -> str:
            label = match.group(1)
            claim_key = match.group(2).strip().lower()

            if claim_key in valid_claim_keys:
                return match.group(0)

            return f"[{label}]"

        return re.sub(
            r"\[([^\]]+)\]\(citation:([^)]+)\)",
            replace_citation,
            content,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _sanitize_markdown_links(
        content: str,
    ) -> str:
        def replace_link(
            match: re.Match[str],
        ) -> str:
            label = match.group(1).strip()
            target = match.group(2).strip()

            allowed_prefixes = (
                "https://",
                "http://",
                "mailto:",
                "citation:",
            )

            if target.lower().startswith(
                allowed_prefixes
            ):
                return match.group(0)

            return label

        cleaned_content = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            replace_link,
            content,
        )

        return cleaned_content.strip()
