"""Qdrant grounding retriever (task 6.2, specs/generate).

Retrieves top-k Manim CE API snippets for a prompt from a Qdrant collection built from the
pinned version (task 6.1). Grounding is what pins the API surface: a prompt that would
elicit a ManimGL construct (e.g. ``ShowCreation``) should surface the CE equivalent
(``Create``) so the generator has the right form in front of it.

Uses qdrant-client's fastembed integration for local embeddings, so retrieval stays
sovereign — no embedding API call leaves the machine. The client and third-party imports
are lazy so a render-only deployment pulls in none of this.
"""

from __future__ import annotations

from ..version import MANIM_CE_VERSION


class QdrantGrounding:
    """`GroundingRetriever` adapter over a fastembed-backed Qdrant collection."""

    def __init__(
        self,
        url: str,
        collection: str,
        *,
        manim_version: str = MANIM_CE_VERSION,
    ) -> None:
        self._url = url
        self._collection = collection
        self._manim_version = manim_version
        self._client = None  # lazily connected on first retrieve

    def _connect(self):
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "grounding needs the 'generate' extra: "
                    "pip install manima-server[generate]"
                ) from exc
            self._client = QdrantClient(url=self._url)
        return self._client

    async def retrieve(self, prompt: str, k: int = 8) -> list[str]:
        """Top-k snippet texts for the prompt.

        qdrant-client's fastembed query is synchronous; it is run in a thread so it does
        not block the event loop while other jobs progress.
        """

        import anyio

        client = self._connect()

        def _query() -> list[str]:
            # `.query` embeds `query_text` locally via fastembed and searches. It filters
            # to the pinned version so a corpus rebuilt for a new version cannot leak old
            # snippets into a current generation.
            hits = client.query(
                collection_name=self._collection,
                query_text=prompt,
                limit=k,
                query_filter=_version_filter(self._manim_version),
            )
            return [h.document for h in hits if getattr(h, "document", None)]

        return await anyio.to_thread.run_sync(_query)


def _version_filter(manim_version: str):
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(
                key="manim_version",
                match=models.MatchValue(value=manim_version),
            )
        ]
    )
