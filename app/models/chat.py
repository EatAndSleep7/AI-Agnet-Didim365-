from typing import Optional
from pydantic import BaseModel, ConfigDict
from uuid import UUID


class ChatRequest(BaseModel):
    thread_id: UUID
    message: str


class ResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_name: Optional[str] = None
    execution_time_ms: Optional[int] = None


class ChatResponse(BaseModel):
    message_id: str
    content: str
    metadata: ResponseMetadata
