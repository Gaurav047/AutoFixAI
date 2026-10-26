import { useEffect, useMemo, useState } from "react";
import { api, Demo, FixResult, Health, NewRun, RunEvent, RunSummary, Tier } from "./api";

const TIER_LABEL: Record<Tier, string> = { nano: "Nano", super: "Super", ultra: "Ultra" };
const TIER_ROLE: Record<Tier, string> = {
  nano: "Triage · reflection · PR write-up",
  super: "Coding agent (default)",
  ultra: "Escalation for hard failures",
};
const STAGES = [
  { id: "reproduce", label: "Reproduce" },
  { id: "triage", label: "Triage" },
  { id: "fix", label: "Fix" },
  { id: "verify", label: "Verify" },
  { id: "done", label: "Ship" },
];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [demos, setDemos] = useState<Demo[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeId, setActive] = useState<string | null>(() => location.hash.match(/run=(\w+)/)?.[1] ?? null);
  const setActiveId = (id: string) => {
    setActive(id);
    history.replaceState(null, "", `#run=${id}`);
  };

  const refreshRuns = () => api.runs().then(setRuns).catch(() => {});

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.demos().then(setDemos).catch(() => {});
    refreshRuns();
    const t = setInterval(refreshRuns, 4000);
    return () => clearInterval(t);
  }, []);

  const start = async (body: NewRun) => {
    const run = await api.createRun(body);
    setActiveId(run.id);
    refreshRuns();
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32" width="22" height="22">
              <path d="M9 17l5 5 9-11" stroke="currentColor" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <div>
            <h1>AutoFixAI</h1>
            <p>Autonomous CI repair · NVIDIA Nemotron on Nebius Token Factory</p>
          </div>
        </div>
        <StatusPills health={health} />
      </header>

      <main className="layout">
        <aside className="sidebar">
          <NewRunPanel demos={demos} health={health} onStart={start} />
          <RunList runs={runs} activeId={activeId} onSelect={setActiveId} />
        </aside>
        <section className="content">
          {activeId ? <RunView key={activeId} runId={activeId} /> : <Welcome health={health} />}
        </section>
      </main>
    </div>
  );
}

function StatusPills({ health }: { health: Health | null }) {
  if (!health) return <div className="pills"><span className="pill bad">API offline</span></div>;
  return (
    <div className="pills">
      <span className={`pill ${health.nebius_configured ? "ok" : "bad"}`}>Token Factory</span>
      <span className={`pill ${health.github_configured ? "ok" : "off"}`}>GitHub</span>
      <span className={`pill ${health.tavily_configured ? "ok" : "off"}`}>Tavily</span>
    </div>
  );
}

function Welcome({ health }: { health: Health | null }) {
  return (
    <div className="welcome">
      <h2>Red build in, verified pull request out.</h2>
      <p className="lede">
        AutoFixAI reproduces a failing test suite in a sandbox, has a team of NVIDIA Nemotron models
        diagnose and patch the code, checks the patch by rerunning the tests itself, and opens a PR
        explaining the root cause.
      </p>
      <div className="tiers">
        {(["nano", "super", "ultra"] as Tier[]).map((t) => (
          <div key={t} className={`tier-card tier-${t}`}>
            <div className="tier-name">Nemotron {TIER_LABEL[t]}</div>
            <div className="tier-role">{TIER_ROLE[t]}</div>
            <code className="tier-model">{health?.models?.[t] ?? "—"}</code>
          </div>
        ))}
      </div>
      <ol className="how">
        <li><b>Reproduce.</b> Clone the repo into an isolated workspace and run the real test command.</li>
        <li><b>Triage.</b> Nano classifies the failure and names the files it suspects, in about a second.</li>
        <li><b>Research.</b> When a failure points outside the repo, such as a removed API or a library change, Tavily searches the web and the sources are cited in the PR.</li>
        <li><b>Fix.</b> Super reads, searches, edits and reruns tests in a tool-calling loop.</li>
        <li><b>Escalate.</b> If Super's patch is rejected, Nano writes up what went wrong and Ultra retries from a clean tree.</li>
        <li><b>Verify &amp; ship.</b> AutoFixAI reruns the tests itself and rejects any patch that touches test files, then opens a PR.</li>
      </ol>
      <p className="hint">Pick a demo repository on the left to watch a live run.</p>
    </div>
  );
}

function NewRunPanel({ demos, health, onStart }: { demos: Demo[]; health: Health | null; onStart: (b: NewRun) => Promise<void> }) {
  const [tab, setTab] = useState<"demo" | "repo">("demo");
  const [form, setForm] = useState({ repo: "", ref: "", test_command: "python -m pytest -q", ci_log: "", open_pr: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async (body: NewRun) => {
    setBusy(true);
    setError(null);
    try {
      await onStart(body);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="tabs">
        <button className={tab === "demo" ? "active" : ""} onClick={() => setTab("demo")}>Demo repos</button>
        <button className={tab === "repo" ? "active" : ""} onClick={() => setTab("repo")} disabled={health?.public_mode}>
          Your repo
        </button>
      </div>
      {tab === "demo" ? (
        <div className="demos">
          {demos.map((d) => (
            <button key={d.id} className="demo" disabled={busy} onClick={() => go({ demo: d.id })}>
              <span className="demo-name">{d.name}<span className="lang">{d.language}</span></span>
              <span className="demo-desc">{d.description}</span>
            </button>
          ))}
        </div>
      ) : (
        <form
          className="repo-form"
          onSubmit={(e) => {
            e.preventDefault();
            go({ ...form, ref: form.ref || undefined, ci_log: form.ci_log || undefined });
          }}
        >
          <label>Repository<input required placeholder="https://github.com/org/repo or local path" value={form.repo} onChange={(e) => setForm({ ...form, repo: e.target.value })} /></label>
          <div className="row">
            <label>Branch<input placeholder="default" value={form.ref} onChange={(e) => setForm({ ...form, ref: e.target.value })} /></label>
            <label>Test command<input required value={form.test_command} onChange={(e) => setForm({ ...form, test_command: e.target.value })} /></label>
          </div>
          <label>Failing CI log <span className="opt">(optional)</span><textarea rows={3} value={form.ci_log} onChange={(e) => setForm({ ...form, ci_log: e.target.value })} /></label>
          <label className="check">
            <input type="checkbox" checked={form.open_pr} disabled={!health?.github_configured} onChange={(e) => setForm({ ...form, open_pr: e.target.checked })} />
            Open a pull request when fixed
          </label>
          <button className="primary" disabled={busy}>{busy ? "Starting…" : "Fix it"}</button>
        </form>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function RunList({ runs, activeId, onSelect }: { runs: RunSummary[]; activeId: string | null; onSelect: (id: string) => void }) {
  if (!runs.length) return null;
  return (
    <div className="panel">
      <h3 className="panel-title">Runs</h3>
      <ul className="runs">
        {runs.map((r) => (
          <li key={r.id}>
            <button className={r.id === activeId ? "active" : ""} onClick={() => onSelect(r.id)}>
              <span className={`dot ${r.status === "completed" ? r.result_status : r.status}`} />
              <span className="run-repo">{shortRepo(r.repo)}</span>
              <span className="run-meta">{r.source} · {new Date(r.created * 1000).toLocaleTimeString()}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function shortRepo(repo: string) {
  return repo.replace(/^https?:\/\/(www\.)?github\.com\//, "").split(/[\\/]/).slice(-2).join("/");
}

// ------------------------------------------------------------------ run view

function useRunEvents(runId: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  useEffect(() => {
    setEvents([]);
    const es = api.stream(runId);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as RunEvent;
      setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
      if (ev.kind === "end") es.close();
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId]);
  return events;
}

function RunView({ runId }: { runId: string }) {
  const events = useRunEvents(runId);
  const derived = useMemo(() => derive(events), [events]);
  const { stage, tier, attempt, triage, research, diff, writeup, result, models, prUrl } = derived;
  const finished = !!result;

  return (
    <div className="run">
      <Stepper stage={stage} finished={finished} status={result?.status} />

      {result && <ResultBanner result={result} prUrl={prUrl} />}

      <div className="grid">
        <div className="col-main">
          {triage && (
            <Card title="Triage" badge={<TierBadge tier="nano" />}>
              <div className="triage">
                <div><span className="k">Category</span><span className="tag">{triage.category ?? "—"}</span>
                  <span className="k">Difficulty</span><span className={`tag ${triage.difficulty === "hard" ? "warn" : ""}`}>{triage.difficulty ?? "—"}</span></div>
                <p>{triage.summary}</p>
                {triage.hypothesis && <p className="muted"><b>Hypothesis:</b> {triage.hypothesis}</p>}
                {!!triage.suspect_files?.length && (
                  <div className="files">{triage.suspect_files.map((f: string) => <code key={f}>{f}</code>)}</div>
                )}
              </div>
            </Card>
          )}

          {research.length > 0 && (
            <Card title="Web research" badge={<span className="tavily-badge">Tavily</span>}>
              <div className="research">
                {research.map((r: any) => (
                  <div key={r.seq} className="finding">
                    <div className="query"><span className="tag">{r.origin === "triage" ? "after triage" : "agent search"}</span>
                      <code>{r.query}</code></div>
                    {r.error ? <p className="error">Search failed: {r.error}</p> : r.answer && <p>{r.answer}</p>}
                    {!!r.sources?.length && (
                      <ol className="sources">
                        {r.sources.map((s: any) => (
                          <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
                            <span className="muted small">{new URL(s.url).hostname}</span></li>
                        ))}
                      </ol>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {diff && (
            <Card title="Verified patch" badge={<span className="tag ok">tests passing</span>}>
              <DiffView diff={diff} />
            </Card>
          )}

          {writeup && (
            <Card title="Pull request" badge={<TierBadge tier="nano" />}>
              <h4 className="pr-title">{writeup.title}</h4>
              <Markdown text={writeup.body ?? ""} />
            </Card>
          )}

          <Card title="Agent timeline" badge={!finished && tier ? <span className="live"><TierBadge tier={tier} /> attempt {attempt}</span> : null}>
            <Timeline events={events} />
          </Card>
        </div>

        <div className="col-side">
          <Card title="Model routing">
            <UsageTable usage={result?.usage} models={models} activeTier={finished ? null : tier} events={events} />
          </Card>
          {result && (
            <Card title="Run stats">
              <dl className="stats">
                <dt>Outcome</dt><dd>{result.status.replace("_", " ")}</dd>
                <dt>Attempts</dt><dd>{result.attempts ?? 0}</dd>
                <dt>Solved by</dt><dd>{result.tier_used ? `Nemotron ${TIER_LABEL[result.tier_used]}` : "—"}</dd>
                <dt>Wall time</dt><dd>{result.seconds ?? "—"}s</dd>
                <dt>Files changed</dt><dd>{result.changed_files?.length ?? 0}</dd>
              </dl>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function derive(events: RunEvent[]) {
  let stage = "setup";
  let tier: Tier | null = null;
  let attempt = 0;
  let triage: any = null;
  const research: RunEvent[] = [];
  let diff = "";
  let writeup: any = null;
  let result: FixResult | null = null;
  let models: Record<Tier, string> | null = null;
  let prUrl: string | null = null;
  for (const e of events) {
    if (e.kind === "stage") {
      stage = e.stage;
      if (e.tier) tier = e.tier;
      if (e.attempt) attempt = e.attempt;
    } else if (e.kind === "triage") triage = e;
    else if (e.kind === "research") research.push(e);
    else if (e.kind === "diff") diff = e.diff;
    else if (e.kind === "writeup") writeup = e;
    else if (e.kind === "models") models = e.models;
    else if (e.kind === "pr") prUrl = e.url;
    else if (e.kind === "end") result = e.result;
  }
  return { stage, tier, attempt, triage, research, diff, writeup, result, models, prUrl };
}

function Stepper({ stage, finished, status }: { stage: string; finished: boolean; status?: string }) {
  // Research happens between triage and fix; show it as part of the triage step.
  const idx = STAGES.findIndex((s) => s.id === (stage === "research" ? "triage" : stage));
  return (
    <ol className="stepper">
      {STAGES.map((s, i) => {
        let state = i < idx ? "done" : i === idx ? "current" : "todo";
        if (finished) state = status === "fixed" || i < idx ? "done" : i === idx ? "failed" : "todo";
        if (finished && status === "already_passing") state = "done";
        return (
          <li key={s.id} className={state}>
            <span className="bubble">{state === "done" ? "✓" : state === "failed" ? "✕" : i + 1}</span>
            {s.label}
          </li>
        );
      })}
    </ol>
  );
}

function ResultBanner({ result, prUrl }: { result: FixResult; prUrl: string | null }) {
  const text: Record<string, string> = {
    fixed: `Fixed and verified in ${result.attempts} attempt${result.attempts === 1 ? "" : "s"}.`,
    already_passing: "The tests already pass. Nothing to fix.",
    failed: "AutoFixAI couldn't produce a verified fix within its attempt budget. Nothing was pushed.",
    error: `Run errored: ${result.error ?? "unknown error"}`,
  };
  return (
    <div className={`banner ${result.status}`}>
      <span>{text[result.status]}</span>
      {(prUrl || result.pr_url) && <a href={prUrl || result.pr_url!} target="_blank" rel="noreferrer">View pull request →</a>}
    </div>
  );
}

function Card({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card">
      <header><h3>{title}</h3>{badge}</header>
      <div className="card-body">{children}</div>
    </section>
  );
}

function TierBadge({ tier }: { tier: Tier }) {
  return <span className={`tier-badge tier-${tier}`}>Nemotron {TIER_LABEL[tier]}</span>;
}

function Timeline({ events }: { events: RunEvent[] }) {
  const items = events.filter((e) => !["models", "end", "diff", "writeup", "tests_started"].includes(e.kind));
  if (!items.length) return <div className="muted pulse">Waiting for the agent…</div>;
  return (
    <ul className="timeline">
      {items.map((e) => <TimelineItem key={e.seq} e={e} />)}
    </ul>
  );
}

function TimelineItem({ e }: { e: RunEvent }) {
  const time = <span className="t">{e.t.toFixed(1)}s</span>;
  switch (e.kind) {
    case "stage":
      return <li className="ev stage">{time}<b>{e.message}</b>{e.tier && <TierBadge tier={e.tier} />}</li>;
    case "research":
      return (
        <li className="ev research">{time}<span className="tavily-badge">Tavily</span>
          <code>{e.query}</code>
          <span className="muted">{e.error ? `failed: ${e.error}` : `${e.sources?.length ?? 0} sources`}</span>
        </li>
      );
    case "triage":
      return <li className="ev">{time}Triage: <span className="tag">{e.category}</span> {e.summary}</li>;
    case "thought":
      return <li className="ev thought">{time}<span className="quote">{e.text}</span></li>;
    case "tool":
      return <li className="ev tool">{time}<code>{e.name}</code> <span className="muted">{e.summary}</span></li>;
    case "edit":
      return (
        <li className="ev edit">{time}<code>edit</code> <span>{e.path}</span>
          <details><summary>change</summary><DiffView diff={miniDiff(e.old, e.new)} /></details>
        </li>
      );
    case "tests":
      return (
        <li className={`ev tests ${e.passed ? "pass" : "fail"}`}>{time}
          <span className={`tag ${e.passed ? "ok" : "bad"}`}>{e.passed ? "PASS" : "FAIL"}</span>
          {e.baseline ? "Baseline test run" : e.verification ? "Independent verification" : "Agent ran tests"}
          <details><summary>output</summary><pre className="out">{e.output}</pre></details>
        </li>
      );
    case "finish":
      return <li className="ev finish">{time}<b>Agent reports:</b> {e.root_cause} <span className="muted">→ {e.fix_summary}</span></li>;
    case "blocked":
      return <li className="ev blocked">{time}<span className="tag bad">guardrail</span> Blocked edit to <code>{e.path}</code>: {e.reason}</li>;
    case "attempt_failed":
      return <li className="ev blocked">{time}<span className="tag bad">rejected</span> Attempt {e.attempt} ({e.tier}): {e.reason}</li>;
    case "lesson":
      return <li className="ev lesson">{time}<TierBadge tier="nano" /> <span className="quote">{e.text}</span></li>;
    case "pr":
      return <li className="ev">{time}Opened <a href={e.url} target="_blank" rel="noreferrer">{e.url}</a></li>;
    case "error":
      return <li className="ev blocked">{time}<span className="tag bad">error</span> {e.message}</li>;
    default:
      return null;
  }
}

function miniDiff(oldText: string, newText: string) {
  const minus = oldText ? oldText.split("\n").map((l) => "-" + l) : [];
  const plus = newText.split("\n").map((l) => "+" + l);
  return [...minus, ...plus].join("\n");
}

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="diff">
      {diff.split("\n").map((line, i) => {
        let cls = "";
        if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ")) cls = "meta";
        else if (line.startsWith("@@")) cls = "hunk";
        else if (line.startsWith("+")) cls = "add";
        else if (line.startsWith("-")) cls = "del";
        return <span key={i} className={cls}>{line + "\n"}</span>;
      })}
    </pre>
  );
}

function UsageTable({ usage, models, activeTier, events }: {
  usage?: FixResult["usage"]; models: Record<Tier, string> | null; activeTier: Tier | null; events: RunEvent[];
}) {
  const tiers: Tier[] = ["nano", "super", "ultra"];
  const used = new Set<Tier>(["nano"]);
  for (const e of events) if (e.kind === "stage" && e.tier) used.add(e.tier);
  const searches = usage?.tavily?.searches ?? events.filter((e) => e.kind === "research").length;
  return (
    <div className="usage">
      {tiers.map((t) => {
        const u = usage?.[t];
        return (
          <div key={t} className={`usage-row tier-${t} ${activeTier === t ? "active" : ""} ${used.has(t) ? "" : "idle"}`}>
            <div className="usage-head"><TierBadge tier={t} /><span className="muted small">{TIER_ROLE[t]}</span></div>
            <code className="model-id">{u?.model ?? models?.[t] ?? "—"}</code>
            {u && (
              <div className="usage-nums">
                <span><b>{u.calls}</b> calls</span>
                <span><b>{(u.prompt_tokens + u.completion_tokens).toLocaleString()}</b> tokens</span>
                <span><b>{u.seconds}</b>s</span>
              </div>
            )}
          </div>
        );
      })}
      <div className={`usage-row tavily ${searches ? "" : "idle"}`}>
        <div className="usage-head"><span className="tavily-badge">Tavily</span>
          <span className="muted small">Web research for failures outside the repo</span></div>
        <div className="usage-nums"><span><b>{searches}</b> {searches === 1 ? "search" : "searches"}</span></div>
      </div>
    </div>
  );
}

function Markdown({ text }: { text: string }) {
  // Minimal renderer for PR bodies: headings, bullets, inline code, paragraphs.
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string) =>
    s.split(/(`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/).map((part, i) => {
      if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
      const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (link) return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
      return <span key={i}>{part.replace(/\*\*/g, "")}</span>;
    });
  return (
    <div className="md">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (/^#{1,6} /.test(lines[0])) {
          return (
            <div key={i}>
              <h5>{lines[0].replace(/^#+ /, "")}</h5>
              {lines.length > 1 && <Markdown text={lines.slice(1).join("\n")} />}
            </div>
          );
        }
        const isItem = (l: string) => /^\s*[-*] /.test(l);
        if (lines.some(isItem) && !b.startsWith("```")) {
          // A block can mix text lines and bullets (e.g. "Sources retrieved...:" followed by a list).
          const groups: { list: boolean; lines: string[] }[] = [];
          for (const l of lines) {
            const last = groups[groups.length - 1];
            if (last && last.list === isItem(l)) last.lines.push(l);
            else groups.push({ list: isItem(l), lines: [l] });
          }
          return (
            <div key={i}>
              {groups.map((g, j) => g.list
                ? <ul key={j}>{g.lines.map((l, k) => <li key={k}>{inline(l.replace(/^\s*[-*] /, ""))}</li>)}</ul>
                : <p key={j}>{inline(g.lines.join(" "))}</p>)}
            </div>
          );
        }
        if (b.startsWith("```")) return <pre key={i} className="out">{b.replace(/^```\w*\n?|```$/g, "")}</pre>;
        if (/^-{3,}$/.test(b.trim())) return <hr key={i} />;
        const em = b.trim().match(/^[_*]([^_*][\s\S]*)[_*]$/);
        if (em) return <p key={i}><em>{inline(em[1])}</em></p>;
        return <p key={i}>{inline(b)}</p>;
      })}
    </div>
  );
}
