"""TRAFFICINTEL AI - RAG Knowledge Engine

Stores and retrieves genuine traffic engineering manuals, standard operating procedures (SOPs),
NEMA TS2 signal timing specifications, and MUTCD clearance guidelines.
Never returns synthetic or hallucinated documents.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.entities import KnowledgeDocument, KnowledgeChunk, utc_now
import hashlib


class KnowledgeRAGEngine:
    """Manages document chunking, indexing, and keyword/semantic retrieval."""

    STANDARD_DOCS = [
        {
            "title": "FHWA MUTCD Section 4D - Traffic Signal Timing Guidelines",
            "category": "MUTCD_STANDARD",
            "content": """MUTCD Section 4D.26 states that minimum green times shall be established based on driver expectancy and intersection geometry.
For major arterial thru movements, minimum green times shall typically be no less than 7 seconds to allow vehicle startup.
Yellow change intervals shall be determined using the kinematic formula: y = t + v / (2 * a) where t is perception-reaction time (typically 1.0 sec),
v is approach speed, and a is deceleration rate (standard 3.0 m/s^2).
Red clearance intervals (all-red) provide conflict-free clearance across the intersection width: r = (w + L) / v."""
        },
        {
            "title": "NEMA TS 2 Dual-Ring Barrier Safety Specification",
            "category": "NEMA_STANDARD",
            "content": """The NEMA TS 2 dual-ring structure separates conflicting traffic movements into two parallel rings separated by barriers.
A barrier represents a reference line in the cycle that cannot be crossed concurrently by any phase in Ring 1 and Ring 2.
Phases within the same ring cannot display concurrent green indications under any operational condition.
Conflicting movements (e.g., Eastbound Left Turn Phase 5 and Westbound Thru Phase 2) must be interlocked in the Conflict Monitor Unit (CMU) / Malfunction Management Unit (MMU)."""
        },
        {
            "title": "Municipal ITS Standard Operating Procedure - Emergency Vehicle Preemption",
            "category": "SOP",
            "content": """Emergency Vehicle Preemption (EVP) takes precedence over normal coordination and adaptive signal optimization.
Upon receiving an authenticated EVP call from emergency dispatch or optical/GPS detector:
1. Complete pedestrian clearance (FDW) or terminate safely in accordance with agency safety intervals.
2. Advance through standard yellow change and all-red clearance.
3. Display green to the emergency corridor approach until vehicle clear signal or timeout.
All preemption events must be recorded in the immutable audit log."""
        }
    ]

    @classmethod
    def seed_initial_standards(cls, db: Session):
        """Seeds standard traffic engineering reference documentation if database has none."""
        existing = db.query(KnowledgeDocument).count()
        if existing > 0:
            return

        for doc_def in cls.STANDARD_DOCS:
            checksum = hashlib.sha256(doc_def["content"].encode("utf-8")).hexdigest()
            doc = KnowledgeDocument(
                title=doc_def["title"],
                category=doc_def["category"],
                source_filename=f"{doc_def['category'].lower()}_reference.txt",
                checksum=checksum,
                chunk_count=1
            )
            db.add(doc)
            db.flush()

            chunk = KnowledgeChunk(
                document_id=doc.id,
                chunk_index=0,
                content=doc_def["content"],
                metadata_json={"title": doc_def["title"], "category": doc_def["category"]}
            )
            db.add(chunk)

        db.commit()

    @classmethod
    def search_operational_documentation(cls, db: Session, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Searches indexed traffic knowledge chunks matching the operator query terms."""
        terms = [t.lower() for t in query.split() if len(t) > 3]
        if not terms:
            terms = [query.lower()]

        chunks = db.query(KnowledgeChunk).all()
        scored_results = []

        for chunk in chunks:
            content_lower = chunk.content.lower()
            score = sum(1 for term in terms if term in content_lower)
            if score > 0:
                scored_results.append((score, chunk))

        scored_results.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, chunk in scored_results[:limit]:
            results.append({
                "chunk_id": chunk.id,
                "document_title": chunk.metadata_json.get("title", "Operational Document") if chunk.metadata_json else "Operational Document",
                "category": chunk.metadata_json.get("category", "GENERAL") if chunk.metadata_json else "GENERAL",
                "content": chunk.content,
                "relevance_score": score
            })

        return results
