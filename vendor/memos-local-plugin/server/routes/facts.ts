/**
 * Atlas fork — "关于你" facts.
 *
 *   GET    /api/v1/facts?history=1&limit=500   current facts (+ old versions with history=1)
 *   DELETE /api/v1/facts/:id                    hard delete one version
 */

import type { ServerDeps } from "../types.js";
import { writeError, type Routes } from "./registry.js";

export function registerFactsRoutes(routes: Routes, deps: ServerDeps): void {
  routes.set("GET /api/v1/facts", async (ctx) => {
    if (!deps.core.listUserFacts) {
      writeError(ctx, 501, "unsupported", "user facts are not available in this core");
      return;
    }
    const history = ctx.url.searchParams.get("history");
    const limit = Number(ctx.url.searchParams.get("limit") ?? "500");
    const facts = await deps.core.listUserFacts({
      includeHistory: history === "1" || history === "true",
      limit: Number.isFinite(limit) ? limit : 500,
    });
    return { facts };
  });

  routes.setPattern("DELETE /api/v1/facts/:id", async (ctx) => {
    const id = ctx.params.id;
    if (!id) {
      writeError(ctx, 400, "invalid_argument", "id is required");
      return;
    }
    if (!deps.core.deleteUserFact) {
      writeError(ctx, 501, "unsupported", "user facts are not available in this core");
      return;
    }
    return await deps.core.deleteUserFact(id);
  });
}
