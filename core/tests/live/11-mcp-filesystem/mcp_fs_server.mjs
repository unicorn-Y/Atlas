// Minimal MCP stdio "filesystem" server for live scenario 11 (taskbook §12.2).
// Exposes one read-only tool, read_file, sandboxed to the directory given as
// argv[1]. Built on the worktree's local @modelcontextprotocol/sdk so the
// scenario needs no network download. Test fixture only — not product code.
import fs from "node:fs";
import path from "node:path";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const root = path.resolve(process.argv[2] || ".");
const server = new McpServer({ name: "atlas-live-fs", version: "1.0.0" });

server.tool(
  "read_file",
  "读取沙箱目录内的一个文本文件（MCP filesystem 工具）",
  { path: z.string().describe("沙箱内的相对路径，例如 vault.txt") },
  async ({ path: relative }) => {
    const target = path.resolve(root, relative);
    if (!target.startsWith(root + path.sep) && target !== root) {
      return { content: [{ type: "text", text: "路径越出沙箱。" }] };
    }
    try {
      const text = fs.readFileSync(target, "utf-8");
      return { content: [{ type: "text", text }] };
    } catch (error) {
      return { content: [{ type: "text", text: `读取失败：${String(error)}` }] };
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
