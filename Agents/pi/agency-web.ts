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
	private static readonly limits = {
		requestBytes: 64 * 1024,
		responseBytes: 4 * 1024 * 1024,
		pendingRequests: 16,
		requestDeadlineMs: 180_000,
		shutdownGraceMs: 5_000,
		diagnosticCharacters: 4000,
	};

	private child: ChildProcessWithoutNullStreams | null = null;
	private ready: Promise<void> | null = null;
	private closing: Promise<void> | null = null;
	private generation = 0;
	private closed = false;
	private nextId = 1;
	private outputParts: string[] = [];
	private outputBytes = 0;
	private errors = "";
	private pending = new Map<number, Pending>();

	private start() {
		if (this.closed) return Promise.reject(new Error("agency-web client closed"));
		if (this.ready) return this.ready;
		const ready = this.launch();
		this.ready = ready;
		void ready.catch(error => { if (this.ready === ready) this.fail(error); });
		return ready;
	}

	private async launch() {
		const generation = this.generation;
		await this.closing;
		if (this.closed || generation !== this.generation) throw new Error("agency-web client closed during startup");
		this.outputParts = [];
		this.outputBytes = 0;
		this.errors = "";
		const child = spawn(
			process.env.WEB_RESEARCH_MCP_COMMAND || join(homedir(), ".local/bin/web-research-mcp"),
			[],
			{ stdio: ["pipe", "pipe", "pipe"] },
		);
		this.child = child;
		child.stdout.setEncoding("utf8");
		child.stderr.setEncoding("utf8");
		child.stdout.on("data", (chunk: string) => {
			if (this.child === child) this.receive(chunk);
		});
		child.stderr.on("data", (chunk: string) => {
			if (this.child === child) this.errors = `${this.errors}${chunk}`.slice(-AgencyWebClient.limits.diagnosticCharacters);
		});
		child.on("error", (error) => { if (this.child === child) this.fail(error); });
		child.on("close", (status) => {
			if (this.child === child) this.fail(new Error(this.errors.trim() || `agency-web MCP exited with status ${status}`), true);
		});
		await this.request("initialize", {
			protocolVersion: "2025-06-18",
			capabilities: {},
			clientInfo: { name: "agency-pi", version: "1.0.0" },
		});
	}

	private receive(chunk: string) {
		let start = 0;
		while (start < chunk.length) {
			const separator = chunk.indexOf("\n", start);
			const end = separator < 0 ? chunk.length : separator;
			const part = chunk.slice(start, end);
			this.outputBytes += Buffer.byteLength(part);
			if (this.outputBytes > AgencyWebClient.limits.responseBytes) {
				this.fail(new Error("agency-web MCP response exceeds 4 MiB"));
				return;
			}
			this.outputParts.push(part);
			if (separator < 0) break;
			const line = this.outputParts.join("").trim();
			this.outputParts = [];
			this.outputBytes = 0;
			start = separator + 1;
			if (!line) continue;
			let response: any;
			try { response = JSON.parse(line); }
			catch {
				this.fail(new Error("agency-web MCP returned invalid JSON"));
				return;
			}
			const pending = this.pending.get(response.id);
			if (!pending) continue;
			this.pending.delete(response.id);
			pending.cleanup();
			if (response.error) pending.reject(new Error(String(response.error.message || "MCP error")));
			else pending.resolve(response.result);
		}
	}

	private retireChild() {
		const child = this.child;
		this.child = null;
		this.ready = null;
		if (!child) return;
		let complete: () => void;
		const closing = new Promise<void>(resolve => { complete = resolve; });
		this.closing = closing;
		const timer = setTimeout(() => child.kill("SIGKILL"), AgencyWebClient.limits.shutdownGraceMs);
		child.once("close", () => {
			clearTimeout(timer);
			if (this.closing === closing) this.closing = null;
			complete();
		});
		child.kill("SIGTERM");
	}

	private fail(error: Error, closed = false) {
		this.generation += 1;
		for (const pending of this.pending.values()) {
			pending.cleanup();
			pending.reject(error);
		}
		this.pending.clear();
		this.outputParts = [];
		this.outputBytes = 0;
		if (closed) { this.child = null; this.ready = null; }
		else this.retireChild();
	}

	private request(method: string, params: unknown, signal?: AbortSignal) {
		if (this.pending.size >= AgencyWebClient.limits.pendingRequests) return Promise.reject(new Error("agency-web request queue is full"));
		const frame = `${JSON.stringify({ jsonrpc: "2.0", id: this.nextId, method, params })}\n`;
		if (Buffer.byteLength(frame) > AgencyWebClient.limits.requestBytes) return Promise.reject(new Error("agency-web request exceeds 64 KiB"));
		const id = this.nextId++;
		return new Promise<any>((resolve, reject) => {
			const aborted = () => {
				this.fail(new Error("agency-web request aborted"));
			};
			const timer = setTimeout(() => {
				this.fail(new Error("agency-web request deadline exceeded"));
			}, AgencyWebClient.limits.requestDeadlineMs);
			const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", aborted); };
			if (signal?.aborted) {
				cleanup();
				reject(new Error("agency-web request aborted"));
				return;
			}
			signal?.addEventListener("abort", aborted, { once: true });
			this.pending.set(id, { resolve, reject, cleanup });
			this.child?.stdin.write(frame, (error) => {
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
		this.closed = true;
		this.fail(new Error("agency-web client closed"));
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
