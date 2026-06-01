-- Allow multiple onboarding sessions per user by removing the unique constraint on owner_id.
-- This enables users to create multiple agents through the onboarding flow.

ALTER TABLE public.agent_onboarding_sessions
DROP CONSTRAINT IF EXISTS agent_onboarding_sessions_owner_id_key;
