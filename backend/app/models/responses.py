from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    latency_ms: Optional[int] = None
    tool_confidence: Optional[Dict[str, Any]] = None
