import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlignLeft,
  ArrowLeft,
  Archive,
  AudioLines,
  BookOpen,
  Braces,
  Captions,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Clock3,
  Copy,
  ExternalLink,
  FileJson,
  FileText,
  Film,
  Folder,
  GitBranch,
  GitCompareArrows,
  History,
  Image as ImageIcon,
  Layers3,
  LayoutList,
  ListTree,
  Loader2,
  Mic2,
  Newspaper,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  ShieldCheck,
  Sparkles,
  Terminal,
  Workflow,
} from "lucide-react";
import {
  GenerationLegend,
  GenerationMap,
  GlossaryTip,
  HelpTip,
  InspectorCatalogProvider,
  OriginBadge,
  OriginMark,
  useHelp,
  useInspectorCatalog,
} from "./catalog";
import type { GenerationDefinition, GenerationEvidence, OriginKey, OutputOrigin } from "./catalog";
import {
  CompareRunsView,
  ConfigStudio,
  NewRunView,
  ProvenanceMatches,
  ReviewNotesPanel,
  useControllerStatus,
} from "./control";
import "./styles.css";

const API = "";
type Json = any;

type RunIndex = {
  run_id: string;
  is_current: boolean;
  created_at: string;
  profile: string;
  environment: string;
  trigger: string;
  overall_status: string;
  stage_status: Record<string, string>;
  last_completed_module: string;
  failure_reason: string;
  metrics: Record<string, Json>;
  problems: string[];
};

type ArtifactNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  size?: number;
  media?: boolean;
  extension?: string;
  children?: ArtifactNode[];
};

type ModuleInfo = {
  name: string;
  stage: string;
  status: string;
  path: string;
  summary: Record<string, Json>;
  artifacts: ArtifactNode[];
  reused?: boolean;
  variant_count?: number;
};

type RunDetail = {
  index: RunIndex;
  context: Record<string, Json>;
  state: Record<string, Json>;
  modules: ModuleInfo[];
  errors: Record<string, string | null>;
};

type GlobalArea = "desk" | "new" | "history" | "compare" | "config";
type RunViewKey = "overview" | "workflow" | "lineage" | "diagnostics";
type ViewMode = "read" | "raw";

type WorkflowModule = ModuleInfo & {
  sequence: number;
  label: string;
  purpose: string;
  consumes: string;
  produces: string;
  artifact_count: number;
  has_llm_calls: boolean;
  available_modes: string[];
  primary_origin: OriginKey;
  generation_note: string;
  outputs: OutputOrigin[];
};

type WorkflowStage = {
  key: string;
  order: number;
  label: string;
  purpose: string;
  consumes: string;
  produces: string;
  status: string;
  started_at: string;
  completed_at: string;
  invocation_count: number;
  module_count: number;
  completed_module_count: number;
  primary_origin: OriginKey;
  modules: WorkflowModule[];
};

type WorkflowData = {
  run_id: string;
  updated_at: string;
  read_only: boolean;
  stages: WorkflowStage[];
};

type RecordRowData = {
  record_ref: string;
  record_id: string;
  record_key: string;
  candidate_key: string;
  title: string;
  source: string;
  source_group: string;
  published_at: string;
  content_status: string;
  evidence_decision: string;
  triage_action: string;
  triage_confidence: number | null;
  story_id: string;
  story_title: string;
  selection_action: string;
  selection_role: string;
  outcome: string;
  latest_step: string;
};

function App() {
  const [runs, setRuns] = useState<RunIndex[]>([]);
  const [area, setArea] = useState<GlobalArea>("desk");
  const [originArea, setOriginArea] = useState<GlobalArea>("desk");
  const [openedRunId, setOpenedRunId] = useState("");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [runView, setRunView] = useState<RunViewKey>("overview");
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const [newRunPreset, setNewRunPreset] = useState<{ operation: "new" | "resume" | "retry"; run_id?: string }>({ operation: "new" });
  const controller = useControllerStatus();

  const loadRuns = async (silent = false) => {
    if (!silent) {
      setLoadingRuns(true);
      setError("");
    }
    try {
      const data = await fetchJson<{ runs: RunIndex[] }>("/api/runs");
      setRuns(data.runs);
      setLastSyncedAt(new Date());
    } catch (err) {
      if (!silent) setError(errorMessage(err));
    } finally {
      if (!silent) setLoadingRuns(false);
    }
  };

  useEffect(() => {
    void loadRuns();
    const interval = window.setInterval(() => {
      if (!document.hidden) void loadRuns(true);
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!openedRunId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const loadDetail = async (silent = false) => {
      if (!silent) {
        setLoadingDetail(true);
        setError("");
      }
      try {
        const next = await fetchJson<RunDetail>(`/api/runs/${encodeURIComponent(openedRunId)}`);
        if (!cancelled) setDetail(next);
      } catch (err) {
        if (!silent && !cancelled) setError(errorMessage(err));
      } finally {
        if (!silent && !cancelled) setLoadingDetail(false);
      }
    };
    void loadDetail();
    const interval = window.setInterval(() => {
      if (!document.hidden) void loadDetail(true);
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [openedRunId]);

  const openRun = (runId: string, view: RunViewKey, from: GlobalArea) => {
    setOriginArea(from);
    setOpenedRunId(runId);
    setRunView(view);
  };

  const returnToArea = (next: GlobalArea) => {
    setArea(next);
    setOpenedRunId("");
    setDetail(null);
    setError("");
  };

  const openRunBuilder = (operation: "new" | "resume" | "retry" = "new", runId?: string) => {
    setNewRunPreset({ operation, run_id: runId });
    returnToArea("new");
  };

  const currentRun = runs.find((run) => run.is_current) || runs[0];

  return (
    <div className="productShell">
      <GlobalHeader
        area={openedRunId ? originArea : area}
        runOpen={Boolean(openedRunId)}
        lastSyncedAt={lastSyncedAt}
        onNavigate={returnToArea}
        onRefresh={() => void loadRuns()}
        controller={controller}
      />
      <main className="productMain">
        {error && <ErrorBanner message={error} />}
        {!openedRunId && area === "desk" && (
          <RunDesk
            runs={runs}
            currentRun={currentRun}
            loading={loadingRuns}
            activeJob={controller.activeJob}
            onOpen={(id, view) => openRun(id, view, "desk")}
            onHistory={() => returnToArea("history")}
            onNew={() => openRunBuilder("new")}
            onContinue={(id) => openRunBuilder("resume", id)}
            controllerConnected={controller.available}
          />
        )}
        {!openedRunId && area === "new" && (
          <NewRunView
            runs={runs}
            preset={newRunPreset}
            controller={controller}
            onRunsChanged={() => void loadRuns(true)}
          />
        )}
        {!openedRunId && area === "history" && (
          <HistoryView runs={runs} loading={loadingRuns} onOpen={(id) => openRun(id, "overview", "history")} />
        )}
        {!openedRunId && area === "compare" && <CompareRunsView runs={runs} />}
        {!openedRunId && area === "config" && <ConfigStudio activeJob={controller.activeJob} />}
        {openedRunId && loadingDetail && !detail && <Loading label="Opening run" />}
        {openedRunId && detail && detail.index.run_id === openedRunId && (
          <RunWorkspace
            detail={detail}
            activeView={runView}
            onView={setRunView}
            onBack={() => returnToArea(originArea)}
            backLabel={originArea === "history" ? "Runs" : "Run desk"}
            runs={runs}
            loading={loadingRuns}
            onSelectRun={(id) => openRun(id, runView, originArea)}
            onRefresh={() => void loadRuns()}
          />
        )}
      </main>
    </div>
  );
}

function GlobalHeader({
  area,
  runOpen,
  lastSyncedAt,
  onNavigate,
  onRefresh,
  controller,
}: {
  area: GlobalArea;
  runOpen: boolean;
  lastSyncedAt: Date | null;
  onNavigate: (area: GlobalArea) => void;
  onRefresh: () => void;
  controller: ReturnType<typeof useControllerStatus>;
}) {
  const deskHelp = useHelp("run_desk");
  const historyHelp = useHelp("history");
  return (
    <header className="globalHeader">
      <button className="globalBrand" onClick={() => onNavigate("desk")}>
        <span className="brandRule" />
        <span><small>Production desk</small><strong>Run Inspector</strong></span>
      </button>
      <nav className="globalNav" aria-label="Primary navigation">
        <button className={area === "desk" ? "active" : ""} title={deskHelp} onClick={() => onNavigate("desk")}>
          <Layers3 size={17} /> Run desk
        </button>
        <button className={area === "new" ? "active" : ""} title="Build and supervise an allowlisted local pipeline plan." onClick={() => onNavigate("new")}>
          <Plus size={17} /> New run
        </button>
        <button className={area === "history" ? "active" : ""} title={historyHelp} onClick={() => onNavigate("history")}>
          <History size={17} /> History
        </button>
        <button className={area === "compare" ? "active" : ""} title="Compare two persisted runs." onClick={() => onNavigate("compare")}>
          <GitCompareArrows size={17} /> Compare
        </button>
        <button className={area === "config" ? "active" : ""} title="Edit validated current authoring YAML." onClick={() => onNavigate("config")}>
          <SlidersHorizontal size={17} /> Config
        </button>
      </nav>
      <div className="syncStatus">
        <span className={`liveDot ${controller.activeJob ? "working" : controller.available ? "" : "offline"}`} />
        <span>{controller.activeJob ? humanize(controller.activeJob.current_stage || controller.activeJob.status) : runOpen ? "Run polling" : controller.available ? "Controller ready" : "Inspector only"}</span>
        <small>{lastSyncedAt ? lastSyncedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Waiting"}</small>
        <button className="iconButton" title="Refresh now" onClick={onRefresh}><RefreshCw size={16} /></button>
      </div>
    </header>
  );
}

type CreditProvider = { key: string; label: string; status: string; balance?: number; currency?: string; available?: boolean; reason?: string; dashboard?: string };
type CreditsData = { providers: CreditProvider[]; fetched_at: string };

function useCredits() {
  const [data, setData] = useState<CreditsData | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = async (force = false) => {
    setLoading(true);
    try {
      const res = await fetch(`/control/credits${force ? "?refresh=true" : ""}`);
      if (!res.ok) throw new Error();
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void refresh(); }, []);
  return { data, loading, refresh };
}

function creditTone(provider: CreditProvider): string {
  if (provider.status !== "ok" || typeof provider.balance !== "number") return "muted";
  if (provider.balance < 1) return "critical";
  if (provider.balance < 3) return "low";
  return "ok";
}

function formatMoney(value: number | undefined, currency: string | undefined): string {
  if (typeof value !== "number") return "—";
  const symbol = currency === "USD" ? "$" : currency === "CNY" ? "¥" : "";
  return `${symbol}${value.toFixed(2)}${symbol ? "" : ` ${currency || ""}`}`.trim();
}

function CreditsPanel({ credits }: { credits: ReturnType<typeof useCredits> }) {
  const providers = credits.data?.providers || [];
  if (credits.loading && !credits.data) return null;
  if (!providers.length) return null;
  const low = providers.some((provider) => ["low", "critical"].includes(creditTone(provider)));
  return (
    <section className="creditsPanel">
      <div className="creditsHead">
        <SectionTitle label="Provider balances" title="AI credits" />
        {low && <span className="creditsFlag">Low balance</span>}
        <button className="iconButton" title="Refresh balances" onClick={() => void credits.refresh(true)}><RefreshCw size={14} /></button>
      </div>
      <div className="creditsRow">
        {providers.map((provider) => (
          <a
            key={provider.key}
            className={`creditCard tone-${creditTone(provider)}`}
            href={provider.dashboard || "#"}
            target="_blank"
            rel="noreferrer"
            title={provider.status === "ok" ? "Open provider dashboard" : provider.reason || "Unavailable"}
          >
            <strong>{provider.label}</strong>
            {provider.status === "ok"
              ? <span className="creditAmount">{formatMoney(provider.balance, provider.currency)}</span>
              : <span className="creditNa">{provider.status === "unavailable" ? "No balance API" : "Unavailable"}</span>}
          </a>
        ))}
      </div>
    </section>
  );
}

const MINIMAP_STAGES: Array<[string, string]> = [
  ["ingestion", "Ingest"],
  ["content", "Content"],
  ["voiceover", "Voice"],
  ["visuals", "Visuals"],
];

function StageMiniMap({ stageStatus, compact = false }: { stageStatus?: Record<string, string>; compact?: boolean }) {
  const status = stageStatus || {};
  return (
    <div className={`stageMiniMap ${compact ? "compact" : ""}`} role="img" aria-label="Stage progress">
      {MINIMAP_STAGES.map(([key, label]) => {
        const state = status[key] || "missing";
        return (
          <span key={key} className={`miniStage ${statusClass(state)}`} title={`${label}: ${humanize(state)}`}>
            <span className="miniDot" />
            {!compact && <span className="miniLabel">{label}</span>}
          </span>
        );
      })}
    </div>
  );
}

type ActiveJob = { id: string; run_id: string; status: string; current_stage: string; current_step: number; step_count: number };

function ActiveJobPanel({ job, onOpen }: { job: ActiveJob; onOpen: () => void }) {
  const pct = job.step_count ? Math.max(6, Math.round((job.current_step / job.step_count) * 100)) : 0;
  return (
    <section className="activeJobPanel">
      <div className="activeJobHead">
        <span className="liveDot working" />
        <div className="activeJobIdent">
          <strong>{humanize(job.current_stage || job.status)}</strong>
          <small>{job.run_id} · step {Math.max(job.current_step, 1)} of {job.step_count || 1}</small>
        </div>
        <span className={`controlStatus status-${job.status}`}><i />{humanize(job.status)}</span>
        <button className="secondaryButton" onClick={onOpen}><Terminal size={15} /> Console</button>
      </div>
      <div className="activeJobBar"><span style={{ width: `${pct}%` }} /></div>
    </section>
  );
}

function RunDesk({
  runs,
  currentRun,
  loading,
  activeJob,
  onOpen,
  onHistory,
  onNew,
  onContinue,
  controllerConnected,
}: {
  runs: RunIndex[];
  currentRun?: RunIndex;
  loading: boolean;
  activeJob?: ActiveJob | null;
  onOpen: (id: string, view: RunViewKey) => void;
  onHistory: () => void;
  onNew: () => void;
  onContinue: (id: string) => void;
  controllerConnected: boolean;
}) {
  const catalog = useInspectorCatalog();
  const stages = catalog?.stages || [];
  const credits = useCredits();
  return (
    <div className="deskPage">
      <ViewHeading eyebrow="Local production" title="Run desk" summary="What's running now, the current run's stage progress, and provider balances." helpKey="run_desk" />
      {controllerConnected && <CreditsPanel credits={credits} />}
      {activeJob && ["queued", "running", "cancelling", "orphaned"].includes(activeJob.status) && <ActiveJobPanel job={activeJob} onOpen={onNew} />}
      {loading && !currentRun ? <Loading label="Scanning output" /> : currentRun ? (
        <section className="currentRunBand">
          <div className="currentRunLead">
            <div className="runStatusLine"><StatusChip status={currentRun.overall_status} /><span>{currentRun.is_current ? "Current run" : "Latest discovered run"}</span></div>
            <h3>{runTitle(currentRun)}</h3>
            <p>{currentRun.run_id}</p>
            <StageMiniMap stageStatus={currentRun.stage_status} />
            {currentRun.failure_reason && <div className="inlineWarning">{currentRun.failure_reason}</div>}
          </div>
          <dl className="deskMetrics">
            <Metric label="Last module" value={humanize(currentRun.last_completed_module || "None")} helpKey="last_module" />
            <Metric label="Script" value={currentRun.metrics?.script_word_count ? `${formatNumber(currentRun.metrics.script_word_count)} words` : "Not available"} helpKey="script_metric" />
            <Metric label="Voice" value={formatDuration(currentRun.metrics?.audio_duration_seconds)} helpKey="voice_metric" />
            <Metric label="Video" value={currentRun.metrics?.final_video_available ? "Episode ready" : "Not available"} helpKey="video_metric" />
          </dl>
          <div className="deskCommands">
            <button className="secondaryButton" onClick={() => onOpen(currentRun.run_id, "overview")}><Newspaper size={16} /> Overview</button>
            <button className="primaryButton" onClick={() => onOpen(currentRun.run_id, "workflow")}><Workflow size={16} /> Inspect workflow</button>
            <button className="secondaryButton" disabled={!controllerConnected} onClick={() => onContinue(currentRun.run_id)}><Play size={16} /> Continue</button>
          </div>
        </section>
      ) : <EmptyState label="No runs found under output/runs" />}

      <div className={`controllerState ${controllerConnected ? "connected" : ""}`}>
        <ShieldCheck size={16} />
        <span>Execution boundary <HelpTip text="Run commands are owned by the separate local controller; artifact inspection remains isolated and path-restricted." /></span>
        <strong>{controllerConnected ? "Controller ready" : "Inspector only"}</strong>
        <small>{controllerConnected ? "One supervised writer" : "Execution controller not connected"}</small>
        <button className="textButton" disabled={!controllerConnected} onClick={onNew}>New run <ChevronRight size={14} /></button>
      </div>

      <section className="recentRunsSection">
        <div className="sectionHeadingRow"><SectionTitle label="Recently discovered" title="Run activity" /><button className="textButton" onClick={onHistory}>View all runs <ChevronRight size={15} /></button></div>
        <div className="recentRunRows">
          {runs.slice(0, 5).map((run) => (
            <button key={run.run_id} onClick={() => onOpen(run.run_id, "overview")}>
              <StatusChip status={run.overall_status} />
              <div><strong>{runTitle(run)}</strong><small>{run.run_id}</small></div>
              <StageMiniMap stageStatus={run.stage_status} compact />
              <time>{shortDate(run.created_at)}</time>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      </section>

      <details className="capabilityDetails">
        <summary>Pipeline reference — the production path</summary>
        <div className="capabilityFlow">
          {stages.map((stage, index) => (
            <div className="capabilityStep" key={stage.key} title={stage.purpose}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{stage.label}</strong><small>{stage.desk_summary}</small></div>
              <em>{stage.modules.length} module{stage.modules.length === 1 ? "" : "s"}</em>
              <OriginMark origin={stage.primary_origin} />
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

function HistoryView({ runs, loading, onOpen }: { runs: RunIndex[]; loading: boolean; onOpen: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const visible = useMemo(() => runs.filter((run) => {
    const matchesQuery = `${run.run_id} ${run.profile} ${run.environment}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (status === "all" || run.overall_status === status);
  }), [runs, query, status]);
  const statuses = ["all", ...Array.from(new Set(runs.map((run) => run.overall_status).filter(Boolean)))];
  return (
    <div className="historyPage">
      <ViewHeading eyebrow="Persisted output" title="Run history" summary={`${runs.length} dynamically discovered run${runs.length === 1 ? "" : "s"}.`} helpKey="history" />
      <div className="historyToolbar">
        <FilterBar value={query} onChange={setQuery} placeholder="Search run ID, profile, or environment" />
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by status">
          {statuses.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
        </select>
      </div>
      {loading ? <Loading label="Scanning runs" /> : (
        <div className="historyTableWrap">
          <table className="historyTable">
            <thead><tr><th>Status</th><th>Run</th><th>Progress</th><th>Output</th><th>Created</th><th><span className="srOnly">Open</span></th></tr></thead>
            <tbody>
              {visible.map((run) => (
                <tr key={run.run_id}>
                  <td><StatusChip status={run.overall_status} /></td>
                  <td><strong>{runTitle(run)}</strong><small>{run.run_id}</small></td>
                  <td><StageMiniMap stageStatus={run.stage_status} compact /><small>{humanize(run.last_completed_module || "No completed module")}</small></td>
                  <td><span>{run.metrics?.final_video_available ? "Episode video" : run.metrics?.script_word_count ? "Script" : "Artifacts only"}</span></td>
                  <td><time>{formatDate(run.created_at)}</time></td>
                  <td><button className="iconButton" title="Open run" onClick={() => onOpen(run.run_id)}><ChevronRight size={17} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && <EmptyState label="No matching runs" />}
        </div>
      )}
    </div>
  );
}

function RunWorkspace({
  detail,
  activeView,
  onView,
  onBack,
  backLabel,
  runs,
  loading,
  onSelectRun,
  onRefresh,
}: {
  detail: RunDetail;
  activeView: RunViewKey;
  onView: (view: RunViewKey) => void;
  onBack: () => void;
  backLabel: string;
  runs: RunIndex[];
  loading: boolean;
  onSelectRun: (id: string) => void;
  onRefresh: () => void;
}) {
  const catalog = useInspectorCatalog();
  const views: Array<{ key: RunViewKey; label: string; icon: React.ElementType; helpKey: string }> = [
    { key: "overview", label: "Overview", icon: Newspaper, helpKey: "overview" },
    { key: "workflow", label: "Workflow", icon: Workflow, helpKey: "workflow" },
    { key: "lineage", label: "Record lineage", icon: GitBranch, helpKey: "record_lineage" },
    { key: "diagnostics", label: "Run diagnostics", icon: Terminal, helpKey: "run_diagnostics" },
  ];
  const activeLabel = views.find((view) => view.key === activeView)?.label || "";
  return (
    <div className="runLayout">
      <RunRail embedded runs={runs} selected={detail.index.run_id} loading={loading} onSelect={onSelectRun} onRefresh={onRefresh} />
      <div className="runWorkspace">
        <nav className="breadcrumbs" aria-label="Breadcrumb">
          <button onClick={onBack}>{backLabel}</button>
          <ChevronRight size={14} />
          <span title={detail.index.run_id}>{runTitle(detail.index)}</span>
          <ChevronRight size={14} />
          <strong>{activeLabel}</strong>
        </nav>
        <RunMasthead run={detail.index} />
        <nav className="runNav" aria-label="Selected run navigation">
          {views.map(({ key, label, icon: Icon, helpKey }) => (
            <button key={key} className={activeView === key ? "active" : ""} title={catalog?.help?.[helpKey]} onClick={() => onView(key)}><Icon size={16} />{label}</button>
          ))}
        </nav>
        <div className="runViewCanvas" key={`${detail.index.run_id}-${activeView}`}>
          {activeView === "overview" && <OverviewView detail={detail} onView={onView} />}
          {activeView === "workflow" && <WorkflowView runId={detail.index.run_id} />}
          {activeView === "lineage" && <RecordLineageView runId={detail.index.run_id} />}
          {activeView === "diagnostics" && <DiagnosticsView runId={detail.index.run_id} modules={detail.modules} />}
        </div>
      </div>
    </div>
  );
}

function RunRail({
  runs,
  selected,
  loading,
  onSelect,
  onRefresh,
  embedded = false,
}: {
  runs: RunIndex[];
  selected: string;
  loading: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => Promise<void> | void;
  embedded?: boolean;
}) {
  const [query, setQuery] = useState("");
  const visible = runs.filter((run) => `${run.run_id} ${run.profile} ${run.overall_status}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <aside className={`runRail ${embedded ? "embedded" : ""}`}>
      {!embedded && (
        <header className="brandMark">
          <span className="brandRule" />
          <div>
            <span className="eyebrow">Production desk</span>
            <h1>Run Inspector</h1>
          </div>
        </header>
      )}
      <div className="railToolbar">
        <label className="searchField">
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a run" />
        </label>
        <button className="iconButton" title="Refresh runs" onClick={() => void onRefresh()}>
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="railCount">{visible.length} of {runs.length} runs</div>
      {loading ? <Loading label="Scanning runs" /> : (
        <div className="runList">
          {visible.map((run) => (
            <button key={run.run_id} className={`runItem ${selected === run.run_id ? "selected" : ""}`} onClick={() => onSelect(run.run_id)}>
              <div className="runItemTop">
                <StatusChip status={run.overall_status} />
                <time>{shortDate(run.created_at)}</time>
              </div>
              <strong>{humanize(run.profile || "Unprofiled run")}</strong>
              <span>{shortRunId(run.run_id)}</span>
              <StageMiniMap stageStatus={run.stage_status} compact />
            </button>
          ))}
          {!visible.length && <EmptyState label="No matching runs" />}
        </div>
      )}
      {!embedded && <footer className="railFooter"><span />Read only / local</footer>}
    </aside>
  );
}

function RunMasthead({ run }: { run: RunIndex }) {
  const metrics = run.metrics || {};
  return (
    <header className="runMasthead">
      <div className="runIdentity">
        <div className="runStatusLine">
          <StatusChip status={run.overall_status} />
          {run.is_current && <span className="currentLabel">Current run</span>}
          <span>{run.environment || "environment unknown"}</span>
        </div>
        <h2>{runTitle(run)}</h2>
        <p>{run.run_id}</p>
        <StageMiniMap stageStatus={run.stage_status} />
      </div>
      <dl className="headlineMetrics">
        <Metric label="Script" value={metrics.script_word_count ? `${formatNumber(metrics.script_word_count)} words` : "Not available"} helpKey="script_metric" />
        <Metric label="Voice" value={formatDuration(metrics.audio_duration_seconds)} helpKey="voice_metric" />
        <Metric label="Video" value={metrics.final_video_available ? "Episode ready" : "Not available"} helpKey="video_metric" />
      </dl>
    </header>
  );
}

function WorkflowView({ runId }: { runId: string }) {
  const [data, setData] = useState<WorkflowData | null>(null);
  const [error, setError] = useState("");
  const [selectedStageKey, setSelectedStageKey] = useState("ingestion");
  const [selectedModule, setSelectedModule] = useState("news_collection");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const next = await fetchJson<WorkflowData>(`/api/runs/${encodeURIComponent(runId)}/workflow`);
        if (cancelled) return;
        setData(next);
        setError("");
        const stage = next.stages.find((item) => item.key === selectedStageKey) || next.stages[0];
        if (stage && !stage.modules.some((module) => module.name === selectedModule)) {
          setSelectedStageKey(stage.key);
          setSelectedModule(stage.modules[0]?.name || "");
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    };
    void load();
    const interval = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [runId]);

  const selectedStage = data?.stages.find((stage) => stage.key === selectedStageKey) || data?.stages[0];
  const selectStage = (stage: WorkflowStage) => {
    setSelectedStageKey(stage.key);
    setSelectedModule(stage.modules[0]?.name || "");
  };
  return (
    <>
      <ViewHeading eyebrow="Execution trace" title="Stage-by-stage workflow" summary="Every persisted module in production order, with its inputs, produced data, decisions, activity, configuration, and artifacts." helpKey="workflow" />
      <GenerationLegend />
      {error && <ErrorBanner message={error} />}
      {!data ? <Loading label="Building workflow" /> : (
        <>
          <div className="workflowStageStrip">
            {data.stages.map((stage) => (
              <button key={stage.key} className={selectedStage?.key === stage.key ? "active" : ""} title={stage.purpose} onClick={() => selectStage(stage)}>
                <span>{String(stage.order).padStart(2, "0")}</span>
                <div><strong>{stage.label}</strong><small>{stage.completed_module_count} of {stage.module_count} modules</small></div>
                <div className="stageState"><StatusChip status={stage.status} /><OriginMark origin={stage.primary_origin} /></div>
              </button>
            ))}
          </div>
          {selectedStage && (
            <div className="stageBriefBand">
              <div><span className="sectionLabel">Stage {selectedStage.order}</span><h3>{selectedStage.purpose}</h3></div>
              <dl><Fact label="Consumes" value={selectedStage.consumes} /><Fact label="Produces" value={selectedStage.produces} /><Fact label="Invocations" value={selectedStage.invocation_count} /></dl>
            </div>
          )}
          <div className="workflowLayout">
            <aside className="moduleSequence" aria-label="Stage modules">
              <span className="sectionLabel">Module sequence</span>
              {(selectedStage?.modules || []).map((module) => (
                <button key={module.name} className={selectedModule === module.name ? "active" : ""} title={`${module.purpose} ${module.generation_note}`} onClick={() => setSelectedModule(module.name)}>
                  <span>{String(module.sequence).padStart(2, "0")}</span>
                  <div><strong>{module.label}</strong><small>{module.produces}</small></div>
                  <div className="moduleSequenceState"><StatusChip status={module.status} /><OriginMark origin={module.primary_origin} /></div>
                </button>
              ))}
            </aside>
            <ModuleInspector runId={runId} module={selectedModule} />
          </div>
        </>
      )}
    </>
  );
}

function ModuleInspector({ runId, module }: { runId: string; module: string }) {
  const result = useModule(runId, module);
  const [section, setSection] = useState("summary");
  const [mode, setMode] = useState<ViewMode>("read");
  useEffect(() => {
    setSection("summary");
    setMode("read");
  }, [module]);
  if (result.loading) return <section className="moduleInspector"><Loading label="Opening module" /></section>;
  if (result.error) return <section className="moduleInspector"><ErrorBanner message={result.error} /></section>;
  const data = result.data || {};
  const sources = (data.raw_sources || []) as Json[];
  const tabs = [
    { key: "summary", label: "Summary", helpKey: "module_summary" },
    { key: "data", label: "Produced data", helpKey: "module_data" },
    { key: "input", label: "Inputs", helpKey: "module_inputs" },
    { key: "output", label: "Outputs", helpKey: "module_outputs" },
    { key: "activity", label: "Activity", helpKey: "module_activity" },
    { key: "config", label: "Config", helpKey: "module_config" },
    { key: "artifacts", label: "Artifacts", helpKey: "module_artifacts" },
  ];
  const rawSources = sources
    .filter((source) => !source.media)
    .map((source) => ({ label: `${humanize(source.role)} / ${source.label}`, path: source.path }));
  return (
    <section className="moduleInspector">
      <header className="moduleInspectorHeader">
        <div>
          <div className="runStatusLine"><StatusChip status={data.status || "missing"} />{data.reused && <span className="currentLabel">Reused</span>}<span>{data.recorded_at ? formatDate(data.recorded_at) : "No recorded time"}</span></div>
          <h2>{data.definition?.label || humanize(module)}</h2>
          <p>{data.definition?.purpose || "No module description is available."}</p>
          <OriginBadge origin={data.definition?.primary_origin || "deterministic"} />
        </div>
        <ModeSwitch mode={mode} onChange={setMode} />
      </header>
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={rawSources} /> : (
        <>
          <SubNav value={section} onChange={setSection} items={tabs} compact />
          <div className="moduleInspectorBody">
            {section === "summary" && <ModuleSummary data={data} />}
            {section === "data" && <><GenerationMap definition={data.definition as GenerationDefinition} evidence={data.generation_evidence as GenerationEvidence} compact /><ModuleDataReader runId={runId} module={module} data={data.curated || {}} /></>}
            {section === "input" && <ArtifactRolePanel runId={runId} sources={sources.filter((source) => source.role === "input")} empty="No persisted module input was found" />}
            {section === "output" && <ArtifactRolePanel runId={runId} sources={sources.filter((source) => ["summary", "primary", "result", "media"].includes(source.role))} empty="No persisted module output was found" />}
            {section === "activity" && <ModuleActivityPanel runId={runId} module={module} activity={data.activity || {}} />}
            {section === "config" && <ArtifactRolePanel runId={runId} sources={sources.filter((source) => source.role === "config")} empty="No effective config snapshot was persisted" />}
            {section === "artifacts" && <ArtifactRolePanel runId={runId} sources={sources} empty="No artifacts were discovered" />}
          </div>
        </>
      )}
    </section>
  );
}

function ModuleSummary({ data }: { data: Json }) {
  return (
    <div className="moduleSummaryView">
      <section className="moduleContract">
        <div><span className="sectionLabel">Receives</span><p>{data.definition?.consumes || "Not documented"}</p></div>
        <ChevronRight size={19} />
        <div><span className="sectionLabel">Produces</span><p>{data.definition?.produces || "Not documented"}</p></div>
      </section>
      <GenerationMap definition={data.definition as GenerationDefinition} evidence={data.generation_evidence as GenerationEvidence} />
      <section className="dataSection"><SectionTitle label="Persisted summary" title="Module measurements" />{Object.keys(data.summary || {}).length ? <ReadableObject value={data.summary} /> : <EmptyState label="No compact summary was persisted" />}</section>
      <section className="moduleFacts"><Fact label="Module path" value={data.path} /><Fact label="Artifact files" value={(data.raw_sources || []).length} /><Fact label="Reused" value={data.reused ? "Yes" : "No"} /></section>
    </div>
  );
}

function ModuleDataReader({ runId, module, data }: { runId: string; module: string; data: Json }) {
  if (!data || !Object.keys(data).length) return <EmptyState label="No curated data view is available; use Outputs or Raw for the persisted artifacts" />;
  if (module === "news_collection") return <CollectionReader data={data} />;
  if (module === "evidence_prep") return <EvidenceReader data={data} />;
  if (module === "editorial_triage") return <TriageReader data={data} />;
  if (module === "story_mapping") return <section className="storyDirectory">{(data.stories || []).map((story: Json) => <DirectoryStory key={story.story_id} story={story} />)}</section>;
  if (module === "editorial_selection") return <div className="selectionData"><section className="directionLead"><span className="sectionLabel">Episode thesis</span><h3>{data.episode_thesis || "No thesis persisted"}</h3><p>{data.ordering_rationale}</p></section><section className="selectedStories">{(data.selected_stories || []).map((story: Json, index: number) => <SelectedStory key={story.story_id} story={story} index={index} />)}</section><section className="dataSection"><SectionTitle label="Reserve and rejection" title="Stories not selected" /><div className="storyDirectory">{[...(data.reserve_stories || []), ...(data.rejected_stories || [])].map((story: Json) => <DirectoryStory key={story.story_id} story={story} />)}</div></section></div>;
  if (module === "video_packaging") return <div><MetricBand items={[["Format", data.selected_format], ["Stories", data.story_count]]} /><section className="dataSection"><SectionTitle label="Structural packet" title="Packaged stories" /><div className="storyDirectory">{(data.stories || []).map((story: Json) => <DirectoryStory key={story.story_id} story={story} />)}</div></section><ReadableObject value={{ editorial_context: data.editorial_context, format_contract: data.format_contract, duration_policy: data.duration_policy }} /></div>;
  if (module === "script_generation") return <div className="scriptModuleData"><ScriptReading sections={data.sections || []} /><section className="dataSection"><SectionTitle label="Audiovisual structure" title="Beat sheet" /><BeatSheet sections={data.sections || []} /></section></div>;
  if (module === "metadata_creator" || module === "metadata_finalizer") {
    const metadata = data.youtube_metadata || {};
    return <div className="metadataLayout"><TitleOptions options={metadata.title_options || []} /><ThumbnailConcepts concepts={metadata.thumbnail_concepts || []} textOptions={metadata.thumbnail_text_options || []} blocked={metadata.blocked_title_angles || []} /><DescriptionReader metadata={metadata} /></div>;
  }
  if (module === "voiceover") return <VoiceVariantsData runId={runId} variants={data.variants || []} />;
  if (module === "visuals") return <ModuleVideoData data={data} />;
  return <ReadableObject value={data} />;
}

function VoiceVariantsData({ runId, variants }: { runId: string; variants: Json[] }) {
  const [selectedId, setSelectedId] = useState(variants[0]?.variant_id || "");
  const selected = variants.find((variant) => variant.variant_id === selectedId) || variants[0];
  if (!selected) return <EmptyState label="No voiceover variants were persisted" />;
  return (
    <div className="voiceVariantModule">
      <div className="voiceToolbar">
        <label>Variant<select value={selected.variant_id} onChange={(event) => setSelectedId(event.target.value)}>{variants.map((variant) => <option key={variant.variant_id} value={variant.variant_id}>{variant.voice || variant.variant_id}</option>)}</select></label>
        <StatusChip status={selected.status} />
      </div>
      {selected.audio_path && <audio className="voicePlayer" controls preload="metadata" src={mediaUrl(selected.audio_path)} />}
      <MetricBand items={[["Provider", selected.provider], ["Model", selected.model], ["Voice", selected.voice], ["Duration", formatDuration(selected.duration_seconds)], ["Units", selected.unit_count], ["Chunks", selected.chunk_count]]} />
      <section className="dataSection"><SectionTitle label="Variant setup" title="Synthesis and mastering" /><ReadableObject value={{ style: selected.style, style_description: selected.style_description, speed: selected.speed, sample_rate_hz: selected.sample_rate_hz, mastering_status: selected.mastering_status, integrated_lufs: selected.integrated_lufs, true_peak_db: selected.true_peak_db, captions: selected.captions, variant_id: selected.variant_id, run_id: runId }} /></section>
    </div>
  );
}

function ModuleVideoData({ data }: { data: Json }) {
  return (
    <div className="moduleVideoData">
      {data.final_video ? <section><SectionTitle label="Rendered episode" title="Episode video" /><video controls preload="metadata" src={mediaUrl(data.final_video)} /></section> : <EmptyState label="No rendered episode for this run" />}
      <ReadableObject value={data.summary || {}} />
    </div>
  );
}

function ArtifactRolePanel({ runId, sources, empty }: { runId: string; sources: Json[]; empty: string }) {
  const [selectedPath, setSelectedPath] = useState(sources[0]?.path || "");
  const [artifact, setArtifact] = useState<Json>(null);
  useEffect(() => {
    setSelectedPath(sources[0]?.path || "");
  }, [runId, sources.map((source) => source.path).join("|")]);
  useEffect(() => {
    if (!selectedPath) {
      setArtifact(null);
      return;
    }
    setArtifact(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/artifacts?path=${encodeURIComponent(selectedPath)}`)
      .then(setArtifact)
      .catch((err) => setArtifact({ kind: "error", text: errorMessage(err) }));
  }, [runId, selectedPath]);
  if (!sources.length) return <EmptyState label={empty} />;
  return (
    <div className="artifactRoleLayout">
      <aside className="artifactSourceList">
        {sources.map((source) => (
          <button key={source.path} className={selectedPath === source.path ? "active" : ""} onClick={() => setSelectedPath(source.path)}>
            {source.media ? <Film size={15} /> : source.extension === ".json" || source.extension === ".jsonl" ? <FileJson size={15} /> : <FileText size={15} />}
            <div><strong>{source.label}</strong><small>{humanize(source.role)} / {formatBytes(source.size || 0)}</small></div>
          </button>
        ))}
      </aside>
      <section className="artifactSourcePreview">
        <div className="artifactPathBar"><span>{selectedPath}</span></div>
        {!artifact ? <Loading label="Reading artifact" /> : <ArtifactPreview artifact={artifact} />}
      </section>
    </div>
  );
}

function ModuleActivityPanel({ runId, module, activity }: { runId: string; module: string; activity: Json }) {
  const [ttsVariant, setTtsVariant] = useState(activity.tts_variants?.[0] || "");
  const hasAnything = activity.llm_ledger || activity.log_stage || activity.tts_variants?.length;
  if (!hasAnything) return <EmptyState label="No stage log or call ledger was persisted for this module" />;
  return (
    <div className="moduleActivity">
      {activity.llm_ledger && <section><div className="sectionHeadingRow"><SectionTitle label="Model activity" title="LLM call ledger" /><OriginBadge origin="llm" /></div><LedgerPanel runId={runId} module={module} ledger="llm" /></section>}
      {!!activity.tts_variants?.length && <section><div className="sectionHeadingRow"><SectionTitle label="Synthesis activity" title="TTS request ledger" /><div className="activityOriginControl"><OriginBadge origin="model" /><select value={ttsVariant} onChange={(event) => setTtsVariant(event.target.value)}>{activity.tts_variants.map((variant: string) => <option key={variant} value={variant}>{variant}</option>)}</select></div></div>{ttsVariant && <LedgerPanel runId={runId} module={ttsVariant} ledger="tts" />}</section>}
      {activity.log_stage && <section><SectionTitle label="Orchestration" title={`${humanize(activity.log_stage)} stage log`} /><LogsPanel runId={runId} /></section>}
    </div>
  );
}

function DiagnosticsView({ runId, modules }: { runId: string; modules: ModuleInfo[] }) {
  const [section, setSection] = useState("activity");
  return (
    <>
      <ViewHeading eyebrow="Run utilities" title="Run diagnostics" summary="Run-wide activity, the complete safe artifact tree, historical configuration, and local review notes." helpKey="run_diagnostics" />
      <SubNav value={section} onChange={setSection} items={[{ key: "activity", label: "Activity", helpKey: "module_activity" }, { key: "files", label: "All artifacts", helpKey: "module_artifacts" }, { key: "config", label: "Configuration", helpKey: "module_config" }, { key: "notes", label: "Review notes" }]} />
      {section === "activity" && <ActivityView runId={runId} modules={modules} embedded />}
      {section === "files" && <FilesView runId={runId} embedded />}
      {section === "config" && <ConfigView runId={runId} embedded />}
      {section === "notes" && <ReviewNotesPanel runId={runId} />}
    </>
  );
}

function CopyField({ label, value, empty, multiline = false }: { label: string; value: string; empty?: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);
  const has = value.trim().length > 0;
  return (
    <div className="copyField">
      <div className="copyFieldHead">
        <span className="sectionLabel">{label}</span>
        <button className="textButton" disabled={!has} onClick={() => {
          navigator.clipboard?.writeText(value).catch(() => {});
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }}>{copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}</button>
      </div>
      {has
        ? <pre className={`copyFieldBody ${multiline ? "" : "single"}`}>{value}</pre>
        : <div className="copyFieldEmpty">{empty || "Not generated"}</div>}
    </div>
  );
}

function PublishKit({ detail }: { detail: RunDetail }) {
  const runId = detail.index.run_id;
  const final = useModule(runId, "metadata_finalizer");
  const draft = useModule(runId, "metadata_creator");
  const visuals = useModule(runId, "visuals");
  const voiceover = useModule(runId, "voiceover");
  const meta = (final.data?.youtube_metadata && Object.keys(final.data.youtube_metadata).length ? final.data.youtube_metadata : draft.data?.youtube_metadata) || {};
  const video = visuals.data?.final_video;
  const audio = voiceover.data?.variants?.[0]?.audio_path;
  const titleOptions: Json[] = meta.title_options || [];
  const title = titleOptions.map((option: Json) => typeof option === "string" ? option : option?.title).find(Boolean) || "";
  const description = String(meta.description || "");
  const tags = (meta.tags || []).join(", ");
  const chapters = (meta.chapters || [])
    .map((chapter: Json) => `${formatDuration(chapter.start_seconds ?? chapter.start ?? 0)} ${chapter.label || chapter.title || chapter.name || ""}`.trim())
    .join("\n");
  const thumbs: Json[] = meta.thumbnail_concepts || [];
  return (
    <section className="publishKit">
      <div className="sectionHeading"><span className="sectionLabel">Publish kit</span><small>Everything for upload — media plus copy-paste metadata</small></div>
      <div className="publishMedia">
        <figure>
          <figcaption><Film size={13} /> Episode video</figcaption>
          {video ? <video controls preload="metadata" src={mediaUrl(video)} /> : <EmptyState label={detail.index.metrics?.final_video_available ? "Rendered video not found" : "No episode rendered yet"} />}
        </figure>
        {audio && <figure><figcaption><AudioLines size={13} /> Voiceover audio</figcaption><audio controls preload="metadata" src={mediaUrl(audio)} /></figure>}
      </div>
      <div className="publishMeta">
        <CopyField label="Title" value={title} empty="No title options were generated." />
        <CopyField label="Description" value={description} empty="No description was generated for this run." multiline />
        <CopyField label="Tags" value={tags} empty="No tags were generated." />
        <CopyField label="Chapters" value={chapters} empty="No chapters were generated." multiline />
      </div>
      {titleOptions.length > 1 && (
        <div className="titleAlternates">
          <span className="sectionLabel">Alternate titles</span>
          {titleOptions.slice(1).map((option: Json, index: number) => {
            const text = typeof option === "string" ? option : option?.title;
            return text ? <CopyField key={index} label={`Option ${index + 2}`} value={String(text)} /> : null;
          })}
        </div>
      )}
      {thumbs.length > 0 && (
        <div className="thumbConcepts">
          <span className="sectionLabel">Thumbnail concepts</span>
          <div className="thumbConceptGrid">
            {thumbs.map((thumb: Json, index: number) => (
              <div key={index} className="thumbConcept">
                <strong>{thumb.headline || thumb.text || thumb.overlay_text || thumb.concept || `Concept ${index + 1}`}</strong>
                <p>{thumb.description || thumb.visual || thumb.visual_description || thumb.rationale || ""}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function OverviewView({ detail, onView }: { detail: RunDetail; onView: (view: RunViewKey) => void }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const script = useModule(detail.index.run_id, "script_generation");
  const selection = useModule(detail.index.run_id, "editorial_selection");
  const direction = script.data?.curated?.episode_direction || {};
  const stories = selection.data?.curated?.selected_stories || [];
  const stages = ["ingestion", "content", "voiceover", "visuals"];

  return (
    <>
      <ViewHeading
        eyebrow="Run at a glance"
        title="Production overview"
        summary="The editorial promise, stage health, and persisted outputs for this run."
        helpKey="overview"
        mode={mode}
        onMode={setMode}
      />
      {mode === "raw" ? (
        <RawArtifactReader runId={detail.index.run_id} sources={[
          { label: "Run context", path: "run_context.json" },
          { label: "Run state", path: "orchestration/run_state.json" },
          { label: "Content stage result", path: "orchestration/content_stage_result.json" },
          { label: "Visuals stage result", path: "orchestration/visuals_stage_result.json" },
        ]} />
      ) : (
        <div className="overviewLayout">
          <PublishKit detail={detail} />

          <section className="editorialBrief">
            <span className="sectionLabel">Episode promise</span>
            <h3>{direction.viewer_promise || direction.episode_thesis || "No episode direction was persisted."}</h3>
            {direction.episode_connection_reason && <p>{direction.episode_connection_reason}</p>}
            {!!stories.length && (
              <ol className="slateIndex">
                {stories.map((story: Json, index: number) => (
                  <li key={story.story_id}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div><strong>{story.story_title}</strong><small>{humanize(story.role || "story")}</small></div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <div className="overviewCommand"><button className="secondaryButton" onClick={() => onView("workflow")}><Workflow size={16} /> Inspect stage workflow</button></div>

          {(detail.index.failure_reason || detail.index.problems?.length > 0) && (
            <section className="attentionBand">
              <CircleAlert size={18} />
              <div><strong>Needs attention</strong><p>{detail.index.failure_reason || detail.index.problems.join(" ")}</p></div>
            </section>
          )}

          <section className="moduleLedger">
            <div className="sectionHeading"><span className="sectionLabel">Persisted work</span><h3>Module ledger</h3></div>
            {stages.map((stage) => {
              const modules = detail.modules.filter((module) => module.stage === stage);
              if (!modules.length) return null;
              return (
                <div className="moduleGroup" key={stage}>
                  <div className="moduleGroupLabel">{humanize(stage)}</div>
                  <div>
                    {modules.map((module) => <ModuleLedgerRow key={`${stage}-${module.name}`} module={module} />)}
                  </div>
                </div>
              );
            })}
          </section>
        </div>
      )}
    </>
  );
}

function ModuleLedgerRow({ module }: { module: ModuleInfo }) {
  const metrics = Object.entries(module.summary || {}).filter(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value)).slice(0, 3);
  return (
    <div className="moduleLedgerRow">
      <div><strong>{humanize(module.name)}</strong><small>{module.path}</small></div>
      <div className="moduleMetrics">
        {metrics.map(([key, value]) => <span key={key}><b>{humanize(key)}</b> {displayValue(value)}</span>)}
      </div>
      {module.reused && <span className="reuseLabel">Reused</span>}
      <StatusChip status={module.status} />
    </div>
  );
}

function RecordLineageView({ runId }: { runId: string }) {
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState("all");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Json>(null);
  const [selectedRef, setSelectedRef] = useState("");
  const [detail, setDetail] = useState<Json>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const limit = 30;

  useEffect(() => {
    setOffset(0);
  }, [query, outcome, runId]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      const params = new URLSearchParams({ search: query, outcome, offset: String(offset), limit: String(limit) });
      fetchJson(`/api/runs/${encodeURIComponent(runId)}/records?${params}`)
        .then((next: Json) => {
          if (cancelled) return;
          setPage(next);
          setError("");
          const rows = (next.records || []) as RecordRowData[];
          if (!rows.some((record) => record.record_ref === selectedRef)) setSelectedRef(rows[0]?.record_ref || "");
        })
        .catch((err) => !cancelled && setError(errorMessage(err)))
        .finally(() => !cancelled && setLoading(false));
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [runId, query, outcome, offset]);

  useEffect(() => {
    if (!selectedRef) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetail(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/records/${encodeURIComponent(selectedRef)}`)
      .then((next) => !cancelled && setDetail(next))
      .catch((err) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setDetailLoading(false));
    return () => { cancelled = true; };
  }, [runId, selectedRef]);

  const counts = page?.counts || {};
  const outcomeOrder = ["all", "selected", "reserve", "rejected", "filtered", "quarantined", "mapped", "triaged", "prepared", "unresolved"];
  const outcomes = outcomeOrder.filter((key) => key === "all" || counts[key]);
  return (
    <>
      <ViewHeading eyebrow="Source provenance" title="Record lineage" summary="Follow one collected article through every module that transformed, judged, selected, narrated, voiced, or visualized it." helpKey="record_lineage" />
      <div className="lineageToolbar">
        <FilterBar value={query} onChange={setQuery} placeholder="Search title, source, record key, or story" />
        <div className="outcomeFilters">
          {outcomes.map((key) => <button key={key} className={outcome === key ? "active" : ""} title={`Show records whose latest production outcome is ${humanize(key)}.`} onClick={() => setOutcome(key)}>{humanize(key)} <span>{counts[key] || 0}</span></button>)}
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      <div className="recordLineageLayout">
        <aside className="recordDirectory">
          <div className="recordDirectoryHead"><span>{page?.total || 0} records</span><small>{offset + 1}-{Math.min(offset + limit, page?.total || 0)}</small></div>
          {loading ? <Loading label="Tracing records" /> : (page?.records || []).map((record: RecordRowData) => (
            <button key={record.record_ref} className={selectedRef === record.record_ref ? "active" : ""} onClick={() => setSelectedRef(record.record_ref)}>
              <div><StatusChip status={record.outcome} /><small>{record.source}</small></div>
              <strong>{record.title || "Untitled record"}</strong>
              <span>{humanize(record.latest_step)}{record.story_title ? ` / ${record.story_title}` : ""}</span>
            </button>
          ))}
          {!loading && !page?.records?.length && <EmptyState label="No matching records" />}
          <div className="paginationBar">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <button disabled={page?.next_offset == null} onClick={() => setOffset(page.next_offset)}>Next</button>
          </div>
        </aside>
        <section className="recordTrace">
          {detailLoading ? <Loading label="Building record trace" /> : detail ? <LineageDetail data={detail} runId={runId} /> : <EmptyState label="Select a record to inspect its production history" />}
        </section>
      </div>
    </>
  );
}

function LineageDetail({ data, runId }: { data: Json; runId: string }) {
  const [selectedStep, setSelectedStep] = useState(data.stages?.[0]?.key || "news_collection");
  const [mode, setMode] = useState<ViewMode>("read");
  useEffect(() => {
    setSelectedStep(data.stages?.[0]?.key || "news_collection");
    setMode("read");
  }, [data.record?.record_ref]);
  const step = (data.stages || []).find((item: Json) => item.key === selectedStep) || data.stages?.[0];
  const groups = ["ingestion", "content", "voiceover", "visuals"].map((stage) => {
    const steps = (data.stages || []).filter((item: Json) => item.stage === stage);
    return { stage, reached: steps.filter((item: Json) => item.status !== "not_reached").length, total: steps.length };
  }).filter((group) => group.total);
  const rawSources = (step?.raw_sources || []).filter((source: Json) => /\.[A-Za-z0-9]+$/.test(source.path || ""));
  return (
    <div className="lineageDetail">
      <header className="lineageRecordHeader">
        <div><div className="runStatusLine"><StatusChip status={data.record?.outcome} /><span>{data.record?.source}</span><span>{data.record?.record_key || data.record?.record_id}</span></div><h2>{data.record?.title || "Untitled record"}</h2><p>{data.record?.story_title || "This record did not become a mapped story."}</p></div>
        <div className="traceCount"><strong>{data.reached_count}</strong><span>of {data.stage_count} steps reached</span></div>
      </header>
      <div className="lineageStageSummary">
        {groups.map((group, index) => <div key={group.stage}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{humanize(group.stage)}</strong><small>{group.reached} of {group.total} steps</small></div></div>)}
      </div>
      <div className="lineageStepLayout">
        <aside className="lineageStepList">
          {(data.stages || []).map((item: Json, index: number) => (
            <button key={item.key} className={selectedStep === item.key ? "active" : ""} onClick={() => setSelectedStep(item.key)}>
              <span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.label}</strong><small>{humanize(item.stage)}</small></div><StatusChip status={item.status} />
            </button>
          ))}
        </aside>
        {step && (
          <section className="lineageStepData">
            <header><div><span className="sectionLabel">{humanize(step.stage)} module</span><h3>{step.label}</h3><p>{step.explanation}</p><OriginBadge origin={step.generation?.primary_origin || "deterministic"} /></div><ModeSwitch mode={mode} onChange={setMode} /></header>
            {mode === "raw" ? <RawArtifactReader runId={runId} sources={rawSources} /> : (
              <>
                <div className="lineagePurpose"><ListTree size={17} /><span>{step.purpose}</span></div>
                <GenerationMap definition={step.generation as GenerationDefinition} compact />
                {["llm", "mixed"].includes(step.generation?.primary_origin) && step.status !== "not_reached" && (
                  <ProvenanceMatches
                    runId={runId}
                    module={step.key}
                    recordKey={data.record?.record_key || data.record?.record_id}
                    storyId={data.record?.story_id}
                    sectionId={step.data?.sections?.[0]?.section_id || step.data?.chapters?.[0]?.section_id}
                  />
                )}
                {step.data && Object.keys(step.data).length ? <ReadableObject value={step.data} /> : <EmptyState label="This module produced no record-specific data" />}
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

function IntakeView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("collection");
  const moduleName = section === "collection" ? "news_collection" : section === "evidence" ? "evidence_prep" : "editorial_triage";
  const module = useModule(runId, moduleName);
  const curated = module.data?.curated || {};
  const rawSources = section === "collection"
    ? [{ label: "Raw records", path: "news_collection/raw_records.json" }, { label: "Candidate ledger", path: "news_collection/candidate_ledger.json" }, { label: "Result envelope", path: "news_collection/news_collection_result.json" }]
    : section === "evidence"
      ? [{ label: "Prepared records", path: "evidence_prep/prepared_records.json" }, { label: "Decision ledger", path: "evidence_prep/decision_ledger.json" }, { label: "Result envelope", path: "evidence_prep/evidence_prep_result.json" }]
      : [{ label: "Triage decisions", path: "editorial_triage/decisions.json" }, { label: "Result envelope", path: "editorial_triage/editorial_triage_result.json" }, { label: "LLM calls", path: "editorial_triage/llm_calls.jsonl" }];
  return (
    <>
      <ViewHeading eyebrow="Source desk" title="Intake and triage" summary="What entered the pipeline, what survived preparation, and why each record moved forward." mode={mode} onMode={setMode} />
      <SubNav value={section} onChange={setSection} items={[
        { key: "collection", label: "Collection" },
        { key: "evidence", label: "Evidence prep" },
        { key: "triage", label: "Editorial triage" },
      ]} />
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={rawSources} /> : module.loading ? <Loading label="Opening intake data" /> : module.error ? <ErrorBanner message={module.error} /> : (
        <>
          {section === "collection" && <CollectionReader data={curated} />}
          {section === "evidence" && <EvidenceReader data={curated} />}
          {section === "triage" && <TriageReader data={curated} />}
        </>
      )}
    </>
  );
}

function CollectionReader({ data }: { data: Json }) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(40);
  const records = (data.records || []).filter((record: Json) => `${record.title} ${record.source} ${record.excerpt}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="readerStack">
      <MetricBand items={[
        ["Collected", data.stats?.total_records],
        ["Source groups", `${data.stats?.successful_source_group_count || 0} / ${data.stats?.enabled_source_group_count || 0}`],
        ["Elapsed", formatDuration(data.stats?.elapsed_seconds)],
        ["Run status", humanize(data.stats?.status || "unknown")],
      ]} />
      <section className="dataSection">
        <SectionTitle label="Source health" title="Collectors and feeds" />
        <div className="sourceGroupList">
          {(data.source_groups || []).map((group: Json) => (
            <details className="sourceGroup" key={group.name}>
              <summary>
                <div><strong>{humanize(group.name)}</strong><small>{formatNumber(group.collected_count)} records from {group.source_count} sources</small></div>
                <span>{group.failed_source_count ? `${group.failed_source_count} failed` : "All sources reached"}</span>
                <StatusChip status={group.status} />
              </summary>
              <div className="sourceRows">
                {(group.sources || []).map((source: Json) => (
                  <div className="sourceRow" key={source.name}>
                    <div><strong>{humanize(source.name)}</strong><small>{source.notes?.[0] || "No collector notes"}</small></div>
                    <span>{formatNumber(source.collected_count)} collected</span>
                    <StatusChip status={source.status} />
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      </section>
      <section className="dataSection">
        <SectionTitle label="Collected material" title={`${formatNumber(records.length)} records`} />
        <FilterBar value={query} onChange={setQuery} placeholder="Filter headlines or sources" />
        <div className="recordList">
          {records.slice(0, limit).map((record: Json) => <RecordRow key={record.record_key} record={record} />)}
        </div>
        {limit < records.length && <button className="textButton" onClick={() => setLimit(limit + 40)}>Show 40 more</button>}
      </section>
    </div>
  );
}

function RecordRow({ record }: { record: Json }) {
  return (
    <article className="recordRow">
      <div className="recordMeta"><span>{record.source}</span><time>{shortDate(record.published_at)}</time></div>
      <div>
        <h4>{record.url ? <a href={safeUrl(record.url)} target="_blank" rel="noreferrer">{record.title}<ExternalLink size={13} /></a> : record.title}</h4>
        <p>{record.excerpt || "No summary was persisted."}</p>
      </div>
      <div className="recordFlags"><span>{humanize(record.source_group)}</span><span>{humanize(record.content_status || record.source_relationship)}</span></div>
    </article>
  );
}

function EvidenceReader({ data }: { data: Json }) {
  const [decision, setDecision] = useState("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(30);
  const rows = (data.decisions || []).filter((row: Json) => (decision === "all" || row.decision === decision) && `${row.title} ${row.source}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="readerStack">
      <MetricBand items={[
        ["Input", data.stats?.input_record_count],
        ["Prepared", data.stats?.prepared_record_count],
        ["Excluded", data.stats?.excluded_count],
        ["Duplicates", data.stats?.duplicate_count],
      ]} />
      <section className="dataSection">
        <SectionTitle label="Preparation funnel" title="Decisions by source group" />
        <div className="comparisonTable">
          <div className="tableHeader"><span>Source group</span><span>Input</span><span>Prepared</span><span>Excluded</span></div>
          {(data.source_groups || []).map((group: Json) => (
            <div className="tableRow" key={group.name}><strong>{humanize(group.name)}</strong><span>{group.input}</span><span>{group.prepared}</span><span>{group.excluded}</span></div>
          ))}
        </div>
      </section>
      <section className="dataSection">
        <SectionTitle label="Reversible ledger" title={`${formatNumber(rows.length)} decisions`} />
        <div className="filterRow">
          <SubNav value={decision} onChange={setDecision} compact items={[
            { key: "all", label: "All" },
            { key: "candidate", label: `Candidates ${data.decision_counts?.candidate || 0}` },
            { key: "hard_reject", label: `Excluded ${data.decision_counts?.hard_reject || 0}` },
            { key: "duplicate", label: `Duplicates ${data.decision_counts?.duplicate || 0}` },
          ]} />
          <FilterBar value={query} onChange={setQuery} placeholder="Filter decisions" />
        </div>
        <div className="decisionList">
          {rows.slice(0, limit).map((row: Json, index: number) => (
            <div className="decisionRow" key={`${row.record_key}-${index}`}>
              <StatusChip status={row.decision} />
              <div><strong>{row.title || row.record_key}</strong><small>{row.source} / {humanize(row.source_group)}</small></div>
              <span>{(row.reason_codes || []).map(humanize).join(", ") || humanize(row.decision_owner || "recorded")}</span>
            </div>
          ))}
        </div>
        {limit < rows.length && <button className="textButton" onClick={() => setLimit(limit + 30)}>Show 30 more</button>}
      </section>
    </div>
  );
}

function TriageReader({ data }: { data: Json }) {
  const [action, setAction] = useState("advance");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(24);
  const rows = (data.decisions || []).filter((row: Json) => (action === "all" || row.recommended_action === action) && `${row.title} ${row.reason} ${row.source}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="readerStack">
      <MetricBand items={[
        ["Reviewed", data.stats?.decision_count],
        ["Advanced", data.action_counts?.advance],
        ["Reserved", data.action_counts?.reserve],
        ["Quarantined", data.action_counts?.quarantine],
      ]} />
      <section className="dataSection">
        <SectionTitle label="Semantic review" title={`${formatNumber(rows.length)} editorial decisions`} />
        <div className="filterRow">
          <SubNav value={action} onChange={setAction} compact items={[
            { key: "advance", label: "Advance" },
            { key: "reserve", label: "Reserve" },
            { key: "quarantine", label: "Quarantine" },
            { key: "all", label: "All" },
          ]} />
          <FilterBar value={query} onChange={setQuery} placeholder="Filter triage decisions" />
        </div>
        <div className="triageList">
          {rows.slice(0, limit).map((row: Json) => (
            <details className="triageRow" key={row.record_key}>
              <summary>
                <StatusChip status={row.recommended_action} />
                <div><strong>{row.title || row.record_key}</strong><small>{row.source} / {humanize(row.likely_content_type)}</small></div>
                <span>{formatPercent(row.confidence)}</span>
              </summary>
              <div className="triageBody">
                <p>{row.reason}</p>
                <dl className="inlineFacts">
                  <Fact label="Relevance" value={row.topic_relevance} />
                  <Fact label="News value" value={row.newsworthiness} />
                  <Fact label="Audience" value={row.audience_value} />
                  <Fact label="Usability" value={row.content_usability} />
                  <Fact label="Novelty" value={row.novelty} />
                </dl>
                {!!row.possible_story_keys?.length && <p className="keywordLine">Possible threads: {row.possible_story_keys.join(" / ")}</p>}
              </div>
            </details>
          ))}
        </div>
        {limit < rows.length && <button className="textButton" onClick={() => setLimit(limit + 24)}>Show 24 more</button>}
      </section>
    </div>
  );
}

function StoriesView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("selected");
  const [query, setQuery] = useState("");
  const selection = useModule(runId, "editorial_selection");
  const mapping = useModule(runId, "story_mapping");
  const packaging = useModule(runId, "video_packaging");
  const selected = selection.data?.curated?.selected_stories || [];
  const reserve = selection.data?.curated?.reserve_stories || [];
  const rejected = selection.data?.curated?.rejected_stories || [];
  const mapped = mapping.data?.curated?.stories || [];
  const current = section === "selected" ? selected : section === "reserve" ? reserve : section === "mapped" ? mapped : rejected;
  const visible = current.filter((story: Json) => `${story.story_title} ${story.one_sentence_story} ${story.reason}`.toLowerCase().includes(query.toLowerCase()));
  const context = packaging.data?.curated?.editorial_context || selection.data?.curated || {};

  return (
    <>
      <ViewHeading eyebrow="Editorial slate" title="Stories and selection" summary="The episode order, source basis, reserves, and decisions behind the final slate." mode={mode} onMode={setMode} />
      <SubNav value={section} onChange={setSection} items={[
        { key: "selected", label: `Selected ${selected.length}` },
        { key: "reserve", label: `Reserve ${reserve.length}` },
        { key: "mapped", label: `Story map ${mapped.length}` },
        { key: "rejected", label: `Rejected ${rejected.length}` },
      ]} />
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={[
        { label: "Story map", path: "story_mapping/stories.json" },
        { label: "Editorial slate", path: "editorial_selection/editorial_slate.json" },
        { label: "Video packet", path: "video_packaging/video_packet.json" },
      ]} /> : selection.loading || mapping.loading ? <Loading label="Opening editorial slate" /> : (
        <div className="storiesLayout">
          {section === "selected" && (
            <section className="slateBrief">
              <span className="sectionLabel">Editorial shape</span>
              <h3>{humanize(context.episode_shape || "curated roundup")}</h3>
              <p>{context.episode_thesis || context.ordering_rationale || "No ordering rationale was persisted."}</p>
            </section>
          )}
          {section !== "selected" && <FilterBar value={query} onChange={setQuery} placeholder="Filter stories" />}
          <div className={section === "selected" ? "selectedStories" : "storyDirectory"}>
            {visible.map((story: Json, index: number) => section === "selected"
              ? <SelectedStory key={story.story_id} story={story} index={index} />
              : <DirectoryStory key={story.story_id || index} story={story} />)}
            {!visible.length && <EmptyState label="No stories in this view" />}
          </div>
        </div>
      )}
    </>
  );
}

function SelectedStory({ story, index }: { story: Json; index: number }) {
  return (
    <article className="selectedStory">
      <div className="storyNumber">{String(index + 1).padStart(2, "0")}</div>
      <div className="storyCopy">
        <div className="storyLine"><span>{humanize(story.role || "story")}</span><span>{story.primary_entity || story.owning_org}</span><span>{formatPercent(story.confidence)}</span></div>
        <h3>{story.story_title}</h3>
        <p className="storyDek">{story.one_sentence_story || story.why_it_matters}</p>
        <div className="editorialReasoning">
          <div><strong>Why it made the slate</strong><p>{story.selection_reason || "No selection rationale was persisted."}</p></div>
          <div><strong>Viewer payoff</strong><p>{story.viewer_payoff || story.why_it_matters || "No viewer payoff was persisted."}</p></div>
        </div>
        <SourceLinks records={story.records || []} />
      </div>
    </article>
  );
}

function DirectoryStory({ story }: { story: Json }) {
  return (
    <details className="directoryStory">
      <summary>
        <div><strong>{story.story_title || story.story_id}</strong><small>{story.primary_entity || humanize(story.selection_stage || story.story_type || "story")}</small></div>
        <span>{story.record_count ? `${story.record_count} source${story.record_count === 1 ? "" : "s"}` : formatPercent(story.confidence)}</span>
      </summary>
      <div className="directoryBody">
        <p>{story.one_sentence_story || story.reason || story.why_it_matters}</p>
        {story.selection_reason && <p><strong>Decision:</strong> {story.selection_reason}</p>}
        <SourceLinks records={story.records || []} />
      </div>
    </details>
  );
}

function SourceLinks({ records }: { records: Json[] }) {
  if (!records.length) return null;
  return (
    <div className="sourceLinks">
      {records.map((record: Json) => (
        <a key={record.record_key || record.url} href={safeUrl(record.url)} target="_blank" rel="noreferrer">
          <span>{record.source}</span><strong>{record.title}</strong><ExternalLink size={13} />
        </a>
      ))}
    </div>
  );
}

function ScriptView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("copy");
  const script = useModule(runId, "script_generation");
  const curated = script.data?.curated || {};
  const sections = curated.sections || [];
  return (
    <>
      <ViewHeading eyebrow="Writing desk" title="Script package" summary="The clean narration, beat construction, delivery direction, and review outcome." mode={mode} onMode={setMode} />
      <SubNav value={section} onChange={setSection} items={[
        { key: "copy", label: "Reading copy" },
        { key: "beats", label: "Beat sheet" },
        { key: "direction", label: "Direction and review" },
      ]} />
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={[
        { label: "Script package", path: "script_generation/script_package.json" },
        { label: "Canonical result", path: "script_generation/script_generation_result.json" },
        { label: "Full script text", path: "script_generation/full_script.txt" },
      ]} /> : script.loading ? <Loading label="Opening script" /> : script.error ? <ErrorBanner message={script.error} /> : (
        <div className="scriptLayout">
          <MetricBand items={[
            ["Words", curated.stats?.total_word_count],
            ["Sections", sections.length],
            ["Beats", curated.stats?.beat_count],
            ["Estimated", formatDuration(curated.stats?.estimated_duration_seconds)],
          ]} />
          {section === "copy" && <ScriptReading sections={sections} />}
          {section === "beats" && <BeatSheet sections={sections} />}
          {section === "direction" && <ScriptDirection data={curated} />}
        </div>
      )}
    </>
  );
}

function ScriptReading({ sections }: { sections: Json[] }) {
  return (
    <div className="readingPage">
      {sections.map((section: Json, index: number) => (
        <article className="scriptSection" key={section.section_id}>
          <aside><span>{String(index + 1).padStart(2, "0")}</span><small>{humanize(section.section_type)}</small></aside>
          <div>
            <h3>{section.story_title || humanize(section.section_type || section.section_id)}</h3>
            <p>{sectionNarration(section)}</p>
            <footer>{formatNumber(section.word_count)} words / {formatDuration(section.estimated_seconds)}</footer>
          </div>
        </article>
      ))}
      {!sections.length && <EmptyState label="No script sections available" />}
    </div>
  );
}

function BeatSheet({ sections }: { sections: Json[] }) {
  return (
    <div className="beatSheet">
      {sections.map((section: Json) => (
        <details className="beatSection" key={section.section_id} open={section.section_type === "intro"}>
          <summary><div><span>{humanize(section.section_type)}</span><strong>{section.story_title || humanize(section.section_id)}</strong></div><small>{(section.beats || []).length} beats / {formatNumber(section.word_count)} words</small></summary>
          <div className="beatRows">
            {(section.beats || []).map((beat: Json) => (
              <article className="beatItem" key={beat.beat_id}>
                <div className="beatIndex"><span>{String(beat.beat_order || 0).padStart(2, "0")}</span><small>{humanize(beat.beat_function || beat.beat_type)}</small></div>
                <div className="beatNarration"><p>{beat.narration_text || beat.text}</p><small>{formatNumber(beat.word_count)} words / {formatDuration(beat.estimated_seconds)}</small></div>
                <div className="beatDirection"><strong>Visual</strong><p>{beat.visual_goal || beat.visual_brief?.purpose || "No visual direction"}</p><strong>Delivery</strong><p>{beat.delivery_direction?.performance_intent || "No delivery note"}</p></div>
              </article>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function ScriptDirection({ data }: { data: Json }) {
  const direction = data.episode_direction || {};
  const review = data.review || {};
  return (
    <div className="directionLayout">
      <section className="directionLead">
        <span className="sectionLabel">Episode thesis</span>
        <h3>{direction.episode_thesis || "No episode thesis persisted."}</h3>
        <p>{direction.viewer_promise}</p>
        <dl className="directionFacts">
          <Fact label="Hook" value={direction.hook_strategy} />
          <Fact label="Pacing" value={direction.pacing_strategy} />
          <Fact label="Connection" value={direction.episode_connection_reason} />
        </dl>
      </section>
      <section className="dataSection">
        <SectionTitle label="Story treatment" title="Writing briefs" />
        <div className="briefList">
          {(direction.story_briefs || []).map((brief: Json, index: number) => (
            <details key={brief.story_id}>
              <summary><span>{String(index + 1).padStart(2, "0")}</span><strong>{brief.story_promise || brief.story_id}</strong><small>{humanize(brief.story_engine)}</small></summary>
              <div><p><b>Hook:</b> {brief.hook_idea}</p><p><b>Tension:</b> {brief.tension}</p><p><b>Payoff:</b> {brief.reveal_or_payoff}</p><p><b>Narrator take:</b> {brief.narrator_take}</p></div>
            </details>
          ))}
        </div>
      </section>
      <section className="reviewSummary">
        <div><span className="sectionLabel">Editorial review</span><h3>{review.revision_count ? `${review.revision_count} revisions applied` : "Approved without rewrite"}</h3></div>
        <dl><Fact label="Review calls" value={review.review_call_count} /><Fact label="Revision cap" value={review.max_revision_passes} /><Fact label="Fingerprint" value={shortFingerprint(data.fingerprint)} /></dl>
      </section>
    </div>
  );
}

function MetadataView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("titles");
  const finalized = useModule(runId, "metadata_finalizer");
  const created = useModule(runId, "metadata_creator");
  const curated = finalized.data?.curated?.youtube_metadata ? finalized.data.curated : created.data?.curated || {};
  const metadata = curated.youtube_metadata || {};
  return (
    <>
      <ViewHeading eyebrow="Packaging desk" title="Viewer metadata" summary="Title strategy, thumbnail direction, description, chapters, tags, and source links." mode={mode} onMode={setMode} />
      <SubNav value={section} onChange={setSection} items={[
        { key: "titles", label: `Titles ${(metadata.title_options || []).length}` },
        { key: "thumbnails", label: `Thumbnails ${(metadata.thumbnail_concepts || []).length}` },
        { key: "description", label: "Description and chapters" },
      ]} />
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={[
        { label: "Final metadata", path: "metadata_finalizer/metadata_package.json" },
        { label: "Metadata draft", path: "metadata_creator/metadata_package.json" },
        { label: "YouTube metadata", path: "metadata_finalizer/youtube_metadata.json" },
      ]} /> : finalized.loading || created.loading ? <Loading label="Opening metadata" /> : (
        <div className="metadataLayout">
          {section === "titles" && <TitleOptions options={metadata.title_options || metadata.titles || []} />}
          {section === "thumbnails" && <ThumbnailConcepts concepts={metadata.thumbnail_concepts || []} textOptions={metadata.thumbnail_text_options || []} blocked={metadata.blocked_title_angles || []} />}
          {section === "description" && <DescriptionReader metadata={metadata} />}
        </div>
      )}
    </>
  );
}

function TitleOptions({ options }: { options: Json[] }) {
  return (
    <section className="titleOptions">
      <SectionTitle label="Candidate set" title="Title options" />
      {options.map((option: Json, index: number) => {
        const title = typeof option === "string" ? option : option.title || option.text;
        return (
          <article key={`${title}-${index}`}>
            <span className="optionNumber">{String(index + 1).padStart(2, "0")}</span>
            <div><h3>{title}</h3>{typeof option === "object" && <><p>{option.why_it_works}</p><small>{humanize(option.angle_strategy)} / click potential {humanize(option.click_potential)} / accuracy risk {humanize(option.accuracy_risk)}</small></>}</div>
          </article>
        );
      })}
      {!options.length && <EmptyState label="No title options available" />}
    </section>
  );
}

function ThumbnailConcepts({ concepts, textOptions, blocked }: { concepts: Json[]; textOptions: string[]; blocked: string[] }) {
  return (
    <div className="thumbnailLayout">
      <section className="thumbnailTexts"><SectionTitle label="Overlay copy" title="Short text options" /><div>{textOptions.map((text) => <span key={text}>{text}</span>)}</div></section>
      <section className="conceptList">
        {concepts.map((concept: Json, index: number) => (
          <article key={concept.concept_id || index}>
            <div className="conceptIndex"><ImageIcon size={19} /><span>{String(index + 1).padStart(2, "0")}</span></div>
            <div className="conceptBody"><span className="sectionLabel">{concept.text_overlay}</span><h3>{concept.concept_name}</h3><p className="conceptHook">{concept.visual_hook}</p><dl><Fact label="Composition" value={concept.composition} /><Fact label="Color" value={concept.color_direction} /><Fact label="Tone" value={concept.emotional_tone} /></dl><details><summary>Generation brief</summary><p>{concept.generation_prompt}</p></details></div>
          </article>
        ))}
      </section>
      {!!blocked.length && <section className="blockedAngles"><SectionTitle label="Accuracy guardrails" title="Blocked title angles" /><ul>{blocked.map((item, index) => <li key={index}>{item}</li>)}</ul></section>}
    </div>
  );
}

function DescriptionReader({ metadata }: { metadata: Json }) {
  return (
    <div className="descriptionLayout">
      <section className="descriptionCopy"><SectionTitle label="YouTube description" title="Final copy" /><div>{(metadata.description_draft || metadata.description || "No description available.").split("\n").map((line: string, index: number) => line ? <p key={index}>{linkifyLine(line)}</p> : <br key={index} />)}</div></section>
      <section className="chapterList"><SectionTitle label="Audio timed" title="Chapters" />{(metadata.chapters || []).map((chapter: Json) => <div key={chapter.section_id || chapter.timestamp}><time>{chapter.timestamp}</time><strong>{chapter.title}</strong></div>)}</section>
      <section className="tagSection"><SectionTitle label="Discovery" title="Tags" /><p>{(metadata.tags || []).join(" / ") || "No tags available."}</p></section>
    </div>
  );
}

function VoiceoverView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("timeline");
  const [variants, setVariants] = useState<Json[]>([]);
  const [variantId, setVariantId] = useState("");
  const [detail, setDetail] = useState<Json>(null);
  const [error, setError] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/voiceovers`)
      .then((data: Json) => {
        setVariants(data.voiceovers || []);
        setVariantId(data.voiceovers?.[0]?.variant_id || "");
      })
      .catch((err) => setError(errorMessage(err)));
  }, [runId]);

  useEffect(() => {
    if (!variantId) return;
    setDetail(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/voiceovers/${encodeURIComponent(variantId)}`)
      .then(setDetail)
      .catch((err) => setError(errorMessage(err)));
  }, [runId, variantId]);

  const selected = variants.find((variant) => variant.variant_id === variantId);
  const seek = (seconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = seconds;
    void audioRef.current.play();
  };
  return (
    <>
      <ViewHeading eyebrow="Voice desk" title="Narration and timing" summary="Selectable voice variants, mastered audio, section alignment, captions, and provider requests." mode={mode} onMode={setMode} />
      <div className="voiceToolbar">
        <label><span>Variant</span><select value={variantId} onChange={(event) => setVariantId(event.target.value)}>{variants.map((variant) => <option key={variant.variant_id} value={variant.variant_id}>{variant.voice || "Voice"} / {variant.model || variant.provider} / {formatDuration(variant.duration_seconds)}</option>)}</select></label>
        <SubNav value={section} onChange={setSection} compact items={[
          { key: "timeline", label: "Timeline" },
          { key: "setup", label: "Voice setup" },
          { key: "requests", label: "TTS requests" },
        ]} />
      </div>
      {error && <ErrorBanner message={error} />}
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={variantId ? [
        { label: "Voiceover package", path: `voiceover/${variantId}/voiceover_package.json` },
        { label: "Voiceover result", path: `voiceover/${variantId}/voiceover_result.json` },
        { label: "TTS ledger", path: `voiceover/${variantId}/tts_requests.jsonl` },
      ] : []} /> : !selected || !detail ? <Loading label="Opening voice package" /> : (
        <div className="voiceLayout">
          <section className="audioConsole">
            <div className="audioIdentity"><AudioLines size={22} /><div><span className="sectionLabel">{selected.provider}</span><h3>{selected.voice} / {humanize(selected.style)}</h3><p>{selected.style_description}</p></div></div>
            {selected.audio_path ? <audio ref={audioRef} controls preload="metadata" src={mediaUrl(selected.audio_path)} /> : <EmptyState label="No WAV available" />}
            <dl className="audioFacts"><Fact label="Duration" value={formatDuration(selected.duration_seconds)} /><Fact label="Model" value={selected.model} /><Fact label="Speed" value={selected.speed ? `${selected.speed}x` : "n/a"} /><Fact label="Mastering" value={selected.mastering_status} /></dl>
            <div className="captionLinks"><Captions size={15} />{selected.captions?.vtt && <a href={mediaUrl(selected.captions.vtt)} target="_blank" rel="noreferrer">VTT captions</a>}{selected.captions?.srt && <a href={mediaUrl(selected.captions.srt)} target="_blank" rel="noreferrer">SRT captions</a>}</div>
          </section>
          {section === "timeline" && <VoiceTimeline units={detail.audio_units || []} onSeek={seek} />}
          {section === "setup" && <VoiceSetup detail={detail} selected={selected} />}
          {section === "requests" && <LedgerPanel runId={runId} module={variantId} ledger="tts" />}
        </div>
      )}
    </>
  );
}

function VoiceTimeline({ units, onSeek }: { units: Json[]; onSeek: (seconds: number) => void }) {
  return (
    <section className="voiceTimeline">
      <SectionTitle label="Audio alignment" title={`${units.length} timed sections`} />
      {units.map((unit: Json, index: number) => (
        <article key={unit.audio_unit_id}>
          <button className="timeButton" title={`Play from ${formatDuration(unit.start_seconds)}`} onClick={() => onSeek(Number(unit.start_seconds || 0))}><Play size={14} />{formatDuration(unit.start_seconds)}</button>
          <div><span>{humanize(unit.section_type)}</span><h3>{unit.story_title || humanize(unit.section_id)}</h3><p>{(unit.aligned_beats || []).map((beat: Json) => beat.text).join(" ")}</p><small>{formatNumber(unit.word_count)} words / {formatDuration(unit.duration_seconds || unit.timeline_duration_seconds)} / {(unit.aligned_beats || []).length} beats</small></div>
          <span className="timelineIndex">{String(index + 1).padStart(2, "0")}</span>
        </article>
      ))}
    </section>
  );
}

function VoiceSetup({ detail, selected }: { detail: Json; selected: Json }) {
  const style = detail.style || {};
  const mastering = detail.audio?.mastering || {};
  return (
    <div className="voiceSetup">
      <section className="directionLead"><span className="sectionLabel">Performance direction</span><h3>{style.description || humanize(style.name)}</h3><p>{style.provider_settings?.instructions}</p></section>
      <section className="setupColumns">
        <div><SectionTitle label="Synthesis" title="Voice settings" /><dl className="stackedFacts"><Fact label="Provider" value={selected.provider} /><Fact label="Model" value={selected.model} /><Fact label="Voice" value={selected.voice} /><Fact label="Language" value={style.provider_settings?.language_code} /><Fact label="Speed" value={style.speed} /><Fact label="Chunks" value={selected.chunk_count} /></dl></div>
        <div><SectionTitle label="Mastering" title="Output measurements" /><dl className="stackedFacts"><Fact label="Integrated loudness" value={formatDb(mastering.output_measurement?.integrated_lufs, "LUFS")} /><Fact label="True peak" value={formatDb(mastering.output_measurement?.true_peak_db, "dB")} /><Fact label="Loudness range" value={formatDb(mastering.output_measurement?.loudness_range_lu, "LU")} /><Fact label="Sample rate" value={detail.audio?.sample_rate_hz ? `${formatNumber(detail.audio.sample_rate_hz)} Hz` : "n/a"} /></dl></div>
      </section>
    </div>
  );
}

function VisualsView({ runId }: { runId: string }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [data, setData] = useState<Json>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/visual-scenes`).then(setData).catch((err) => setError(errorMessage(err)));
  }, [runId]);

  const artDirector = data?.summary?.art_director === "bridge"
    ? "Deterministic bridge"
    : data?.summary?.art_director === "llm"
      ? "LLM art director"
      : "Not available";

  return (
    <>
      <ViewHeading eyebrow="Visual desk" title="Rendered episode" summary="The motion-graphics episode rendered from the finished voiceover, and how it was produced." mode={mode} onMode={setMode} />
      {error && <ErrorBanner message={error} />}
      {mode === "raw" ? <RawArtifactReader runId={runId} sources={[
        { label: "Visuals stage result", path: "orchestration/visuals_stage_result.json" },
      ]} /> : !data ? <Loading label="Opening the rendered episode" /> : (
        <div className="visualLayout">
          <section className="screeningRoom">
            <div className="screeningHeader"><div><span className="sectionLabel">Episode screening</span><h3>Rendered episode</h3></div></div>
            {data.final_video ? (
              <video controls preload="metadata" src={mediaUrl(data.final_video)} />
            ) : (
              <EmptyState label={data.summary?.rendered ? "Rendered video not found on disk" : "No episode has been rendered for this run"} />
            )}
          </section>
          <MetricBand items={[
            ["Status", humanize(data.status || "missing")],
            ["Art director", artDirector],
            ["Unit slice", data.summary?.units == null ? "All units" : String(data.summary?.units)],
            ["Rendered", data.summary?.rendered ? "Yes" : "No"],
          ]} />
          {data.failure_reason && <ErrorBanner message={data.failure_reason} />}
        </div>
      )}
    </>
  );
}

function ActivityView({ runId, modules, embedded = false }: { runId: string; modules: ModuleInfo[]; embedded?: boolean }) {
  const [section, setSection] = useState("logs");
  const llmModules = modules.filter((module) => module.artifacts?.some((artifact) => artifact.name === "llm_calls.jsonl"));
  const [module, setModule] = useState(llmModules[0]?.name || "script_generation");
  const [variants, setVariants] = useState<Json[]>([]);
  const [variant, setVariant] = useState("");
  useEffect(() => {
    if (section !== "tts") return;
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/voiceovers`).then((data: Json) => {
      setVariants(data.voiceovers || []);
      setVariant((current) => current || data.voiceovers?.[0]?.variant_id || "");
    }).catch(() => setVariants([]));
  }, [runId, section]);
  return (
    <>
      {!embedded && <ViewHeading eyebrow="Operations desk" title="Logs and provider calls" summary="Stage activity, model usage, complete prompts, responses, and parsing diagnostics." helpKey="module_activity" />}
      <SubNav value={section} onChange={setSection} items={[{ key: "logs", label: "Stage logs", helpKey: "module_activity" }, { key: "llm", label: "LLM calls", helpKey: "llm_ledger" }, { key: "tts", label: "TTS requests", helpKey: "tts_ledger" }]} />
      {section === "logs" && <LogsPanel runId={runId} />}
      {section === "llm" && <div className="activityLayout"><div className="activityDeskHead"><OriginBadge origin="llm" /><HelpTip helpKey="llm_ledger" /></div><label className="selectControl"><span>Module</span><select value={module} onChange={(event) => setModule(event.target.value)}>{llmModules.map((item) => <option key={item.name} value={item.name}>{humanize(item.name)}</option>)}</select></label><LedgerPanel runId={runId} module={module} ledger="llm" /></div>}
      {section === "tts" && <div className="activityLayout"><div className="activityDeskHead"><OriginBadge origin="model" /><HelpTip helpKey="tts_ledger" /></div><label className="selectControl"><span>Variant</span><select value={variant} onChange={(event) => setVariant(event.target.value)}>{variants.map((item) => <option key={item.variant_id} value={item.variant_id}>{item.voice || item.variant_id}</option>)}</select></label>{variant ? <LedgerPanel runId={runId} module={variant} ledger="tts" /> : <EmptyState label="No TTS ledger available" />}</div>}
    </>
  );
}

function LogsPanel({ runId }: { runId: string }) {
  const [stage, setStage] = useState("content");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState("");
  const [data, setData] = useState<Json>(null);
  useEffect(() => {
    const params = new URLSearchParams({ search: query, severity, tail: "1000" });
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/logs/${stage}?${params}`).then(setData).catch((err) => setData({ lines: [errorMessage(err)] }));
  }, [runId, stage, query, severity]);
  return (
    <section className="logViewer">
      <div className="logToolbar"><select value={stage} onChange={(event) => setStage(event.target.value)}>{["ingestion", "content", "voiceover", "visuals"].map((item) => <option key={item}>{item}</option>)}</select><FilterBar value={query} onChange={setQuery} placeholder="Search log" /><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">All severities</option><option value="ERROR">Errors</option><option value="WARNING">Warnings</option><option value="INFO">Info</option></select></div>
      <pre>{(data?.lines || []).join("\n")}</pre>
    </section>
  );
}

function LedgerPanel({ runId, module, ledger }: { runId: string; module: string; ledger: "llm" | "tts" }) {
  const [page, setPage] = useState<Json>(null);
  const [record, setRecord] = useState<Json>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const base = ledger === "tts" ? "tts-calls" : "llm-calls";
  const load = (offset: number) => fetchJson(`/api/runs/${encodeURIComponent(runId)}/${base}/${encodeURIComponent(module)}?offset=${offset}&limit=20`).then(setPage).catch((err) => setPage({ rows: [], errors: [errorMessage(err)], total: 0, offset: 0 }));
  useEffect(() => {
    void load(0);
    setExpanded(null);
    setRecord(null);
  }, [runId, module, base]);
  const expand = (index: number) => {
    if (expanded === index) {
      setExpanded(null);
      setRecord(null);
      return;
    }
    setExpanded(index);
    setRecord(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/${base}/${encodeURIComponent(module)}/records/${index}`).then(setRecord).catch((err) => setRecord({ error: errorMessage(err) }));
  };
  const offset = page?.offset || 0;
  return (
    <section className="ledgerViewer">
      {page?.errors?.map((message: string) => <ErrorBanner key={message} message={message} />)}
      <div className="ledgerHeader"><span>Call</span><span>Provider</span><span>Usage</span><span>Duration</span><span>Status</span></div>
      {(page?.rows || []).map((row: Json) => (
        <React.Fragment key={row.index}>
          <button className={`ledgerRow ${expanded === row.index ? "expanded" : ""}`} onClick={() => expand(row.index)}>
            <span><ChevronRight size={14} /><strong>{humanize(row.module_name || row.request_id || row.role || `record ${row.index + 1}`)}</strong></span>
            <span>{row.provider || "n/a"}<small>{row.model}</small></span>
            <span>{tokenSummary(row.usage || row.token_usage)}</span>
            <span>{formatDuration(row.duration_seconds || row.latency_seconds)}</span>
            <StatusChip status={row.status || row.response_status || "recorded"} />
          </button>
          {expanded === row.index && <CallRecord record={record} ledger={ledger} />}
        </React.Fragment>
      ))}
      {!page?.rows?.length && page && <EmptyState label={`No ${ledger.toUpperCase()} records available`} />}
      <div className="pager"><button disabled={offset <= 0} onClick={() => void load(Math.max(0, offset - 20))}>Previous</button><span>{page?.total ? `${offset + 1}-${Math.min(page.total, offset + page.rows.length)} of ${page.total}` : "0 records"}</span><button disabled={!page?.next_offset} onClick={() => void load(page.next_offset)}>Next</button></div>
    </section>
  );
}

function CallRecord({ record, ledger }: { record: Json; ledger: "llm" | "tts" }) {
  const [section, setSection] = useState(ledger === "llm" ? "prompt" : "record");
  if (!record) return <div className="callRecord"><Loading label="Opening complete record" /></div>;
  if (record.error) return <div className="callRecord"><ErrorBanner message={record.error} /></div>;
  const prompt = record.complete_prompt || record.prompt;
  const messages = record.messages || [];
  const response = record.parsed_output || record.structured_response || record.response_text;
  return (
    <div className="callRecord">
      <SubNav value={section} onChange={setSection} compact items={ledger === "llm" ? [
        { key: "prompt", label: "Prompt" }, { key: "response", label: "Response" }, { key: "raw", label: "Raw response" }, { key: "diagnostics", label: "Diagnostics" }, { key: "record", label: "Complete record" },
      ] : [{ key: "record", label: "Complete request" }]} />
      {section === "prompt" && <div className="messageStack">{prompt && <pre>{typeof prompt === "string" ? prompt : JSON.stringify(prompt, null, 2)}</pre>}{messages.map((message: Json, index: number) => <article key={index}><span>{message.role || `message ${index + 1}`}</span><pre>{typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2)}</pre></article>)}{!prompt && !messages.length && <EmptyState label="No prompt payload persisted" />}</div>}
      {section === "response" && <ReadableValue value={response} />}
      {section === "raw" && <ReadableValue value={record.raw_response ?? record.response_text ?? null} />}
      {section === "diagnostics" && <ReadableValue value={record.parsing_diagnostics ?? record.metadata ?? {}} />}
      {section === "record" && <JsonTree value={record} />}
    </div>
  );
}

function FilesView({ runId, embedded = false }: { runId: string; embedded?: boolean }) {
  const [tree, setTree] = useState<ArtifactNode[]>([]);
  const [selected, setSelected] = useState("");
  const [artifact, setArtifact] = useState<Json>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/artifact-tree`).then((data: Json) => setTree(data.tree || [])).catch((err) => setArtifact({ kind: "error", text: errorMessage(err) })).finally(() => setLoading(false));
  }, [runId]);
  useEffect(() => {
    if (!selected) return;
    setArtifact(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/artifacts?path=${encodeURIComponent(selected)}`).then(setArtifact).catch((err) => setArtifact({ kind: "error", text: errorMessage(err) }));
  }, [runId, selected]);
  return (
    <>
      {!embedded && <ViewHeading eyebrow="Artifact archive" title="Persisted files" summary="The complete read-only run directory, loaded only as files are opened." helpKey="module_artifacts" />}
      {loading ? <Loading label="Indexing run files" /> : (
        <div className="fileBrowser">
          <aside><div className="fileBrowserTitle"><Folder size={16} /><strong>Run files</strong></div>{tree.map((node) => <TreeNode key={node.path} node={node} selected={selected} onSelect={setSelected} />)}</aside>
          <section><div className="fileReaderTitle"><FileJson size={16} /><strong>{selected || "Select a file"}</strong></div><ArtifactPreview artifact={artifact} /></section>
        </div>
      )}
    </>
  );
}

function ConfigView({ runId, embedded = false }: { runId: string; embedded?: boolean }) {
  const [mode, setMode] = useState<ViewMode>("read");
  const [section, setSection] = useState("summary");
  const [data, setData] = useState<Json>(null);
  const [sourcePath, setSourcePath] = useState("");
  const [source, setSource] = useState("");
  useEffect(() => {
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/config`).then((value: Json) => {
      setData(value);
      setSourcePath(value.current_authoring?.[0]?.path || "");
    });
  }, [runId]);
  useEffect(() => {
    if (!sourcePath) return;
    fetchJson(`/api/config/source?path=${encodeURIComponent(sourcePath)}`).then((value: Json) => setSource(value.text || "")).catch((err) => setSource(errorMessage(err)));
  }, [sourcePath]);
  return (
    <>
      {!embedded && <ViewHeading eyebrow="Configuration desk" title="Run configuration" summary="Current authoring sources, the frozen run profile, effective module snapshots, and structural changes." helpKey="module_config" mode={mode} onMode={setMode} />}
      {embedded && <div className="embeddedModeSwitch"><ModeSwitch mode={mode} onChange={setMode} /></div>}
      <SubNav value={section} onChange={setSection} items={[{ key: "summary", label: "Summary", helpKey: "frozen_config" }, { key: "snapshots", label: "Module snapshots", helpKey: "module_snapshot" }, { key: "authoring", label: "Current YAML", helpKey: "current_yaml" }, { key: "diffs", label: `Changes ${data?.diffs?.length || 0}`, helpKey: "config_diff" }]} />
      {!data ? <Loading label="Opening configuration" /> : mode === "raw" ? (
        section === "authoring"
          ? <section className="sourceViewer"><select value={sourcePath} onChange={(event) => setSourcePath(event.target.value)}>{(data.current_authoring || []).map((file: Json) => <option key={file.path} value={file.path}>{file.path}</option>)}</select><pre>{source}</pre></section>
          : <div className="jsonViewport"><JsonTree value={section === "snapshots" ? data.module_snapshots : section === "diffs" ? data.diffs : data.frozen_profile} /></div>
      ) : (
        <div className="configLayout">
          {section === "summary" && <ConfigSummary data={data} />}
          {section === "snapshots" && <SnapshotReader snapshots={data.module_snapshots || []} />}
          {section === "authoring" && <section className="sourceViewer"><select value={sourcePath} onChange={(event) => setSourcePath(event.target.value)}>{(data.current_authoring || []).map((file: Json) => <option key={file.path} value={file.path}>{file.path}</option>)}</select><pre>{source}</pre></section>}
          {section === "diffs" && <DiffReader diffs={data.diffs || []} />}
        </div>
      )}
    </>
  );
}

function ConfigSummary({ data }: { data: Json }) {
  const providers = data.provider_model_summary || [];
  return (
    <div className="configSummary">
      <section className="directionLead"><span className="sectionLabel">Frozen at run creation</span><h3>{humanize(data.frozen_profile?.profile_name || data.frozen_profile?.name || "Composed run profile")}</h3><p>The module snapshots below are the effective settings persisted when each module executed.</p></section>
      <section className="dataSection"><SectionTitle label="Provider routing" title="Models used by module" /><div className="providerTable">{providers.map((row: Json, index: number) => <div key={`${row.module}-${row.path}-${index}`}><strong>{humanize(row.module)}</strong><span>{row.provider || "Provider not set"}</span><span>{row.model || "Model not set"}</span><small>{row.path}</small></div>)}</div></section>
      <section className="dataSection"><SectionTitle label="Frozen profile" title="Configuration sections" /><ReadableObject value={data.frozen_profile || {}} /></section>
    </div>
  );
}

function SnapshotReader({ snapshots }: { snapshots: Json[] }) {
  return (
    <section className="snapshotReader">
      {snapshots.map((snapshot) => <details key={snapshot.path}><summary><div><strong>{humanize(snapshot.module)}</strong><small>{snapshot.path}</small></div><span>{snapshot.error ? "Unreadable" : `${Object.keys(snapshot.config || {}).length} sections`}</span></summary><ReadableObject value={snapshot.config || { error: snapshot.error }} /></details>)}
      {!snapshots.length && <EmptyState label="No module snapshots available" />}
    </section>
  );
}

function DiffReader({ diffs }: { diffs: Json[] }) {
  if (!diffs.length) return <EmptyState label="No structural differences were found" />;
  return <section className="diffReader">{diffs.map((diff) => <details key={diff.path}><summary>{diff.path}</summary><pre>{diff.diff}</pre></details>)}</section>;
}

function RawArtifactReader({ runId, sources }: { runId: string; sources: Array<{ label: string; path: string }> }) {
  const [path, setPath] = useState(sources[0]?.path || "");
  const [artifact, setArtifact] = useState<Json>(null);
  useEffect(() => {
    setPath(sources[0]?.path || "");
  }, [runId, sources.map((source) => source.path).join("|")]);
  useEffect(() => {
    if (!path) return;
    setArtifact(null);
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/artifacts?path=${encodeURIComponent(path)}`).then(setArtifact).catch((err) => setArtifact({ kind: "error", text: errorMessage(err) }));
  }, [runId, path]);
  if (!sources.length) return <EmptyState label="No raw artifact is available" />;
  return (
    <section className="rawReader">
      <div className="rawToolbar"><label><FileJson size={15} /><select value={path} onChange={(event) => setPath(event.target.value)}>{sources.map((source) => <option key={source.path} value={source.path}>{source.label}</option>)}</select></label><span>{path}</span></div>
      {!artifact ? <Loading label="Reading persisted artifact" /> : <ArtifactPreview artifact={artifact} literal />}
    </section>
  );
}

function TreeNode({ node, selected, onSelect }: { node: ArtifactNode; selected: string; onSelect: (path: string) => void }) {
  const [open, setOpen] = useState(node.path.split("/").length < 2);
  if (node.type === "directory") return <div className="treeNode"><button className="treeDir" onClick={() => setOpen(!open)}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<span>{node.name}</span></button>{open && <div className="treeChildren">{(node.children || []).map((child) => <TreeNode key={child.path} node={child} selected={selected} onSelect={onSelect} />)}</div>}</div>;
  return <button className={`treeFile ${selected === node.path ? "selected" : ""}`} onClick={() => onSelect(node.path)}><FileText size={13} /><span>{node.name}</span><small>{formatBytes(node.size || 0)}</small></button>;
}

function ArtifactPreview({ artifact, literal = false }: { artifact: Json; literal?: boolean }) {
  if (!artifact) return <EmptyState label="Artifacts load when selected" />;
  if (artifact.kind === "error") return <ErrorBanner message={artifact.text} />;
  if (artifact.kind === "media") {
    const path = artifact.path || "";
    if (/\.mp4$/i.test(path)) return <video className="artifactMedia" controls preload="metadata" src={mediaUrl(path)} />;
    if (/\.wav$/i.test(path)) return <audio controls preload="metadata" src={mediaUrl(path)} />;
    if (/\.(jpg|jpeg|png|webp|svg)$/i.test(path)) return <img className="artifactImage" src={mediaUrl(path)} alt="" />;
  }
  if (literal && typeof artifact.text === "string") return <pre className="codeViewport">{artifact.text}</pre>;
  if (artifact.kind === "json" && artifact.json !== undefined) return <div className="jsonViewport"><JsonTree value={artifact.json} /></div>;
  return <pre className="codeViewport">{artifact.text || artifact.parse_error || JSON.stringify(artifact, null, 2)}</pre>;
}

function JsonTree({ value, depth = 0 }: { value: Json; depth?: number }) {
  const [open, setOpen] = useState(depth < 2);
  if (value === null || typeof value !== "object") return <span className="jsonScalar">{formatScalar(value)}</span>;
  const entries: Array<[string, Json]> = Array.isArray(value) ? value.map((child, index) => [String(index), child]) : Object.entries(value);
  return (
    <div className="jsonTree">
      <button className="jsonToggle" onClick={() => setOpen(!open)}>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}{Array.isArray(value) ? `Array(${value.length})` : `Object(${entries.length})`}</button>
      {open && <div className="jsonChildren">{entries.slice(0, 500).map(([key, child]) => <div className="jsonLine" key={key}><span className="jsonKey">{key}</span><JsonTree value={child} depth={depth + 1} /></div>)}{entries.length > 500 && <small>Showing the first 500 entries</small>}</div>}
    </div>
  );
}

function ReadableObject({ value, depth = 0 }: { value: Json; depth?: number }) {
  if (!value || typeof value !== "object") return <span>{displayValue(value)}</span>;
  const entries = Object.entries(value);
  if (depth >= 2) return <JsonTree value={value} />;
  return <div className="readableObject">{entries.map(([key, child]) => child && typeof child === "object" ? <details key={key}><summary><span className="readableConcept">{humanize(key)}<GlossaryTip term={key} /></span><span>{Array.isArray(child) ? `${child.length} items` : `${Object.keys(child).length} fields`}</span></summary><ReadableObject value={child} depth={depth + 1} /></details> : <div className="readableField" key={key}><span className="readableConcept">{humanize(key)}<GlossaryTip term={key} /></span><strong>{displayValue(child)}</strong></div>)}</div>;
}

function ReadableValue({ value }: { value: Json }) {
  if (typeof value === "string") return <pre className="responseText">{value}</pre>;
  return <div className="jsonViewport"><JsonTree value={value ?? {}} /></div>;
}

function ViewHeading({ eyebrow, title, summary, mode, onMode, helpKey }: { eyebrow: string; title: string; summary: string; mode?: ViewMode; onMode?: (mode: ViewMode) => void; helpKey?: string }) {
  return <header className="viewHeading"><div><span className="eyebrow">{eyebrow}</span><div className="viewTitleLine"><h2>{title}</h2><HelpTip helpKey={helpKey} label={title} /></div><p>{summary}</p></div>{mode && onMode && <ModeSwitch mode={mode} onChange={onMode} />}</header>;
}

function ModeSwitch({ mode, onChange }: { mode: ViewMode; onChange: (mode: ViewMode) => void }) {
  const readHelp = useHelp("read_mode");
  const rawHelp = useHelp("raw_mode");
  return <div className="modeSwitch" aria-label="Data view"><button className={mode === "read" ? "active" : ""} title={readHelp} onClick={() => onChange("read")}><AlignLeft size={15} />Read</button><button className={mode === "raw" ? "active" : ""} title={rawHelp} onClick={() => onChange("raw")}><Braces size={15} />Raw</button></div>;
}

function SubNav({ value, onChange, items, compact = false }: { value: string; onChange: (key: string) => void; items: Array<{ key: string; label: string; helpKey?: string }>; compact?: boolean }) {
  const catalog = useInspectorCatalog();
  return <div className={`subNav ${compact ? "compact" : ""}`}>{items.map((item) => <button key={item.key} className={value === item.key ? "active" : ""} title={item.helpKey ? catalog?.help?.[item.helpKey] : undefined} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>;
}

function SectionTitle({ label, title }: { label: string; title: string }) {
  return <header className="sectionHeading"><span className="sectionLabel">{label}<GlossaryTip term={label} /></span><h3>{title}<GlossaryTip term={title} /></h3></header>;
}

function MetricBand({ items }: { items: Array<[string, Json]> }) {
  return <dl className="metricBand">{items.map(([label, value]) => <Metric key={label} label={label} value={value} />)}</dl>;
}

function Metric({ label, value, helpKey }: { label: string; value: Json; helpKey?: string }) {
  return <div><dt>{label}{helpKey ? <HelpTip helpKey={helpKey} label={label} /> : <GlossaryTip term={label} />}</dt><dd>{value === null || value === undefined || value === "" ? "Not available" : value}</dd></div>;
}

function Fact({ label, value }: { label: string; value: Json }) {
  return <div><dt>{label}<GlossaryTip term={label} /></dt><dd>{displayValue(value)}</dd></div>;
}

function FilterBar({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="filterBar"><Search size={15} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function StatusChip({ status }: { status: string }) {
  const value = status || "missing";
  const statusHelp = useHelp("stage_status");
  return <span className={`statusChip ${statusClass(value)}`} title={`${humanize(value)}. ${statusHelp}`}><i />{humanize(value)}</span>;
}

function Loading({ label }: { label: string }) {
  return <div className="loading"><Loader2 size={16} className="spin" />{label}</div>;
}

function EmptyState({ label }: { label: string }) {
  return <div className="emptyState">{label}</div>;
}

function ErrorBanner({ message }: { message: string }) {
  return <div className="errorBanner"><CircleAlert size={17} />{message}</div>;
}

function useModule(runId: string, module: string) {
  const [data, setData] = useState<Json>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setData(null);
    setError("");
    fetchJson(`/api/runs/${encodeURIComponent(runId)}/modules/${encodeURIComponent(module)}`)
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, module]);
  return { data, loading, error };
}

async function fetchJson<T = Json>(url: string): Promise<T> {
  const response = await fetch(API + url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

function mediaUrl(path: string) {
  return `/api/media?path=${encodeURIComponent(path)}`;
}

function safeUrl(value: string) {
  return /^https?:\/\//i.test(value || "") ? value : "#";
}

function humanize(value: Json) {
  const text = String(value ?? "").replaceAll("_", " ").replaceAll("-", " ").trim();
  if (!text) return "Not available";
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayValue(value: Json): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? formatNumber(value) : value.toFixed(2);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item) => typeof item === "string" ? humanize(item) : displayValue(item)).join(", ");
  return `${Object.keys(value).length} fields`;
}

function formatScalar(value: Json) {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function statusClass(status: string) {
  const value = String(status || "missing").toLowerCase();
  if (["ok", "ready", "rendered", "succeeded", "available", "approved", "mastered", "advance", "candidate", "produced", "selected", "mapped", "triaged", "prepared"].includes(value)) return "success";
  if (["failed", "error", "malformed", "quarantine", "quarantined", "hard_reject", "rejected", "stopped"].includes(value)) return "danger";
  if (["partial", "warning", "reserve", "duplicate", "degraded", "filtered", "episode_level", "inherited"].includes(value)) return "warning";
  return "neutral";
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value || "Date unknown" : date.toLocaleString([], { dateStyle: "long", timeStyle: "short" });
}

function shortDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value || "Unknown" : date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function runTitle(run: RunIndex) {
  const profile = humanize(run.profile || "Production");
  return `${profile} / ${formatDate(run.created_at)}`;
}

function shortRunId(value: string) {
  const parts = value.replace(/^run_/, "").split("_");
  if (parts.length >= 5) return `${parts[3]} / ${parts.slice(4).join("_")}`;
  return value.replace(/^run_/, "");
}

function formatDuration(value: Json) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "Not available";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.round(seconds % 60).toString().padStart(2, "0");
  return hours ? `${hours}:${minutes.toString().padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

function formatNumber(value: Json) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "Not available";
}

function formatPercent(value: Json) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "Not available";
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDb(value: Json, unit: string) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)} ${unit}` : "Not available";
}

function sectionNarration(section: Json) {
  return section.narration_text || (section.beats || []).map((beat: Json) => beat.narration_text || beat.text).filter(Boolean).join(" ") || "No narration available.";
}

function moduleStatus(modules: ModuleInfo[], name: string) {
  return modules.find((module) => module.name === name)?.status || "missing";
}

function shortFingerprint(value: string) {
  if (!value) return "Not available";
  return value.length > 24 ? `${value.slice(0, 18)}...${value.slice(-6)}` : value;
}

function tokenSummary(usage: Json) {
  if (!usage) return "Not recorded";
  const total = usage.total_tokens ?? usage.total ?? usage.input_tokens + usage.output_tokens;
  return Number.isFinite(Number(total)) ? `${formatNumber(total)} tokens` : "Recorded";
}

function summarySentence(summary: Json) {
  const entries = Object.entries(summary || {}).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value)).slice(0, 3);
  return entries.map(([key, value]) => `${humanize(key)}: ${displayValue(value)}`).join(" / ") || "No summary available";
}

function htmlToPlainText(value: string) {
  if (!value) return "";
  const spaced = value.replace(/<\/(p|div|h[1-6]|li|tr|section|article)>/gi, "</$1>\n").replace(/<br\s*\/?>/gi, "\n");
  const document = new DOMParser().parseFromString(spaced, "text/html");
  document.querySelectorAll("script, style, noscript").forEach((node) => node.remove());
  return (document.body.textContent || "").split("\n").map((line) => line.trim()).filter(Boolean).join("\n");
}

function linkifyLine(line: string) {
  if (/^https?:\/\//i.test(line.trim())) return <a href={safeUrl(line.trim())} target="_blank" rel="noreferrer">{line.trim()}<ExternalLink size={13} /></a>;
  return line;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><InspectorCatalogProvider><App /></InspectorCatalogProvider></React.StrictMode>);
