import logging
import uuid
from typing import List

from qdrant_client.models import PointStruct
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.services.embeddings.jina import jina_service
from src.services.indexing.chunker import text_chunker
from src.services.qdrant.client import qdrant_service

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # embed 10 chunks at a time


class IndexingPipeline:
    """Orchestrates chunking, embedding and storing in Qdrant."""

    async def index_paper(self, arxiv_id: str, raw_text: str, metadata: dict) -> int:
        """
        Index a single paper into Qdrant.

        Args:
            arxiv_id: Paper ID
            raw_text: Full extracted text
            metadata: Paper metadata (title, authors, etc.)

        Returns:
            Number of chunks indexed
        """
        # step 1 — chunk
        chunks = text_chunker.chunk_text(raw_text, arxiv_id)
        if not chunks:
            logger.warning(f"No chunks generated for {arxiv_id}")
            return 0

        # step 2 — embed in batches
        points = []
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]

            embeddings = await jina_service.embed(texts)

            for chunk, embedding in zip(batch, embeddings):
                point = PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "arxiv_id": arxiv_id,
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["text"],
                        "title": metadata.get("title", ""),
                        "authors": metadata.get("authors", []),
                        "categories": metadata.get("categories", []),
                        "published_date": metadata.get("published_date", ""),
                        "pdf_url": metadata.get("pdf_url", ""),
                    },
                )
                points.append(point)

        # step 3 — store in Qdrant
        qdrant_service.client.upsert(
            collection_name=qdrant_service.collection_name,
            points=points,
        )

        logger.info(f"Indexed {len(points)} chunks for {arxiv_id}")
        return len(points)

    async def index_all_unembedded(self, session: Session) -> dict:
        """
        Index all papers that have not been embedded yet.

        Args:
            session: Database session

        Returns:
            Summary of indexing results
        """
        # fetch unembedded papers with raw text
        rows = session.execute(
            text("""
                SELECT arxiv_id, title, authors, categories,
                       published_date, pdf_url, raw_text
                FROM papers
                WHERE is_embedded = false
                AND raw_text IS NOT NULL
            """)
        ).fetchall()

        if not rows:
            logger.info("No unembedded papers found")
            return {"indexed": 0, "skipped": 0}

        indexed = 0
        skipped = 0

        for row in rows:
            try:
                count = await self.index_paper(
                    arxiv_id=row.arxiv_id,
                    raw_text=row.raw_text,
                    metadata={
                        "title": row.title,
                        "authors": row.authors,
                        "categories": row.categories,
                        "published_date": str(row.published_date),
                        "pdf_url": row.pdf_url,
                    },
                )

                # mark as embedded in postgres
                session.execute(
                    text("UPDATE papers SET is_embedded = true WHERE arxiv_id = :arxiv_id"),
                    {"arxiv_id": row.arxiv_id},
                )
                session.commit()
                indexed += 1
                logger.info(f"Indexed {row.arxiv_id} ({count} chunks)")

            except Exception as e:
                logger.error(f"Failed to index {row.arxiv_id}: {e}")
                skipped += 1

        return {"indexed": indexed, "skipped": skipped}


indexing_pipeline = IndexingPipeline()
