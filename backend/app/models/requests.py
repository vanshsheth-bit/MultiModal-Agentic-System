from typing import List, Optional

from pydantic import BaseModel


class TextQueryRequest(BaseModel):
    query: str
    doc_ids: Optional[List[int]] = None
    source_filter: Optional[str] = None
    content_type_filter: Optional[str] = None
    stream: bool = False
