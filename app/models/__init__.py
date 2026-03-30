from typing import Optional, Dict, Any
from pydantic import BaseModel


# Chat models
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    message_id: str
    role: str
    content: str
    metadata: Dict[str, Any] = {}
    created_at: str

