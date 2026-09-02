import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SearchItem = Type.Object({
	q: Type.String({ minLength: 1, maxLength: 1000 }),
	domains: Type.Optional(Type.Array(Type.String(), { maxItems: 20 })),
	exclude_domains: Type.Optional(Type.Array(Type.String(), { maxItems: 20 })),
	strategy: Type.Optional(Type.Union([Type.Literal("first"), Type.Literal("federated")])),
});

const ReferenceItem = Type.Object({
	ref_id: Type.String({ minLength: 1, maxLength: 8192 }),
	lineno: Type.Optional(Type.Integer({ minimum: 1 })),
});

const FindItem = Type.Object({
	ref_id: Type.String({ minLength: 1, maxLength: 8192 }),
	pattern: Type.String({ minLength: 1, maxLength: 500 }),
});

const ClickItem = Type.Object({
	ref_id: Type.String({ minLength: 1, maxLength: 8192 }),
	id: Type.Integer({ minimum: 1 }),
});

const LocalItem = Type.Object({
	q: Type.String({ minLength: 1, maxLength: 1000 }),
});

const ReplayItem = Type.Object({
	capture_id: Type.String({ minLength: 1, maxLength: 200 }),
});

const Parameters = Type.Object({
	search_query: Type.Optional(Type.Array(SearchItem, { minItems: 1, maxItems: 4 })),
	local_query: Type.Optional(Type.Array(LocalItem, { minItems: 1, maxItems: 4 })),
	open: Type.Optional(Type.Array(ReferenceItem, { minItems: 1, maxItems: 10 })),
	find: Type.Optional(Type.Array(FindItem, { minItems: 1, maxItems: 10 })),
	click: Type.Optional(Type.Array(ClickItem, { minItems: 1, maxItems: 10 })),
	replay: Type.Optional(Type.Array(ReplayItem, { minItems: 1, maxItems: 10 })),
	response_length: Type.Optional(
		Type.Union([Type.Literal("short"), Type.Literal("medium"), Type.Literal("long")]),
	),
	evidence: Type.Optional(
		Type.Union([Type.Literal("transient"), Type.Literal("index"), Type.Literal("capture")]),
	),
	profile: Type.Optional(Type.String({ minLength: 1, maxLength: 64 })),
});

type Pending = {
	resolve: (value: any) => void;
	reject: (reason: Error) => void;
	cleanup: () => void;
};

class AgencyWebClient {
	private child: ChildProcessWithoutNullStreams | null = null;
	private ready: Promise<void> | null = null;
	private nextId = 1;
	private output = "";
	private errors = "";
	private pending = new Map<number, Pending>();

	private start() {
		if (this.ready) return this.ready;
		this.child = spawn(
			process.env.WEB_RESEARCH_MCP_COMMAND || join(homedir(), ".local/bin/web-research-mcp"),
			[],
			{ stdio: ["pipe", "pipe", "pipe"] },
		);
		this.child.stdout.setEncoding("utf8");
		this.child.stderr.setEncoding("utf8");
		this.child.stdout.on("data", (chunk: string) => this.receive(chunk));
		this.child.stderr.on("data", (chunk: string) => {
			this.errors = `${this.errors}${chunk}`.slice(-4000);
		});
		this.child.on("error", (error) => this.fail(error));
		this.child.on("close", (status) => {
			this.fail(new Error(this.errors.trim() || `agency-web MCP exited with status ${status}`));
		});
		this.ready = this.request("initialize", {
			protocolVersion: "2025-06-18",
			capabilities: {},
			clientInfo: { name: "agency-pi", version: "1.0.0" },
		}).then(() => undefined);
		return this.ready;
	}

	private receive(chunk: string) {
		this.output += chunk;
		while (this.output.includes("\n")) {
			const separator = this.output.indexOf("\n");
			const line = this.output.slice(0, separator).trim();
			this.output = this.output.slice(separator + 1);
			if (!line) continue;
			let response: any;
			try {
				response = JSON.parse(line);
			} catch {
				this.fail(new Error("agency-web MCP returned invalid JSON"));
				continue;
			}
			const pending = this.pending.get(response.id);
			if (!pending) continue;
			this.pending.delete(response.id);
			pending.cleanup();
			if (response.error) pending.reject(new Error(String(response.error.message || "MCP error")));
			else pending.resolve(response.result);
		}
	}

	private fail(error: Error) {
		for (const pending of this.pending.values()) {
			pending.cleanup();
			pending.reject(error);
		}
		this.pending.clear();
		this.child = null;
		this.ready = null;
	}

	private request(method: string, params: unknown, signal?: AbortSignal) {
		const id = this.nextId++;
		return new Promise<any>((resolve, reject) => {
			const aborted = () => {
				this.pending.delete(id);
				reject(new Error("agency-web request aborted"));
			};
			const cleanup = () => signal?.removeEventListener("abort", aborted);
			if (signal?.aborted) {
				reject(new Error("agency-web request aborted"));
				return;
			}
			signal?.addEventListener("abort", aborted, { once: true });
			this.pending.set(id, { resolve, reject, cleanup });
			this.child?.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`, (error) => {
				if (!error) return;
				this.pending.delete(id);
				cleanup();
				reject(error);
			});
		});
	}

	async call(arguments_: unknown, signal?: AbortSignal) {
		await this.start();
		return this.request("tools/call", { name: "run", arguments: arguments_ }, signal);
	}

	close() {
		this.child?.kill();
		this.child = null;
		this.ready = null;
	}
}

export default function (pi: ExtensionAPI) {
	const client = new AgencyWebClient();
	pi.registerTool({
		name: "agency_web",
		label: "Agency Web",
		description:
			"Search and inspect the web with Agency's freshness-aware local Firefox stack. Prefer this for substantive, source-sensitive, authenticated, JavaScript-heavy, or audit-sensitive research. URL opens reuse fresh indexed text and refresh stale pages. Federated search returns stable references accepted by open; opened pages support find, numbered-link click, and citation-ready source metadata. Set evidence to index or capture for durable local evidence.",
		parameters: Parameters,
		async execute(_toolCallId, params, signal) {
			const result = await client.call(params, signal);
			if (result.isError) {
				throw new Error(result.content?.[0]?.text || "Agency web research failed");
			}
			return {
				content: result.content,
				details: result.structuredContent || {},
			};
		},
	});
	pi.on("session_shutdown", () => client.close());
}
