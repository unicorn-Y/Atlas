/**
 * Atlas fork — "关于你" fact layer.
 *
 * After every turn the user's own message is read by the LLM, which proposes
 * key/value facts the user stated about themselves (home city, preferences,
 * family, project constraints …). The store keeps one active value per key
 * and the full history of earlier values, each with the user's verbatim quote
 * as evidence, so "后来改成周五" replaces the old value without losing it.
 *
 * Extraction rules are ported from Atlas MEMORY-V1 `observer_prompt.py`
 * (Mastra observer-agent assertion/question rules + Atlas Chinese rules,
 * verified 30/30 with zero misremembered facts in F3-A). The model only
 * proposes; a proposal is applied only if its quote really occurs in the
 * user's message.
 */

import { ids } from "../id.js";
import type { LlmClient } from "../llm/index.js";
import { rootLogger } from "../logger/index.js";
import type { Repos } from "../storage/repos/index.js";
import type { UserFactRow } from "../storage/repos/user_facts.js";

const log = rootLogger.child({ channel: "core.facts" });

const MAX_USER_CHARS = 4000;
const MAX_KNOWN_FACTS = 120;
const KEY_RE = /^[a-z0-9_]+(\.[a-z0-9_]+){0,4}$/;

export const FACTS_SYSTEM_PROMPT = `You maintain the long-term list of FACTS ABOUT THE USER for a personal assistant.
Read the user's latest message (the assistant's reply is context only) and propose changes to that list.

WHAT COUNTS AS A USER FACT
- Something the user TELLS you about themselves or their world: identity, where they live or work, family and people they know, possessions, health, habits, preferences and dislikes, ongoing projects and their constraints, decisions they have made, plans they will carry out themselves.
- USER ASSERTIONS ARE AUTHORITATIVE. The user is the source of truth about their own life.

WHAT IS NOT A USER FACT (never record these)
- Questions, information requests, requests for help, instructions for work happening now. Only a personal fact explicitly disclosed inside them counts: in "我女儿 6 岁了，她该上几年级？" record "用户的女儿 6 岁", not the grade question.
- Hypotheticals and conditionals ("如果/假如/假设我想……", "if I wanted to…") do not establish a plan, decision or preference.
- Conditions asked about in a question (e.g. asking whether a café has sockets) do not establish a preference or need.
- Assistant suggestions, search filters, examples.
- Text pasted from web pages, files or tool output: that is third-party content, not the user's own facts.
- Things the user says about other people's opinions are facts about those people only if the user asserts them.

CHANGES
- If the user changes something already known ("改成周五了", "我搬到上海了", "不用 SQLite 了，改用 PostgreSQL"), emit op "set" with the SAME key as the known fact and the new value. The old value is kept as history automatically.
- If the user says a known fact is no longer true and gives no replacement ("我已经不养猫了"), emit op "retract" for that key.
- If the message only repeats a known fact with the same value, emit nothing for it.

KEYS
- key is a short English dot-separated slug, lower case: user.home_city, user.employer, user.diet.allergy, user.family.daughter_age, user.preference.answer_style, project.atlas.test_policy, person.<name>.relation.
- REUSE the key of a known fact when the message is about the same attribute. One key = one attribute; a different attribute needs a different key.

OUTPUT
- value: the bare value, in the user's language ("杭州", "周五", "对花生过敏").
- text: one short sentence stating the fact in the user's language, written about "用户" (Chinese) or "User" (English), e.g. "用户住在杭州". Resolve relative dates ("明天", "下周三") to an actual date using the clock given below, and include it.
- quote: the exact span of the user's message that states the fact, copied character for character (no paraphrase, no translation). Proposals whose quote is not in the message are discarded.
- Return {"facts": []} when the message states no fact about the user. Most messages state none; do not invent.`;

const SCHEMA_HINT =
  '{"facts":[{"op":"set|retract","key":"user.home_city","value":"杭州","text":"用户住在杭州","quote":"我住在杭州"}]}';

interface FactProposal {
  op: "set" | "retract";
  key: string;
  value: string;
  text: string;
  quote: string;
}

export interface FactsObserveInput {
  userText: string;
  assistantText?: string;
  traceId?: string | null;
  episodeId?: string | null;
  sessionId?: string | null;
}

export interface FactsObserveResult {
  added: number;
  superseded: number;
  retracted: number;
  rejected: number;
}

export interface FactsObserverDeps {
  llm: LlmClient | null;
  repos: Pick<Repos, "userFacts">;
  now?: () => number;
  timeZone?: string;
}

export function createFactsObserver(deps: FactsObserverDeps) {
  const now = deps.now ?? (() => Date.now());
  const timeZone = deps.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  // Turns are applied strictly in order so a quick "改成周五" can never be
  // overtaken by the slower extraction of the earlier "周三".
  let chain: Promise<unknown> = Promise.resolve();

  async function observe(input: FactsObserveInput): Promise<FactsObserveResult> {
    const empty: FactsObserveResult = { added: 0, superseded: 0, retracted: 0, rejected: 0 };
    const userText = (input.userText ?? "").trim().slice(0, MAX_USER_CHARS);
    if (!deps.llm || userText.length < 2) return empty;

    const known = deps.repos.userFacts.listActive(MAX_KNOWN_FACTS);
    const knownBlock = known.length
      ? known.map((f) => `- ${f.factKey} = ${f.value}`).join("\n")
      : "(none yet)";
    const clock = new Intl.DateTimeFormat("zh-CN", {
      timeZone,
      dateStyle: "full",
      timeStyle: "short",
    }).format(new Date(now()));

    const payload = [
      `USER LOCAL CLOCK: ${clock} (${timeZone})`,
      `KNOWN USER FACTS (key = current value):\n${knownBlock}`,
      `ASSISTANT'S PREVIOUS REPLY (context only, never a source of user facts):\n${(input.assistantText ?? "").slice(0, 1500) || "(none)"}`,
      `USER MESSAGE:\n${userText}`,
    ].join("\n\n");

    let proposals: FactProposal[];
    try {
      const rsp = await deps.llm.completeJson<{ facts: unknown[] }>(
        [
          { role: "system", content: FACTS_SYSTEM_PROMPT },
          { role: "user", content: payload },
        ],
        {
          op: "atlas.user_facts.v1",
          phase: "facts",
          episodeId: input.episodeId ?? undefined,
          temperature: 0,
          malformedRetries: 1,
          schemaHint: SCHEMA_HINT,
          validate: (v): asserts v is { facts: unknown[] } => {
            if (!v || typeof v !== "object" || !Array.isArray((v as { facts?: unknown }).facts)) {
              throw new Error("user_facts: expected {facts: [...]}");
            }
          },
        },
      );
      proposals = rsp.value.facts.map(normaliseProposal).filter((p): p is FactProposal => !!p);
      empty.rejected = rsp.value.facts.length - proposals.length;
    } catch (err) {
      log.warn("facts.llm_failed", { err: err instanceof Error ? err.message : String(err) });
      return empty;
    }

    const result = { ...empty };
    const haystack = squash(userText);
    for (const p of proposals) {
      if (!haystack.includes(squash(p.quote))) {
        result.rejected++;
        log.info("facts.rejected_quote", { key: p.key, quote: p.quote });
        continue;
      }
      const ts = now();
      const current = deps.repos.userFacts.activeByKey(p.key);
      if (p.op === "retract") {
        for (const row of current) deps.repos.userFacts.markRetracted(row.id, ts);
        result.retracted += current.length;
        continue;
      }
      if (current.some((row) => squash(row.value) === squash(p.value))) continue;
      const row: UserFactRow = {
        id: `uf_${ids.span()}`,
        factKey: p.key,
        value: p.value,
        text: p.text,
        status: "active",
        supersededBy: null,
        evidenceQuote: p.quote,
        evidenceTraceId: input.traceId ?? null,
        episodeId: input.episodeId ?? null,
        sessionId: input.sessionId ?? null,
        createdAt: ts,
        updatedAt: ts,
      };
      deps.repos.userFacts.insert(row);
      for (const old of current) deps.repos.userFacts.markSuperseded(old.id, row.id, ts);
      result.added++;
      result.superseded += current.length;
    }
    if (result.added || result.retracted || result.rejected) {
      log.info("facts.applied", { ...result });
    }
    return result;
  }

  return {
    /** Queue one turn; resolves after it (and every earlier turn) is applied. */
    observeTurn(input: FactsObserveInput): Promise<FactsObserveResult> {
      const next = chain.then(() => observe(input));
      chain = next.catch(() => undefined);
      return next;
    },
  };
}

export type FactsObserver = ReturnType<typeof createFactsObserver>;

/** Render the active facts as the "关于用户" block injected every turn. */
export function renderUserFacts(rows: readonly UserFactRow[], timeZone?: string): string {
  if (rows.length === 0) return "";
  const day = new Intl.DateTimeFormat("sv-SE", { timeZone, dateStyle: "short" });
  const lines = rows.map((f) => `- ${f.text}（${day.format(new Date(f.updatedAt))} 起）`);
  return [
    "## About the user (facts the user stated; newest value wins)",
    "Use these directly. When the user corrects one, the correction replaces it.",
    ...lines,
  ].join("\n");
}

function normaliseProposal(raw: unknown): FactProposal | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const op = o.op === "retract" ? "retract" : o.op === "set" ? "set" : null;
  const key = typeof o.key === "string" ? o.key.trim().toLowerCase() : "";
  const value = typeof o.value === "string" ? o.value.trim() : "";
  const text = typeof o.text === "string" ? o.text.trim() : "";
  const quote = typeof o.quote === "string" ? o.quote.trim() : "";
  if (!op || !KEY_RE.test(key) || !quote) return null;
  if (op === "set" && (!value || !text || value.length > 300 || text.length > 400)) return null;
  return { op, key, value, text, quote };
}

/** Whitespace/quote-insensitive form used to compare quotes and values. */
function squash(s: string): string {
  return s
    .normalize("NFKC")
    .replace(/[\s"'“”‘’「」『』]/g, "")
    .toLowerCase();
}
