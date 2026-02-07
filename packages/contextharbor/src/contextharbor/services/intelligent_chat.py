from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .intelligent_tools import IntelligentToolLoop

logger = logging.getLogger(__name__)


class ChatReq(BaseModel):
    model_config = {"extra": "ignore"}
    messages: list[dict] = Field(description="Chat messages")
    model: str = Field(default="llama3.1:latest")
    options: Optional[dict] = Field(default=None)
    keep_alive: Optional[str] = Field(default=None)
    chat_id: Optional[str] = Field(default=None)
    message_id: Optional[str] = Field(default=None)
    use_intelligent_tools: bool = Field(default=True, description="Use intelligent tool-calling system")


class ChatStreamResp(BaseModel):
    type: str
    chat_id: str
    message_id: str
    content: str
    done: bool = False


async def stream_chat_intelligent(
    *,
    http,
    ollama_url: str,
    model: str,
    messages: list[dict],
    options: Optional[dict] = None,
    keep_alive: Optional[str] = None,
    embed_model: str,
    tool_registry,
    tool_executor,
    kiwix_url: Optional[str] = None,
    chat_id: str,
    message_id: str,
    max_cycles: int = 3,
) -> str:
    """
    Intelligent tool-calling that:
    1. Deciphers query intent and entities
    2. Builds context with current date
    3. Decides when to use tools
    4. Executes tools in a loop
    5. Checks sufficiency each round
    6. Provides grounded answers with citations
    """
    
    tool_loop = IntelligentToolLoop(max_cycles=max_cycles)
    
    logger.info(f"Starting intelligent tool loop for chat_id={chat_id}")
    
    try:
        result = await tool_loop.execute(
            http=http,
            ollama_url=ollama_url,
            model=model,
            messages=messages,
            options=options,
            keep_alive=keep_alive,
            embed_model=embed_model,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            kiwix_url=kiwix_url,
        )
        
        logger.info(f"Intelligent tool loop completed for chat_id={chat_id}")
        return result
        
    except Exception as e:
        logger.error(f"Intelligent tool loop failed for chat_id={chat_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Intelligent tool loop failed: {str(e)}")


def should_use_intelligent_tools(messages: list[dict], force_intelligent: bool = False) -> bool:
    """Determine if to use intelligent tool-calling based on message history."""
    
    if force_intelligent:
        return True
    
    # Check if there's evidence of inconsistent tool usage in recent messages
    for msg in messages[-3:]:  # Check last 3 messages
        if msg.get("role") == "assistant":
            content = msg.get("content", "").lower()
            
            # Signs of hallucination without tool usage
            if any(phrase in content for phrase in [
                "i don't have enough information",
                "i cannot access real-time",
                "i don't know the current",
                "as an ai, i don't have access",
            ]):
                return True  # Switch to intelligent tools to fix
                
            # Wrong date format (MM/DD/YYYY instead of Month DD, YYYY)
            if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', content):
                logger.warning(f"Detected wrong date format in response: {content}")
                return True
    
    return False  # Default to current behavior