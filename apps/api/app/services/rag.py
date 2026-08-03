from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..models import KnowledgeChunk, KnowledgeDocument

TOKEN_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(value) if len(token) > 1]


def hashed_embedding(value: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(value):
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1 if digest[4] & 1 else -1
    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(x * y for x, y in zip(left, right))


def chunk_text(content: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = (current[-overlap:] + "\n" + paragraph).strip() if current else paragraph
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars - overlap :]
    if current:
        chunks.append(current)
    return chunks or [content[:max_chars]]


def index_document(db: Session, document: KnowledgeDocument) -> int:
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete()
    chunks = chunk_text(document.content)
    chunk_objects: list[KnowledgeChunk] = []
    for index, content in enumerate(chunks):
        chunk = KnowledgeChunk(
            document_id=document.id,
            chunk_index=index,
            content=content,
            embedding_json=hashed_embedding(content),
            metadata_json={
                "document_type": document.document_type,
                "title": document.title,
                "property_id": document.property_id,
                "project_id": document.project_id,
                "verified": document.verified,
            },
        )
        db.add(chunk)
        chunk_objects.append(chunk)
    db.flush()

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        update_embedding = text(
            "UPDATE knowledge_chunks "
            "SET embedding = CAST(:embedding AS vector) "
            "WHERE id = :id"
        )
        for chunk in chunk_objects:
            vector_text = "[" + ",".join(f"{value:.8f}" for value in (chunk.embedding_json or [])) + "]"
            db.execute(update_embedding, {"embedding": vector_text, "id": chunk.id})
    return len(chunks)


def retrieve(
    db: Session,
    query: str,
    *,
    property_id: str | None = None,
    project_id: str | None = None,
    verified_only: bool = True,
    limit: int = 5,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        vector_text = "[" + ",".join(f"{value:.8f}" for value in hashed_embedding(query)) + "]"
        params: dict[str, Any] = {
            "embedding": vector_text,
            "limit": limit,
            "verified_only": verified_only,
            "property_id": property_id,
            "project_id": project_id,
        }
        sql = text(
            "SELECT kc.content, kd.id AS document_id, kd.title, kd.document_type, "
            "kd.source_url, kd.property_id, kd.verified, "
            "1 - (kc.embedding <=> CAST(:embedding AS vector)) AS score "
            "FROM knowledge_chunks kc "
            "JOIN knowledge_documents kd ON kd.id = kc.document_id "
            "WHERE kc.embedding IS NOT NULL "
            "AND (NOT :verified_only OR kd.verified = TRUE) "
            "AND (:property_id IS NULL OR kd.property_id = :property_id OR kd.property_id IS NULL) "
            "AND (:project_id IS NULL OR kd.project_id = :project_id OR kd.project_id IS NULL) "
            "AND (kd.valid_from IS NULL OR kd.valid_from <= NOW()) "
            "AND (kd.valid_until IS NULL OR kd.valid_until >= NOW()) "
            "ORDER BY kc.embedding <=> CAST(:embedding AS vector) "
            "LIMIT :limit"
        )
        rows = db.execute(sql, params).mappings().all()
        return [
            {
                "score": round(float(row["score"]), 4),
                "content": row["content"],
                "document_id": row["document_id"],
                "title": row["title"],
                "document_type": row["document_type"],
                "source_url": row["source_url"],
                "property_id": row["property_id"],
                "verified": row["verified"],
            }
            for row in rows
        ]

    stmt = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument,
        KnowledgeChunk.document_id == KnowledgeDocument.id,
    )
    conditions = []
    if verified_only:
        conditions.append(KnowledgeDocument.verified.is_(True))
    if property_id:
        conditions.append(
            or_(KnowledgeDocument.property_id == property_id, KnowledgeDocument.property_id.is_(None))
        )
    if project_id:
        conditions.append(
            or_(KnowledgeDocument.project_id == project_id, KnowledgeDocument.project_id.is_(None))
        )
    if conditions:
        stmt = stmt.where(*conditions)

    rows = db.execute(stmt).all()
    query_vector = hashed_embedding(query)
    query_tokens = set(tokenize(query))
    scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
    for chunk, document in rows:
        valid_from = document.valid_from
        valid_until = document.valid_until
        if valid_from and (
            valid_from if valid_from.tzinfo else valid_from.replace(tzinfo=timezone.utc)
        ) > now:
            continue
        if valid_until and (
            valid_until if valid_until.tzinfo else valid_until.replace(tzinfo=timezone.utc)
        ) < now:
            continue
        vector_score = cosine(query_vector, chunk.embedding_json or [])
        chunk_tokens = set(tokenize(chunk.content))
        keyword_score = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
        score = 0.7 * vector_score + 0.3 * keyword_score
        if score > 0:
            scored.append((score, chunk, document))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 4),
            "content": chunk.content,
            "document_id": document.id,
            "title": document.title,
            "document_type": document.document_type,
            "source_url": document.source_url,
            "property_id": document.property_id,
            "verified": document.verified,
        }
        for score, chunk, document in scored[:limit]
    ]
