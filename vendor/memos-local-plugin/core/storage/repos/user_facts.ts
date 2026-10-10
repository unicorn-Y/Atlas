/**
 * Atlas fork — repo for the `user_facts` table (migration 020).
 *
 * A fact key (e.g. `user.home_city`) has at most one `active` row; changing
 * the value inserts a new row and marks the previous one `superseded`, so the
 * history of "以前住哪 / 现在住哪" is kept with the original quote as evidence.
 */

import type { StorageDb } from "../types.js";
import { buildInsert } from "../tx.js";

export type UserFactStatus = "active" | "superseded" | "retracted";

export interface UserFactRow {
  id: string;
  factKey: string;
  value: string;
  text: string;
  status: UserFactStatus;
  supersededBy: string | null;
  evidenceQuote: string;
  evidenceTraceId: string | null;
  episodeId: string | null;
  sessionId: string | null;
  createdAt: number;
  updatedAt: number;
}

interface RawUserFactRow {
  id: string;
  fact_key: string;
  value: string;
  text: string;
  status: string;
  superseded_by: string | null;
  evidence_quote: string;
  evidence_trace_id: string | null;
  episode_id: string | null;
  session_id: string | null;
  created_at: number;
  updated_at: number;
}

const COLUMNS = [
  "id",
  "fact_key",
  "value",
  "text",
  "status",
  "superseded_by",
  "evidence_quote",
  "evidence_trace_id",
  "episode_id",
  "session_id",
  "created_at",
  "updated_at",
];
const SELECT = `SELECT ${COLUMNS.join(", ")} FROM user_facts`;

export function makeUserFactsRepo(db: StorageDb) {
  const insert = db.prepare(buildInsert({ table: "user_facts", columns: COLUMNS }));
  const selectById = db.prepare<{ id: string }, RawUserFactRow>(`${SELECT} WHERE id=@id`);
  const selectActiveByKey = db.prepare<{ key: string }, RawUserFactRow>(
    `${SELECT} WHERE fact_key=@key AND status='active' ORDER BY updated_at DESC`,
  );
  const selectActive = db.prepare<{ limit: number }, RawUserFactRow>(
    `${SELECT} WHERE status='active' ORDER BY updated_at DESC LIMIT @limit`,
  );
  const selectAll = db.prepare<{ limit: number }, RawUserFactRow>(
    `${SELECT} ORDER BY updated_at DESC LIMIT @limit`,
  );
  const setStatus = db.prepare<{ id: string; status: string; by: string | null; ts: number }>(
    `UPDATE user_facts SET status=@status, superseded_by=@by, updated_at=@ts WHERE id=@id`,
  );
  const deleteById = db.prepare<{ id: string }>(`DELETE FROM user_facts WHERE id=@id`);

  return {
    insert(row: UserFactRow): void {
      insert.run({
        id: row.id,
        fact_key: row.factKey,
        value: row.value,
        text: row.text,
        status: row.status,
        superseded_by: row.supersededBy,
        evidence_quote: row.evidenceQuote,
        evidence_trace_id: row.evidenceTraceId,
        episode_id: row.episodeId,
        session_id: row.sessionId,
        created_at: row.createdAt,
        updated_at: row.updatedAt,
      });
    },
    getById(id: string): UserFactRow | null {
      const r = selectById.get({ id });
      return r ? mapRow(r) : null;
    },
    activeByKey(key: string): UserFactRow[] {
      return selectActiveByKey.all({ key }).map(mapRow);
    },
    listActive(limit = 200): UserFactRow[] {
      return selectActive.all({ limit }).map(mapRow);
    },
    listAll(limit = 500): UserFactRow[] {
      return selectAll.all({ limit }).map(mapRow);
    },
    markSuperseded(id: string, by: string, ts: number): void {
      setStatus.run({ id, status: "superseded", by, ts });
    },
    markRetracted(id: string, ts: number): void {
      setStatus.run({ id, status: "retracted", by: null, ts });
    },
    deleteById(id: string): boolean {
      return deleteById.run({ id }).changes > 0;
    },
  };
}

function mapRow(r: RawUserFactRow): UserFactRow {
  return {
    id: r.id,
    factKey: r.fact_key,
    value: r.value,
    text: r.text,
    status: r.status as UserFactStatus,
    supersededBy: r.superseded_by,
    evidenceQuote: r.evidence_quote,
    evidenceTraceId: r.evidence_trace_id,
    episodeId: r.episode_id,
    sessionId: r.session_id,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
  };
}
