import math
from uuid import UUID

from knowledge_assistant.application.chat.services.citation_validator import (
    validate_generated_answer,
)
from knowledge_assistant.domain.chat.answer_generator import (
    KnowledgeAnswerGenerator,
)
from knowledge_assistant.domain.chat.entities import (
    KnowledgeChatResult,
    RetrievedKnowledgeSource,
)
from knowledge_assistant.domain.documents.repository import (
    DocumentRepository,
)
from knowledge_assistant.domain.embeddings.service import (
    EmbeddingService,
)
from knowledge_assistant.domain.vector_store.store import (
    VectorStore,
)
from knowledge_assistant.domain.wiki.entities import WikiPage
from knowledge_assistant.domain.wiki.repository import (
    WikiRepository,
)


class AskKnowledgeQuery:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        wiki_repository: WikiRepository,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        answer_generator: KnowledgeAnswerGenerator,
        max_wiki_pages: int = 3,
        max_vector_chunks: int = 4,
        minimum_wiki_score: float = 0.20,
        vector_fallback_threshold: float = 0.45,
        minimum_vector_score: float = 0.15,
    ) -> None:
        self._document_repository = document_repository
        self._wiki_repository = wiki_repository
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._answer_generator = answer_generator
        self._max_wiki_pages = max_wiki_pages
        self._max_vector_chunks = max_vector_chunks
        self._minimum_wiki_score = minimum_wiki_score
        self._vector_fallback_threshold = (
            vector_fallback_threshold
        )
        self._minimum_vector_score = minimum_vector_score

    async def execute(
        self,
        *,
        owner_id: UUID,
        question: str,
        assistant_behavior: str = "balanced",
        preferred_language: str = "en",
    ) -> KnowledgeChatResult:
        cleaned_question = question.strip()

        if not cleaned_question:
            raise ValueError(
                "Question cannot be empty."
            )

        query_embedding = (
            await self._embedding_service.embed_query(
                cleaned_question
            )
        )

        wiki_pages = (
            await self._wiki_repository.list_by_owner_id(
                owner_id
            )
        )
        wiki_pages = [
            page
            for page in wiki_pages
            if page.owner_id == owner_id
        ]

        wiki_candidates = await self._rank_wiki_pages(
            pages=wiki_pages,
            query_embedding=query_embedding,
        )

        sources: list[RetrievedKnowledgeSource] = []

        for page, page_text, score in wiki_candidates:
            sources.append(
                RetrievedKnowledgeSource(
                    source_id=f"S{len(sources) + 1}",
                    source_type="wiki",
                    document_id=page.document_id,
                    title=page.title,
                    slug=page.slug,
                    text=page_text,
                    score=score,
                )
            )

        best_wiki_score = (
            wiki_candidates[0][2]
            if wiki_candidates
            else 0.0
        )

        use_vector_fallback = (
            not wiki_candidates
            or best_wiki_score
            < self._vector_fallback_threshold
        )

        vector_sources_added = False

        if use_vector_fallback:
            owner_documents = (
                await self._document_repository.list_by_owner_id(owner_id)
            )
            owner_documents_by_id = {
                document.id: document
                for document in owner_documents
                if document.owner_id == owner_id
                and document.active_ingestion_generation is not None
            }
            active_ingestion_generations = {
                document.id: document.active_ingestion_generation
                for document in owner_documents_by_id.values()
            }
            vector_results = await self._vector_store.search(
                owner_id=owner_id,
                active_ingestion_generations=(
                    active_ingestion_generations
                ),
                query_embedding=query_embedding,
                limit=self._max_vector_chunks,
            )

            for result in vector_results:
                if result.score < self._minimum_vector_score:
                    continue

                document = owner_documents_by_id.get(result.document_id)

                if document is None:
                    continue

                sources.append(
                    RetrievedKnowledgeSource(
                        source_id=f"S{len(sources) + 1}",
                        source_type="document_chunk",
                        document_id=result.document_id,
                        title=document.original_filename,
                        text=result.text,
                        page_number=result.page_number,
                        chunk_index=result.chunk_index,
                        score=result.score,
                    )
                )

                vector_sources_added = True

        if not sources:
            return KnowledgeChatResult(
                answer_markdown=self._insufficient_evidence_answer(
                    preferred_language
                ),
                retrieval_mode="none",
                sources=(),
            )

        available_source_ids = frozenset(
            source.source_id
            for source in sources
        )
        validation_feedback: tuple[str, ...] = ()
        validated_source_ids: tuple[str, ...] | None = None
        answer_markdown = ""

        for _attempt in range(2):
            generated_answer = await self._answer_generator.generate(
                question=cleaned_question,
                sources=tuple(sources),
                assistant_behavior=assistant_behavior,
                preferred_language=preferred_language,
                validation_feedback=validation_feedback,
            )
            validation = validate_generated_answer(
                answer_markdown=generated_answer.answer_markdown,
                used_source_ids=generated_answer.used_source_ids,
                available_source_ids=available_source_ids,
            )

            if validation.is_valid:
                answer_markdown = generated_answer.answer_markdown
                validated_source_ids = validation.cited_source_ids
                break

            validation_feedback = validation.failures

        if validated_source_ids is None:
            return KnowledgeChatResult(
                answer_markdown=self._insufficient_evidence_answer(
                    preferred_language
                ),
                retrieval_mode="none",
                sources=(),
            )

        visible_sources = self._select_visible_sources(
            sources=tuple(sources),
            used_source_ids=validated_source_ids,
        )

        if not visible_sources:
            return KnowledgeChatResult(
                answer_markdown=answer_markdown,
                retrieval_mode="none",
                sources=(),
            )

        wiki_sources_added = bool(wiki_candidates)

        if wiki_sources_added and vector_sources_added:
            retrieval_mode = "hybrid"
        elif wiki_sources_added:
            retrieval_mode = "wiki"
        else:
            retrieval_mode = "vector"

        return KnowledgeChatResult(
            answer_markdown=answer_markdown,
            retrieval_mode=retrieval_mode,
            sources=visible_sources,
        )

    async def _rank_wiki_pages(
        self,
        *,
        pages: list[WikiPage],
        query_embedding: list[float],
    ) -> list[tuple[WikiPage, str, float]]:
        if not pages:
            return []

        page_texts = [
            self._format_wiki_page(page)
            for page in pages
        ]

        page_embeddings = (
            await self._embedding_service.embed_documents(
                page_texts
            )
        )

        if len(page_embeddings) != len(pages):
            raise ValueError(
                "Wiki embedding count does not match page count."
            )

        ranked_pages: list[
            tuple[WikiPage, str, float]
        ] = []

        for page, page_text, page_embedding in zip(
            pages,
            page_texts,
            page_embeddings,
            strict=True,
        ):
            score = self._cosine_similarity(
                query_embedding,
                page_embedding,
            )

            if score < self._minimum_wiki_score:
                continue

            ranked_pages.append(
                (
                    page,
                    page_text,
                    score,
                )
            )

        ranked_pages.sort(
            key=lambda item: item[2],
            reverse=True,
        )

        return ranked_pages[:self._max_wiki_pages]

    @staticmethod
    def _format_wiki_page(
        page: WikiPage,
    ) -> str:
        return "\n\n".join(
            part
            for part in (
                page.title,
                page.summary,
                page.content_markdown,
            )
            if part.strip()
        )

    @staticmethod
    def _cosine_similarity(
        first: list[float],
        second: list[float],
    ) -> float:
        if len(first) != len(second):
            raise ValueError(
                "Embedding dimensions do not match."
            )

        dot_product = sum(
            left * right
            for left, right in zip(
                first,
                second,
                strict=True,
            )
        )

        first_norm = math.sqrt(
            sum(value * value for value in first)
        )

        second_norm = math.sqrt(
            sum(value * value for value in second)
        )

        denominator = first_norm * second_norm

        if denominator == 0:
            return 0.0

        return dot_product / denominator

    @staticmethod
    def _select_visible_sources(
        *,
        sources: tuple[RetrievedKnowledgeSource, ...],
        used_source_ids: tuple[str, ...],
    ) -> tuple[RetrievedKnowledgeSource, ...]:
        used_source_id_set = set(used_source_ids)

        return tuple(
            source
            for source in sources
            if source.source_id in used_source_id_set
        )

    @staticmethod
    def _insufficient_evidence_answer(
        preferred_language: str,
    ) -> str:
        if preferred_language == "el":
            return (
                "Τα διαθέσιμα έγγραφα δεν παρέχουν αρκετές "
                "αξιόπιστα τεκμηριωμένες πληροφορίες για να "
                "απαντηθεί αυτή η ερώτηση."
            )

        return (
            "The available documents do not provide enough reliably "
            "cited information to answer this question."
        )
