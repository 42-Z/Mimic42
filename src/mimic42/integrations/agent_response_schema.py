"""Structured output schema for the Mimic agent final response."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    """Schema that defines the structured final response of the agent.

    LangChain's ``create_agent`` uses this schema as ``response_format`` to force
    the model to return a validated object instead of free-form text.
    """

    text: str = Field(
        ...,
        description="The text content of the reply to send to the user.",
    )
    send_any_message: bool = Field(
        default=True,
        description=(
            "Whether the agent should send a message at all. "
            "Set to False to stay silent: the message does not require a reply, or "
            "the only thing to say is a report that an action or tool failed — "
            "technical failure reports are never sent to chats."
        ),
    )
    reply_to: int | None = Field(
        default=None,
        description=(
            "Telegram message ID to reply to. "
            "When set, the outgoing message will be sent as a reply to this specific message."
        ),
    )
