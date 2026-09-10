-- Indexes for the agent activity log dashboard.
--
-- agent_events: the existing (agent_id, status, created_at) index cannot
-- serve "all events of an agent ordered by time", which is the main query
-- of the log screen.
-- message_threads: powers the "contacts today" KPI (threads of an agent
-- ordered by last activity).
CREATE INDEX IF NOT EXISTS agent_events_agent_id_created_at_idx
  ON public.agent_events (agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS message_threads_agent_id_last_message_at_idx
  ON public.message_threads (agent_id, last_message_at DESC);
