"""TRAFFICINTEL AI - Database Bootstrap Script

Creates clean relational tables and provisions the initial authorized administrator account.
Contains ZERO fake operational data, zero synthetic vehicles, zero fake cameras.
"""

from app.core.database import Base, engine, SessionLocal
from app.models.entities import User
from app.core.security import get_password_hash
from app.copilot.knowledge_rag import KnowledgeRAGEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trafficintel-init")


def init_db():
    logger.info("Creating clean database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Seed RAG standard engineering documents
        KnowledgeRAGEngine.seed_initial_standards(db)

        # Check if admin already exists
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            logger.info("Provisioning initial authorized system administrator (admin)...")
            admin_user = User(
                username="admin",
                email="admin@trafficintel.gov",
                hashed_password=get_password_hash("TrafficIntel2026!"),
                full_name="Chief Operations Administrator",
                role="ADMIN",
                is_active=True
            )
            db.add(admin_user)
            db.commit()
            logger.info("Administrator account created: admin / TrafficIntel2026!")
        else:
            logger.info("Administrator account already exists.")
    finally:
        db.close()

    logger.info("Clean database initialization complete. System ready for real integrations.")


if __name__ == "__main__":
    init_db()
