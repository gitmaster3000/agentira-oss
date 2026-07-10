/**
 * Agentira — data contract for the redesigned UI.
 *
 * These interfaces mirror the JSON returned by `src/api.js`. They are the
 * single seam between the hi-fi prototype (Agentira.dc.html) and the real
 * React app: every component takes one of these as a prop, so you can render
 * with mock data today and swap in the live `api` calls when ready.
 *
 * Endpoint references below point at the exact `api.js` method that returns
 * each shape, so wiring is mechanical.
 */

// ─── Primitives ───────────────────────────────────────────────────────────
export type ID = string;
export type ISODate = string; // e.g. "2026-06-12T09:00:00Z"

export type TaskStatus = 'backlog' | 'todo' | 'in_progress' | 'review' | 'done';
export type Priority = 'low' | 'medium' | 'high' | 'critical';
export type AgentStatus = 'running' | 'online' | 'offline';
export type RunStatus =
  | 'pending' | 'ready' | 'running' | 'paused'
  | 'completed' | 'failed' | 'cancelled';
export type MemberKind = 'human' | 'agent' | 'service account';

// ─── Project ──────────────────────────────────────────────────────────────
// GET /projects                → Project[]      api.getProjects()
// GET /projects/:id            → Project        api.getProject(id)
export interface Project {
  id: ID;
  name: string;
  key: string;                // "ACM" — task-key prefix
  color: string;              // hex accent, owned by the UI theme map
  description: string;
  repo: string;               // primary repo slug "acme/web"
  workspaceKind: 'git' | 'local_folder' | 'sandbox';
  sandboxMode: 'off' | 'cwd' | 'strict' | 'container';
  envIsolation: 'auto' | 'hermetic' | 'per_run_db' | 'per_run_compose'; // AP-308
  liveRuns: number;           // count of RUNNING runs (for the sidebar dot)
  needsAttention: number;     // count waiting on the user
  counts: Record<TaskStatus, number>; // board distribution → Overview + Roadmap
}

// ─── Board / Task ─────────────────────────────────────────────────────────
// GET /projects/:id/board      → BoardColumn[]  api.getBoard(projectId)
export interface BoardColumn {
  id: TaskStatus;
  label: string;              // editable in Board settings
  color: string;
  wipLimit?: number;
  role?: AgentRole;           // which agent role this column dispatches
  autoDispatch: boolean;
  gates: GateId[];            // evidence gates blocking exit
  tasks: Task[];
}

// GET /tasks/:id               → Task            api.getTask(id)
// PATCH /tasks/:id             → Task            api.updateTask(id, data)
// POST /tasks/:id/move         → Task            api.moveTask(id, status)
export interface Task {
  id: ID;
  key: string;                // "ACM-142"
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  epicId?: ID;
  assignee?: MemberRef;
  reviewer?: MemberRef;
  estimatePts?: number;
  labels: string[];
  dod: DodItem[];             // definition of done
  branch?: string;
  pr?: { url: string; number: string; state: 'draft' | 'open' | 'merged' };
  liveRunId?: ID;             // set ⇢ "agent working" badge + drawer glow
  needsAttention?: boolean;
}
export interface DodItem { text: string; done: boolean; }

// ─── Epic ─────────────────────────────────────────────────────────────────
// GET /epics?project_id=:id    → Epic[]          api.getEpics(projectId)
// GET /epics/:id/tasks         → Task[]          api.getEpicTasks(id)
export interface Epic {
  id: ID;
  name: string;
  color: string;
  description: string;
  done: number;
  total: number;
  // Roadmap gantt positioning (derived from task start/due dates):
  start: ISODate;
  due: ISODate;
  dependsOn?: ID[];           // dependency arrows
}

// ─── Members / Profiles ───────────────────────────────────────────────────
// GET /projects/:id/members    → Member[]        api.getProjectMembers(id)
// GET /profiles/me             → Member          api.getMe()
export interface Member {
  id: ID;
  name: string;
  handle: string;
  role: 'admin' | 'member' | 'service account';
  kind: MemberKind;
  initials: string;
  color: string;
  agentId?: ID;               // present when kind === 'agent' → links to Agent
}
export type MemberRef = Pick<Member, 'id' | 'name' | 'initials' | 'color'>;

// ─── Agents (Forge) ───────────────────────────────────────────────────────
// GET /forge/agents            → Agent[]         api.forge.listAgents()
// GET /forge/agents/:id        → Agent           api.forge.getAgent(id)
export type AgentRole =
  | 'planner' | 'implementer' | 'reviewer' | 'documentation'
  | 'devops' | 'orchestrator';
export interface Agent {
  id: ID;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  runtime: string;            // "claude-code"
  model: string;              // "claude-opus-4-8"
  color: string;
  inflight: number;
  maxConcurrent: number;
  defaultProjectId?: ID;
  schedule?: string;          // cron, optional
  toolset: AgentToolset;      // the 3-layer resolved view
  systemPrompt: string;
  secrets: { key: string }[]; // names only; values never sent to the client
}
// The load-bearing 3-layer toolset. Layers 1 & 2 are read-only (daemon /
// host reported); only layer 3 is editable.
// GET /forge/agents/:id/dispatch-preview → resolves all three.
export interface AgentToolset {
  runtimeBuiltins: string[];          // Layer 1 — daemon-reported
  hostConfig: string[];               // Layer 2 — discovered on host
  managed: ManagedTool[];             // Layer 3 — Agentira-managed (editable)
  strictMcp: boolean;                 // hides Layer 2 when true
}
export interface ManagedTool { name: string; enabled: boolean; always: boolean; }

// ─── Runs (Forge) ─────────────────────────────────────────────────────────
// GET /forge/runs              → Run[]           api.forge.listRuns(params)
// GET /forge/runs/:id          → Run             api.forge.getRun(id)
// GET /forge/runs/:id/events   → RunEvent[]      api.forge.listRunEvents(id)
export interface Run {
  id: ID;
  key: string;                // "run_9f3a2"
  agentId: ID;
  agentName: string;
  taskKey: string;
  projectId: ID;
  status: RunStatus;
  summary: string;            // auto-regenerated each turn while running
  summaryUpdatedAt: ISODate;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  durationSec: number;
  branch?: string;
  pr?: string;
  events: RunEvent[];         // the live conversation / step stream
}
export interface RunEvent {
  id: ID;
  kind: 'read' | 'tool' | 'test' | 'message' | 'thinking';
  text: string;
  at: ISODate;
}

// ─── Conductor & Runtimes ─────────────────────────────────────────────────
// GET /forge/conductor         → Conductor       api.forge.getConductor()
export interface Conductor {
  active: boolean;
  tickSeconds: number;
  planIntervalMin: number;
  dailyReportAt: string;      // "09:00"
  recentCycle: { kind: string; text: string; at: ISODate }[];
  survey: { agentId: ID; name: string; inflight: number; max: number; nextTaskKey?: string }[];
}
// GET /forge/runtimes          → Runtime[]       api.forge.listRuntimes()
export interface Runtime {
  id: ID;
  name: string;
  provider: 'claude' | 'openclaw' | 'ollama' | 'codex';
  version: string;
  status: 'online' | 'offline';
  models: string[];
  capabilities: string[];     // RESUME · STREAM · STOP · PAUSE · MCP
}
// GET /forge/mcp-servers       → McpServer[]     api.forge.listMcpServers()
export interface McpServer {
  id: ID;
  name: string;
  transport: 'http' | 'stdio';
  description: string;
  enabled: boolean;
  agentCount: number;
}

// ─── Chat (Forge messages) ────────────────────────────────────────────────
// GET  /forge/agents/:id/conversations → ChatThread[]  api.forge.listConversations(id)
// GET  /forge/agents/:id/messages      → ChatMessage[] api.forge.listMessages(id, {scope_key})
// POST /forge/agents/:id/messages      → ChatMessage   api.forge.createMessage(id, data)
//
// A conversation is keyed by SCOPE — this is what the header dropdown selects.
export type ChatScope =
  | { kind: 'general' }
  | { kind: 'project'; projectId: ID }
  | { kind: 'task'; taskId: ID };
export interface ChatThread {
  agentId: ID;
  agentName: string;
  color: string;
  status: AgentStatus;
  scope: ChatScope;           // ⇢ dropdown "select a particular convo"
  lastMessage: string;
  unread: number;
  messages: ChatMessage[];
}
export interface ChatMessage {
  id: ID;
  fromMe: boolean;
  authorName?: string;        // for broadcast threads
  text: string;
  at: ISODate;
}

// ─── Inbox / Notifications ────────────────────────────────────────────────
// GET   /notifications?unread_only=:b → Notification[] api.getNotifications()
// PATCH /notifications/:id/read       → void           api.markNotificationRead(id)
export type NotifCategory = 'mention' | 'agent' | 'assigned' | 'workflow';
export interface Notification {
  id: ID;
  category: NotifCategory;
  title: string;
  subtitle: string;
  taskKey?: string;
  at: ISODate;
  read: boolean;
  link: { route: string; params: Record<string, string> };
}

// ─── Deploy (AP-429) ──────────────────────────────────────────────────────
// See docs/deploy-backend-requirements.md for the full contract.
// GET /projects/{id}/deploy/provider            → DeployConnection | {connected:false}
// GET /projects/{id}/deployments                → {branches: BranchEntry[]}
// POST /projects/{id}/deployments               → Deployment
export interface DeployConnection {
  connected: boolean;
  provider?: 'railway' | 'gcp' | 'docker';
  repo?: string;                 // "owner/name"
  service_name?: string;
  service_region?: string | null;
  key_valid?: boolean;
  key_checked_at?: ISODate;
  connected_at?: ISODate;
}

export type DeployStatus = 'queued' | 'building' | 'live' | 'failed' | 'crashed' | 'stopped';

export interface Deployment {
  id: ID;
  status: DeployStatus;
  url?: string | null;
  step?: number | null;
  total_steps?: number | null;
  status_reason: string;         // always non-empty per spec §4
  trigger: 'push' | 'manual' | 'preview';
  updated_at: ISODate;
  events?: Array<{ status: string; at: ISODate }>;
}

export interface BranchEntry {
  branch: string;
  is_main: boolean;
  commit_sha: string;
  commit_message: string;
  author: string;
  author_is_agent: boolean;
  committed_at: ISODate;
  deployment?: Deployment | null;
}

export interface DeploymentsResponse {
  branches: BranchEntry[];
}
