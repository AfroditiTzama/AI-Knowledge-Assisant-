import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import chromadb

from knowledge_assistant.domain.documents.entities import (
    LEGACY_INGESTION_GENERATION,
)
from knowledge_assistant.domain.vector_store.store import (
    VectorRecord,
    VectorSearchResult,
    VectorStore,
)


class ChromaVectorStore(VectorStore):
    def __init__(
        self,
        *,
        storage_directory: str | Path = "storage/chroma",
        collection_name: str = "document_chunks",
    ) -> None:
        self._client = chromadb.PersistentClient(
            path=str(Path(storage_directory).resolve())
        )

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            configuration={
                "hnsw": {
                    "space": "cosine",
                }
            },
        )

    async def stage_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
        records: tuple[VectorRecord, ...],
    ) -> None:
        await asyncio.to_thread(
            self._stage_document_records_sync,
            owner_id,
            document_id,
            ingestion_generation,
            records,
        )

    async def delete_document_generation(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
    ) -> None:
        await asyncio.to_thread(
            self._delete_document_generation_sync,
            owner_id,
            document_id,
            ingestion_generation,
        )

    async def cleanup_inactive_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        active_ingestion_generation: UUID | None,
    ) -> None:
        await asyncio.to_thread(
            self._cleanup_inactive_document_records_sync,
            owner_id,
            document_id,
            active_ingestion_generation,
        )

    async def delete_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
    ) -> None:
        await asyncio.to_thread(
            self._delete_document_records_sync,
            owner_id,
            document_id,
        )

    async def search(
        self,
        *,
        owner_id: UUID,
        active_ingestion_generations: dict[UUID, UUID],
        query_embedding: list[float],
        limit: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        if not query_embedding:
            raise ValueError("Query embedding cannot be empty.")

        if limit <= 0:
            raise ValueError("Search limit must be greater than zero.")

        return await asyncio.to_thread(
            self._search_sync,
            owner_id,
            active_ingestion_generations,
            query_embedding,
            limit,
        )

    def _delete_document_records_sync(
        self,
        owner_id: UUID,
        document_id: UUID,
    ) -> None:
        self._collection.delete(
            where={
                "$and": [
                    {"owner_id": str(owner_id)},
                    {"document_id": str(document_id)},
                ]
            }
        )

    def _stage_document_records_sync(
        self,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
        records: tuple[VectorRecord, ...],
    ) -> None:
        for record in records:
            if record.owner_id != owner_id:
                raise ValueError("Vector record owner does not match.")
            if record.document_id != document_id:
                raise ValueError("Vector record document does not match.")

        self._delete_document_generation_sync(
            owner_id,
            document_id,
            ingestion_generation,
        )

        if not records:
            return

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int]] = []

        for record in records:
            metadata: dict[str, str | int] = {
                "owner_id": str(record.owner_id),
                "document_id": str(record.document_id),
                "chunk_index": record.chunk_index,
                "ingestion_generation": str(ingestion_generation),
            }

            if record.page_number is not None:
                metadata["page_number"] = record.page_number

            ids.append(record.id)
            embeddings.append(record.embedding)
            documents.append(record.text)
            metadatas.append(metadata)

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        verification = self._collection.get(ids=ids, include=["metadatas"])
        if set(verification.get("ids", [])) != set(ids):
            raise RuntimeError("The staged vector generation could not be verified.")

        for metadata in verification.get("metadatas") or []:
            if (
                metadata is None
                or metadata.get("owner_id") != str(owner_id)
                or metadata.get("document_id") != str(document_id)
                or metadata.get("ingestion_generation")
                != str(ingestion_generation)
            ):
                raise RuntimeError(
                    "The staged vector generation could not be verified."
                )

    def _delete_document_generation_sync(
        self,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
    ) -> None:
        self._collection.delete(
            where={
                "$and": [
                    {"owner_id": str(owner_id)},
                    {"document_id": str(document_id)},
                    {"ingestion_generation": str(ingestion_generation)},
                ]
            }
        )

    def _cleanup_inactive_document_records_sync(
        self,
        owner_id: UUID,
        document_id: UUID,
        active_ingestion_generation: UUID | None,
    ) -> None:
        records = self._collection.get(
            where={
                "$and": [
                    {"owner_id": str(owner_id)},
                    {"document_id": str(document_id)},
                ]
            },
            include=["metadatas"],
        )
        inactive_ids: list[str] = []
        for record_id, metadata in zip(
            records.get("ids", []),
            records.get("metadatas") or [],
            strict=True,
        ):
            generation = metadata.get("ingestion_generation") if metadata else None
            if active_ingestion_generation == LEGACY_INGESTION_GENERATION:
                is_active = generation is None
            elif active_ingestion_generation is None:
                is_active = False
            else:
                is_active = generation == str(active_ingestion_generation)
            if not is_active:
                inactive_ids.append(record_id)

        if inactive_ids:
            self._collection.delete(ids=inactive_ids)

    def _search_sync(
        self,
        owner_id: UUID,
        active_ingestion_generations: dict[UUID, UUID],
        query_embedding: list[float],
        limit: int,
    ) -> tuple[VectorSearchResult, ...]:
        if not active_ingestion_generations:
            return ()

        generated = [
            str(generation)
            for generation in active_ingestion_generations.values()
            if generation != LEGACY_INGESTION_GENERATION
        ]
        legacy_documents = [
            str(document_id)
            for document_id, generation in active_ingestion_generations.items()
            if generation == LEGACY_INGESTION_GENERATION
        ]

        results: list[VectorSearchResult] = []
        if generated:
            result = self._query_collection(
                query_embedding=query_embedding,
                limit=limit,
                where={
                    "$and": [
                        {"owner_id": str(owner_id)},
                        {"ingestion_generation": {"$in": generated}},
                    ]
                },
            )
            results.extend(
                self._convert_search_results(
                    result,
                    active_ingestion_generations,
                )
            )

        if legacy_documents:
            result = self._query_collection(
                query_embedding=query_embedding,
                limit=max(1, self._collection.count()),
                where={
                    "$and": [
                        {"owner_id": str(owner_id)},
                        {"document_id": {"$in": legacy_documents}},
                    ]
                },
            )
            results.extend(
                self._convert_search_results(
                    result,
                    active_ingestion_generations,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return tuple(results[:limit])

    def _query_collection(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        where: dict[str, Any],
    ) -> dict[str, Any]:
        count = self._collection.count()
        if count == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        return self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, count),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    @staticmethod
    def _convert_search_results(
        result: dict[str, Any],
        active_ingestion_generations: dict[UUID, UUID],
    ) -> list[VectorSearchResult]:

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        search_results: list[VectorSearchResult] = []

        for record_id, document, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
            strict=True,
        ):
            if document is None or metadata is None:
                continue

            document_id = UUID(metadata["document_id"])
            active_generation = active_ingestion_generations.get(document_id)
            record_generation = metadata.get("ingestion_generation")
            if active_generation == LEGACY_INGESTION_GENERATION:
                if record_generation is not None:
                    continue
            elif active_generation is None or record_generation != str(active_generation):
                continue

            page_number = metadata.get("page_number")

            search_results.append(
                VectorSearchResult(
                    id=record_id,
                    document_id=document_id,
                    chunk_index=int(metadata["chunk_index"]),
                    text=document,
                    page_number=(
                        int(page_number)
                        if page_number is not None
                        else None
                    ),
                    score=1.0 - float(distance),
                )
            )

        return search_results
