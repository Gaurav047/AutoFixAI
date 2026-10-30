export type Tier = "nano" | "super" | "ultra";

export interface Health {
  ok: boolean;
  public_mode: boolean;
  nebius_configured: boolean;
  github_configured: boolean;
  tavily_configured: boolean;
  base_url: string;
  models?: Record<Tier, string>;
  models_error?: string;
  user_repos?: { enabled: boolean; reason?: string; max_repo_mb?: number; runs_per_hour?: number; max_attempts?: number };
}

export interface Demo {
  id: string;
  name: string;
  language: string;
  description: string;
  test_command: string;
}

export interface RunSummary {
  id: string;
  repo: string;
  test_command: string;
  status: "queued" | "running" | "completed";
  source: string;
  created: number;
  result_status?: string | null;
}

export interface RunEvent {
  seq: number;
  t: number;
  kind: string;
  [key: string]: any;
}

export interface TierUsage {
  model: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  seconds: number;
}

export interface FixResult {
  status: "fixed" | "already_passing" | "failed" | "error";
  attempts?: number;
  tier_used?: Tier | null;
  diff?: string;
  changed_files?: string[];
  triage?: Record<string, any>;
  pr?: { title?: string; body?: string };
  pr_url?: string | null;
  usage?: Record<Tier, TierUsage> & { tavily?: { searches: number } };
  research?: { searches: number; sources: { url: string; title: string }[] };
  seconds?: number;
  error?: string;
}

export interface NewRun {
  demo?: string;
  repo?: string;
  test_command?: string;
  setup_command?: string;
  ref?: string;
  ci_log?: string;
  open_pr?: boolean;
  allow_test_edits?: boolean;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => fetch("/api/health").then(json<Health>),
  demos: () => fetch("/api/demos").then(json<Demo[]>),
  runs: () => fetch("/api/runs").then(json<RunSummary[]>),
  createRun: (body: NewRun) =>
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<RunSummary>),
  stream: (id: string) => new EventSource(`/api/runs/${id}/stream`),
};
