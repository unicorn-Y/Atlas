-- Atlas fork: "关于你" fact layer. One row per version of a user fact; the
-- current value of a key is the row with status='active'. Older versions stay
-- as history (status='superseded') with superseded_by pointing at the newer row.
CREATE TABLE IF NOT EXISTS user_facts (
  id                 TEXT PRIMARY KEY,
  fact_key           TEXT NOT NULL,
  value              TEXT NOT NULL,
  text               TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'active',  -- active | superseded | retracted
  superseded_by      TEXT,
  evidence_quote     TEXT NOT NULL,
  evidence_trace_id  TEXT,
  episode_id         TEXT,
  session_id         TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_facts_key ON user_facts(fact_key, status);
CREATE INDEX IF NOT EXISTS idx_user_facts_status ON user_facts(status, updated_at);
