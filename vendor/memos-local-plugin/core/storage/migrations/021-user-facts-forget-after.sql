-- Atlas fork: temporary facts expire (Supermemory `forgetAfter` semantics).
-- NULL = permanent. Expired rows stay in history but are no longer injected.
ALTER TABLE user_facts ADD COLUMN forget_after INTEGER;
