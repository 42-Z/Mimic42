-- Allow empty content for assistant messages with structured output
-- where the text is stored in payload.structured_response instead.
ALTER TABLE public.agent_messages
DROP CONSTRAINT IF EXISTS agent_messages_content_not_blank;
