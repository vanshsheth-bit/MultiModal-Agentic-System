from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    tier = Column(String)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    storage_uri = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ocr_status = Column(String, nullable=False, default="not_needed")
    ocr_pages_total = Column(Integer, nullable=True)
    ocr_pages_done = Column(Integer, nullable=True)
    ocr_error = Column(Text, nullable=True)
    ocr_updated_at = Column(DateTime, nullable=True)


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    query_text = Column(Text)
    response = Column(Text)
    latency_ms = Column(Integer)
    sources_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    retrieval_confidence = Column(Float, nullable=True)
    retrieval_supports = Column(Integer, nullable=True)
    retrieval_hit = Column(Boolean, nullable=True)
    avg_vector_distance = Column(Float, nullable=True)
    grounded = Column(Boolean, nullable=True)
    hallucination_flag = Column(Boolean, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    estimated_cost_usd = Column(Float, nullable=True)


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True)
    total_queries = Column(Integer)
    total_documents = Column(Integer)
    avg_latency_ms = Column(Float)
    unique_users = Column(Integer)
