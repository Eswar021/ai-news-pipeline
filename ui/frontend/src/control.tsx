import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleStop,
  Code2,
  FileDiff,
  GitCompareArrows,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
} from "lucide-react";
import { HelpTip, OriginBadge } from "./catalog";

type Json = any;

export type RunOption = {
  run_id: string;
  profile: string;
  environment: string;
  overall_status: string;
  created_at: string;
  last_completed_module?: string;
  metrics?: Record<string, Json>;
};

type ControllerJob = {
  id: string;
  request_id: string;
  operation: string;
  run_id: string;
  status: string;
  plan: Record<string, Json>;
  commands: Array<{ stage: string; display: string }>;
  current_step: number;
  step_count: number;
  current_stage: string;
  failure_reason: string;
  cancel_requested: boolean;
  created_at: string;
  started_at?: string;
  finished_at?: string;
};

type ControllerStatus = {
  available: boolean;
  loading: boolean;
  activeJob: ControllerJob | null;
  jobs: ControllerJob[];
  refresh: () => Promise<void>;
};

type ControlStage = {
  key: "collect" | "content" | "voiceover" | "visuals";
  label: string;
  description: string;
  modules: string[];
  supports_boundaries: boolean;
  provider_risk: string;
};

type Capabilities = {
  local_only: boolean;
  profiles: string[];
  environments: string[];
  default_profile: string;
  default_environment: string;
  stages: ControlStage[];
  config_modes: string[];
  synthesis_modes: string[];
  runtime: { ready: boolean; python: string; reason: string };
};

type RunPlan = {
  operation: "new" | "resume" | "retry";
  run_id?: string;
  profile?: string;
  environment?: string;
  target_stage: "collect" | "content" | "voiceover" | "visuals";
  config_mode: "live" | "frozen";
  synthesis_mode: "preview" | "final";
  voiceover_variant?: string;
  deterministic: boolean;
  units?: number | null;
  skip_render: boolean;
  from_module?: string;
  stop_after?: string;
  skip_metadata_finalization: boolean;
  confirm_provider_costs: boolean;
  confirm_final_media: boolean;
};

type PlanPreview = {
  plan: RunPlan;
  run_id: string;
  commands: Array<{ stage: string; display: string }>;
  risk_notes: string[];
  requires_provider_confirmation: boolean;
  requires_final_confirmation: boolean;
};

const DEFAULT_PLAN: RunPlan = {
  operation: "new",
  target_stage: "content",
  config_mode: "live",
  synthesis_mode: "preview",
  deterministic: false,
  units: null,
  skip_render: false,
  skip_metadata_finalization: false,
  confirm_provider_costs: false,
  confirm_final_media: false,
};

export function useControllerStatus(): ControllerStatus {
  const [available, setAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeJob, setActiveJob] = useState<ControllerJob | null>(null);
  const [jobs, setJobs] = useState<ControllerJob[]>([]);

  const refresh = async () => {
    try {
      const data = await controlFetch<{ active_job: ControllerJob | null; jobs: ControllerJob[] }>("/control/jobs");
      setAvailable(true);
      setActiveJob(data.active_job);
      setJobs(data.jobs || []);
    } catch {
      setAvailable(false);
      setActiveJob(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 2000);
    return () => window.clearInterval(interval);
  }, []);

  return { available, loading, activeJob, jobs, refresh };
}

export function NewRunView({
  runs,
  preset,
  controller,
  onRunsChanged,
}: {
  runs: RunOption[];
  preset?: { operation: RunPlan["operation"]; run_id?: string };
  controller: ControllerStatus;
  onRunsChanged: () => void;
}) {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [plan, setPlan] = useState<RunPlan>({ ...DEFAULT_PLAN });
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [jobId, setJobId] = useState(controller.activeJob?.id || "");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    controlFetch<Capabilities>("/control/capabilities")
      .then((value) => {
        setCapabilities(value);
        setPlan((current) => ({
          ...current,
          profile: current.profile || value.default_profile,
          environment: current.environment || value.default_environment,
        }));
      })
      .catch((error) => setPreviewError(message(error)));
  }, [controller.available]);

  useEffect(() => {
    if (!preset) return;
    setPlan((current) => ({
      ...current,
      operation: preset.operation,
      run_id: preset.run_id || (preset.operation === "new" ? undefined : runs[0]?.run_id),
      from_module: undefined,
      stop_after: undefined,
      confirm_provider_costs: false,
      confirm_final_media: false,
    }));
  }, [preset?.operation, preset?.run_id]);

  useEffect(() => {
    if (controller.activeJob?.id) setJobId(controller.activeJob.id);
  }, [controller.activeJob?.id]);

  useEffect(() => {
    if (!capabilities) return;
    if (plan.operation !== "new" && !plan.run_id) return;
    const timer = window.setTimeout(() => {
      setPreviewing(true);
      setPreviewError("");
      controlFetch<PlanPreview>("/control/plans/preview", {
        method: "POST",
        body: JSON.stringify(plan),
      })
        .then((value) => {
          setPreview(value);
          if (plan.operation === "new" && !plan.run_id && value.run_id) {
            setPlan((current) => ({ ...current, run_id: value.run_id }));
          }
        })
        .catch((error) => {
          setPreview(null);
          setPreviewError(message(error));
        })
        .finally(() => setPreviewing(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [capabilities, JSON.stringify(plan)]);

  const stage = capabilities?.stages.find((item) => item.key === plan.target_stage);
  const setOperation = (operation: RunPlan["operation"]) => {
    setPlan((current) => ({
      ...current,
      operation,
      run_id: operation === "new" ? undefined : current.run_id || runs[0]?.run_id,
      from_module: undefined,
      stop_after: undefined,
      confirm_provider_costs: false,
      confirm_final_media: false,
    }));
  };
  const setTargetStage = (target_stage: RunPlan["target_stage"]) => {
    setPlan((current) => ({
      ...current,
      target_stage,
      from_module: undefined,
      stop_after: undefined,
      confirm_provider_costs: false,
      confirm_final_media: false,
    }));
  };
  const canSubmit = Boolean(
    preview
    && capabilities?.runtime.ready
    && !submitting
    && !controller.activeJob
    && (!preview.requires_provider_confirmation || plan.confirm_provider_costs)
    && (!preview.requires_final_confirmation || plan.confirm_final_media)
  );
  const submit = async () => {
    if (!preview || !canSubmit) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const exactPlan = {
        ...preview.plan,
        confirm_provider_costs: plan.confirm_provider_costs,
        confirm_final_media: plan.confirm_final_media,
      };
      const requestId = `request_${crypto.randomUUID()}`;
      const response = await controlFetch<{ job: ControllerJob }>("/control/jobs", {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, plan: exactPlan }),
      });
      setJobId(response.job.id);
      await controller.refresh();
    } catch (error) {
      setSubmitError(message(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="controlPage newRunPage">
      <ControlHeading
        eyebrow="Local execution"
        title="New run"
        summary="Build an allowlisted runner plan, review every command, then supervise it from this desk."
        icon={<Play size={20} />}
      />
      {!controller.available && <ControlError text="The local execution controller is not connected." />}
      {capabilities && !capabilities.runtime.ready && <ControlError text={`Pipeline runtime is not ready: ${capabilities.runtime.reason}`} />}

      <div className="builderMode" role="tablist" aria-label="Run operation">
        {([
          ["new", "New pipeline"],
          ["resume", "Continue run"],
          ["retry", "Replay / retry"],
        ] as const).map(([key, label]) => (
          <button key={key} role="tab" aria-selected={plan.operation === key} className={plan.operation === key ? "active" : ""} onClick={() => setOperation(key)}>
            {label}
          </button>
        ))}
      </div>

      <div className="runBuilderLayout">
        <section className="builderForm">
          <BuilderSection number="01" title="Run identity">
            {plan.operation === "new" ? (
              <div className="formGrid two">
                <ControlSelect label="Profile" value={plan.profile || ""} onChange={(profile) => setPlan((current) => ({ ...current, profile, run_id: undefined }))} options={capabilities?.profiles || []} />
                <ControlSelect label="Environment" value={plan.environment || ""} onChange={(environment) => setPlan((current) => ({ ...current, environment, run_id: undefined }))} options={capabilities?.environments || []} />
              </div>
            ) : (
              <ControlSelect
                label="Persisted run"
                value={plan.run_id || ""}
                onChange={(run_id) => setPlan((current) => ({ ...current, run_id }))}
                options={runs.map((run) => run.run_id)}
                labels={Object.fromEntries(runs.map((run) => [run.run_id, `${titleCase(run.profile)} / ${shortRun(run.run_id)}`]))}
              />
            )}
            <div className="plannedIdentity"><span>Run ID</span><code>{preview?.run_id || plan.run_id || "Generated after profile selection"}</code></div>
          </BuilderSection>

          <BuilderSection number="02" title={plan.operation === "new" ? "Run through" : "Stage to execute"}>
            <div className="stageChoice">
              {(capabilities?.stages || []).map((item, index) => (
                <button key={item.key} aria-pressed={plan.target_stage === item.key} className={plan.target_stage === item.key ? "active" : ""} onClick={() => setTargetStage(item.key)}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </button>
              ))}
            </div>
          </BuilderSection>

          <BuilderSection number="03" title="Execution policy">
            <div className="formGrid three">
              <ControlSelect label="Config mode" value={plan.config_mode} onChange={(config_mode) => setPlan((current) => ({ ...current, config_mode: config_mode as RunPlan["config_mode"] }))} options={["live", "frozen"]} />
              {plan.target_stage === "voiceover" && (
                <ControlSelect label="Voice mode" value={plan.synthesis_mode} onChange={(synthesis_mode) => setPlan((current) => ({ ...current, synthesis_mode: synthesis_mode as RunPlan["synthesis_mode"], confirm_final_media: false }))} options={["preview", "final"]} />
              )}
              {plan.target_stage === "visuals" && (
                <ControlSelect label="Art director" value={plan.deterministic ? "bridge" : "llm"} onChange={(mode) => setPlan((current) => ({ ...current, deterministic: mode === "bridge", confirm_provider_costs: false }))} options={["llm", "bridge"]} labels={{ llm: "LLM art director", bridge: "Deterministic bridge" }} />
              )}
              {plan.target_stage === "visuals" && (
                <ControlSelect label="Render" value={plan.skip_render ? "build" : "render"} onChange={(mode) => setPlan((current) => ({ ...current, skip_render: mode === "build", confirm_final_media: false }))} options={["render", "build"]} labels={{ render: "Full episode render", build: "Build only (no MP4)" }} />
              )}
              {plan.target_stage === "visuals" && (
                <ControlText label="Unit slice (optional)" value={plan.units == null ? "" : String(plan.units)} placeholder="all units" onChange={(value) => {
                  const parsed = parseInt(value, 10);
                  setPlan((current) => ({ ...current, units: Number.isFinite(parsed) && parsed > 0 ? parsed : null }));
                }} />
              )}
            </div>

            {plan.operation !== "new" && stage?.supports_boundaries && (
              <div className="boundaryBand">
                <ControlSelect label="Rerun from module" value={plan.from_module || ""} onChange={(from_module) => setPlan((current) => ({ ...current, from_module: from_module || undefined }))} options={["", ...(stage.modules || [])]} labels={{ "": "Automatic reuse boundary" }} />
                <ArrowRight size={18} />
                <ControlSelect label="Stop after module" value={plan.stop_after || ""} onChange={(stop_after) => setPlan((current) => ({ ...current, stop_after: stop_after || undefined }))} options={["", ...(stage.modules || [])]} labels={{ "": "Complete the stage" }} />
              </div>
            )}
          </BuilderSection>
        </section>

        <aside className="planReview">
          <header><span>Plan review</span><strong>{preview?.commands.length || 0} command{preview?.commands.length === 1 ? "" : "s"}</strong></header>
          {previewing && <ControlLoading label="Validating plan" />}
          {previewError && <ControlError text={previewError} />}
          {preview && (
            <>
              <div className="commandSequence">
                {preview.commands.map((command, index) => (
                  <div key={`${command.stage}-${index}`}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div><strong>{titleCase(command.stage)}</strong><code>{command.display}</code></div>
                  </div>
                ))}
              </div>
              <div className="riskRegister">
                <strong>Execution effects</strong>
                {preview.risk_notes.map((note) => <p key={note}>{note}</p>)}
              </div>
              {preview.requires_provider_confirmation && (
                <ControlCheck checked={plan.confirm_provider_costs} onChange={(confirm_provider_costs) => setPlan((current) => ({ ...current, confirm_provider_costs }))} label="I approve possible provider calls and associated costs." />
              )}
              {preview.requires_final_confirmation && (
                <ControlCheck checked={plan.confirm_final_media} onChange={(confirm_final_media) => setPlan((current) => ({ ...current, confirm_final_media }))} label="I approve final voice or final-quality media generation." />
              )}
              {submitError && <ControlError text={submitError} />}
              <button className="startRunButton" disabled={!canSubmit} onClick={submit}>
                {submitting ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
                Start plan
              </button>
              {controller.activeJob && controller.activeJob.id !== jobId && (
                <p className="activeWriterNotice">Another plan is {controller.activeJob.status}: {controller.activeJob.run_id}</p>
              )}
            </>
          )}
        </aside>
      </div>

      {jobId && <JobMonitor jobId={jobId} onChanged={async () => {
        await controller.refresh();
        onRunsChanged();
      }} />}
      <JobHistory jobs={controller.jobs} onOpen={setJobId} selected={jobId} />
    </div>
  );
}

function JobMonitor({ jobId, onChanged }: { jobId: string; onChanged: () => void }) {
  const [job, setJob] = useState<ControllerJob | null>(null);
  const [events, setEvents] = useState<Array<{ id: number; created_at: string; stream: string; line: string }>>([]);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const afterRef = useRef(0);

  useEffect(() => {
    setJob(null);
    setEvents([]);
    afterRef.current = 0;
    setError("");
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: number | undefined;
    let terminalNotified = false;
    const poll = async () => {
      try {
        const data = await controlFetch<{ job: ControllerJob; events: typeof events; next_after: number }>(`/control/jobs/${encodeURIComponent(jobId)}?after_event_id=${afterRef.current}`);
        if (cancelled) return;
        setJob(data.job);
        if (data.events.length) {
          setEvents((current) => [...current, ...data.events].slice(-2000));
          afterRef.current = data.next_after;
        }
        if (["completed", "failed", "cancelled", "interrupted", "blocked"].includes(data.job.status)) {
          if (!terminalNotified) {
            terminalNotified = true;
            onChanged();
          }
          return;
        }
        timer = window.setTimeout(poll, 1200);
      } catch (nextError) {
        if (!cancelled) {
          setError(message(nextError));
          timer = window.setTimeout(poll, 3000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId]);

  const cancel = async () => {
    setCancelling(true);
    try {
      const data = await controlFetch<{ job: ControllerJob }>(`/control/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
      setJob(data.job);
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setCancelling(false);
    }
  };

  if (!job) return <section className="jobMonitor"><ControlLoading label="Opening controller job" /></section>;
  const active = ["queued", "running", "cancelling", "orphaned"].includes(job.status);
  return (
    <section className="jobMonitor" aria-live="polite">
      <header>
        <div>
          <span className={`controlStatus status-${job.status}`}><i />{titleCase(job.status)}</span>
          <h3>{job.run_id}</h3>
          <p>{job.current_stage ? `${titleCase(job.current_stage)} / step ${job.current_step} of ${job.step_count}` : `${job.step_count} planned stages`}</p>
        </div>
        {active && <button className="dangerButton" disabled={cancelling} onClick={cancel}><CircleStop size={16} /> Cancel</button>}
      </header>
      <div className="jobProgress"><span style={{ width: `${job.step_count ? Math.max(4, (job.current_step / job.step_count) * 100) : 0}%` }} /></div>
      {job.failure_reason && <ControlError text={job.failure_reason} />}
      {error && <ControlError text={error} />}
      <pre className="controllerConsole" aria-label="Controller output">{events.map((event) => `${timeOnly(event.created_at)}  ${event.line}`).join("\n") || "Waiting for runner output..."}</pre>
    </section>
  );
}

function JobHistory({ jobs, onOpen, selected }: { jobs: ControllerJob[]; onOpen: (id: string) => void; selected: string }) {
  if (!jobs.length) return null;
  return (
    <section className="jobHistory">
      <header><span>Controller history</span><strong>{jobs.length} recent jobs</strong></header>
      <div>
        {jobs.slice(0, 12).map((job) => (
          <button key={job.id} className={selected === job.id ? "active" : ""} onClick={() => onOpen(job.id)}>
            <span className={`controlStatus status-${job.status}`}><i />{titleCase(job.status)}</span>
            <strong>{job.run_id}</strong>
            <small>{titleCase(job.operation)} / {dateTime(job.created_at)}</small>
            <ChevronRight size={15} />
          </button>
        ))}
      </div>
    </section>
  );
}

export function CompareRunsView({ runs }: { runs: RunOption[] }) {
  const [left, setLeft] = useState(runs[0]?.run_id || "");
  const [right, setRight] = useState(runs[1]?.run_id || "");
  const [data, setData] = useState<Json>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [section, setSection] = useState("overview");
  const canCompare = left && right && left !== right;
  const compare = async () => {
    if (!canCompare) return;
    setLoading(true);
    setError("");
    try {
      setData(await apiFetch(`/api/compare/runs?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`));
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="controlPage comparePage">
      <ControlHeading eyebrow="Quality desk" title="Compare runs" summary="Inspect production, editorial, model-usage, and configuration differences without loading either run's complete artifact tree." icon={<GitCompareArrows size={20} />} />
      <section className="comparisonPicker">
        <RunSelect label="Left run" value={left} runs={runs} onChange={setLeft} />
        <GitCompareArrows size={22} />
        <RunSelect label="Right run" value={right} runs={runs} onChange={setRight} />
        <button className="compareButton" disabled={!canCompare || loading} onClick={compare}>{loading ? <Loader2 size={16} className="spin" /> : <GitCompareArrows size={16} />} Compare</button>
      </section>
      {error && <ControlError text={error} />}
      {data && (
        <>
          <div className="comparisonNav" aria-label="Comparison sections">
            {["overview", "script", "metadata", "usage", "config"].map((key) => (
              <button key={key} className={section === key ? "active" : ""} onClick={() => setSection(key)}>{titleCase(key)}</button>
            ))}
          </div>
          {section === "overview" && <ComparisonOverview data={data} />}
          {section === "script" && <ScriptComparison data={data.script} />}
          {section === "metadata" && <FieldComparison fields={data.metadata?.fields || []} />}
          {section === "usage" && <UsageComparison data={data.usage} />}
          {section === "config" && <ConfigComparison data={data.config} />}
        </>
      )}
      {!data && !loading && <div className="compareEmpty"><FileDiff size={28} /><strong>Select two runs</strong><span>The comparison is loaded only when requested.</span></div>}
    </div>
  );
}

function ComparisonOverview({ data }: { data: Json }) {
  return (
    <div className="comparisonBody">
      <section className="compareRunHeads">
        <RunCompareHead run={data.left} />
        <RunCompareHead run={data.right} />
      </section>
      <section className="compareMetrics">
        {(data.metrics || []).map((row: Json) => (
          <div key={row.key} className={row.changed ? "changed" : ""}>
            <span>{titleCase(row.key)}</span>
            <strong>{display(row.left)}</strong>
            <ArrowRight size={14} />
            <strong>{display(row.right)}</strong>
          </div>
        ))}
      </section>
      <section className="moduleMatrix">
        <header><span>Workflow comparison</span><strong>Module state and reuse</strong></header>
        {(data.modules || []).map((row: Json) => (
          <div key={row.module} className={row.changed ? "changed" : ""}>
            <strong>{row.label}</strong>
            <span>{titleCase(row.left_status)}{row.left_reused ? " / reused" : ""}</span>
            <ArrowRight size={13} />
            <span>{titleCase(row.right_status)}{row.right_reused ? " / reused" : ""}</span>
          </div>
        ))}
      </section>
    </div>
  );
}

function RunCompareHead({ run }: { run: RunOption }) {
  return <div><span className={`controlStatus status-${run.overall_status}`}><i />{titleCase(run.overall_status)}</span><h3>{titleCase(run.profile)}</h3><code>{run.run_id}</code><small>{dateTime(run.created_at)}</small></div>;
}

function ScriptComparison({ data }: { data: Json }) {
  return (
    <div className="comparisonBody">
      <section className="scriptCompareSummary">
        <div><span>Left script</span><strong>{formatNumber(data.left_word_count)} words</strong><code>{data.left_fingerprint || "No fingerprint"}</code></div>
        <ArrowRight size={18} />
        <div><span>Right script</span><strong>{formatNumber(data.right_word_count)} words</strong><code>{data.right_fingerprint || "No fingerprint"}</code></div>
      </section>
      <section className="sectionDiffList">
        <header><span>Section changes</span><strong>{(data.sections || []).filter((row: Json) => row.changed).length} changed</strong></header>
        {(data.sections || []).map((row: Json) => <div key={row.section_id} className={row.changed ? "changed" : ""}><code>{row.section_id}</code><strong>{row.left_title || "Missing"}</strong><span>{display(row.left_words)} → {display(row.right_words)} words</span></div>)}
      </section>
      <details className="diffBlock" open><summary>Unified narration diff</summary><pre>{data.diff || "No narration differences."}</pre></details>
    </div>
  );
}

function FieldComparison({ fields }: { fields: Json[] }) {
  return (
    <div className="fieldComparison">
      {fields.map((field) => (
        <details key={field.key} className={field.changed ? "changed" : ""}>
          <summary><strong>{titleCase(field.key)}</strong><span>{field.changed ? "Changed" : "Same"}</span></summary>
          <div><ComparisonValue value={field.left} /><ArrowRight size={16} /><ComparisonValue value={field.right} /></div>
        </details>
      ))}
    </div>
  );
}

function ComparisonValue({ value }: { value: Json }) {
  if (Array.isArray(value)) return <ul>{value.length ? value.map((item, index) => <li key={index}>{typeof item === "object" ? JSON.stringify(item) : String(item)}</li>) : <li>Not available</li>}</ul>;
  if (value && typeof value === "object") return <pre>{JSON.stringify(value, null, 2)}</pre>;
  return <p>{display(value)}</p>;
}

function UsageComparison({ data }: { data: Json }) {
  const metrics = [
    ["LLM calls", data.left?.llm?.call_count, data.right?.llm?.call_count],
    ["Prompt tokens", data.left?.llm?.prompt_tokens, data.right?.llm?.prompt_tokens],
    ["Completion tokens", data.left?.llm?.completion_tokens, data.right?.llm?.completion_tokens],
    ["Total tokens", data.left?.llm?.total_tokens, data.right?.llm?.total_tokens],
    ["LLM duration", seconds(data.left?.llm?.duration_seconds), seconds(data.right?.llm?.duration_seconds)],
    ["TTS requests", data.left?.tts?.request_count, data.right?.tts?.request_count],
    ["TTS latency", seconds(data.left?.tts?.latency_seconds), seconds(data.right?.tts?.latency_seconds)],
  ];
  return (
    <div className="comparisonBody">
      <div className="usageNote"><CircleAlert size={16} /><p>{data.cost_note}</p></div>
      <section className="compareMetrics">
        {metrics.map(([label, left, right]) => <div key={String(label)} className={left !== right ? "changed" : ""}><span>{label}</span><strong>{display(left)}</strong><ArrowRight size={14} /><strong>{display(right)}</strong></div>)}
      </section>
      <section className="routeCompare"><RouteList title="Left routes" rows={[...(data.left?.llm?.routes || []), ...(data.left?.tts?.routes || [])]} /><RouteList title="Right routes" rows={[...(data.right?.llm?.routes || []), ...(data.right?.tts?.routes || [])]} /></section>
    </div>
  );
}

function RouteList({ title, rows }: { title: string; rows: Json[] }) {
  return <div><header>{title}</header>{rows.map((row, index) => <p key={`${row.route}-${index}`}><span>{row.route}</span><strong>{row.count}</strong></p>)}{!rows.length && <p>No persisted routes</p>}</div>;
}

function ConfigComparison({ data }: { data: Json }) {
  return (
    <div className="comparisonBody">
      <section className="changedConfigSections"><span>Changed frozen sections</span><div>{(data.changed_sections || []).map((key: string) => <code key={key}>{key}</code>)}{!data.changed_sections?.length && <strong>No differences</strong>}</div></section>
      <details className="diffBlock" open><summary>Frozen profile diff</summary><pre>{data.diff || "No frozen-profile differences."}</pre></details>
    </div>
  );
}

export function ConfigStudio({ activeJob }: { activeJob: ControllerJob | null }) {
  const [files, setFiles] = useState<Json[]>([]);
  const [selected, setSelected] = useState("");
  const [opened, setOpened] = useState<Json>(null);
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [summary, setSummary] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revisions, setRevisions] = useState<Json[]>([]);
  const dirty = Boolean(opened && text !== opened.text);

  const loadFiles = async () => {
    try {
      const data = await controlFetch<{ files: Json[] }>("/control/config/files");
      setFiles(data.files || []);
      setSelected((current) => current || data.files?.[0]?.path || "");
    } catch (nextError) {
      setError(message(nextError));
    }
  };
  useEffect(() => { void loadFiles(); }, []);
  useEffect(() => {
    if (!selected) return;
    setError("");
    setNotice("");
    controlFetch(`/control/config/file?path=${encodeURIComponent(selected)}`)
      .then((value: Json) => {
        setOpened(value);
        setText(value.text || "");
        setSummary("");
        setConfirmed(false);
      })
      .catch((nextError) => setError(message(nextError)));
    controlFetch(`/control/config/revisions?path=${encodeURIComponent(selected)}&limit=12`)
      .then((value: Json) => setRevisions(value.revisions || []))
      .catch(() => setRevisions([]));
  }, [selected]);

  const choose = (path: string) => {
    if (dirty && !window.confirm("Discard the unsaved YAML changes?")) return;
    setSelected(path);
  };
  const save = async () => {
    if (!opened || !dirty || !confirmed || summary.trim().length < 3) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await controlFetch("/control/config/file", {
        method: "PUT",
        body: JSON.stringify({
          path: opened.path,
          expected_sha256: opened.sha256,
          text,
          change_summary: summary.trim(),
          confirm_write: true,
        }),
      });
      setOpened(saved);
      setText(saved.text);
      setSummary("");
      setConfirmed(false);
      setNotice(`Saved and validated revision ${saved.revision_id}.`);
      await loadFiles();
      const history = await controlFetch(`/control/config/revisions?path=${encodeURIComponent(selected)}&limit=12`);
      setRevisions(history.revisions || []);
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setSaving(false);
    }
  };
  const visible = files.filter((file) => file.path.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="controlPage configStudioPage">
      <ControlHeading eyebrow="Authoring control" title="Config studio" summary="Edit an existing authoring YAML file with conflict detection, credential rejection, and complete profile composition validation." icon={<Code2 size={20} />} />
      {activeJob && <div className="configRunLock"><ShieldCheck size={16} /><span>Config writes are locked while {activeJob.run_id} is {activeJob.status}.</span></div>}
      <div className="configStudio">
        <aside className="configFileRail">
          <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find YAML" /></label>
          <span>{visible.length} files</span>
          <div>{visible.map((file) => <button key={file.path} className={selected === file.path ? "active" : ""} onClick={() => choose(file.path)}><strong>{file.path.split("/").at(-1)}</strong><small>{file.path}</small></button>)}</div>
        </aside>
        <section className="configEditorPane">
          <header><div><span>Current authoring YAML</span><strong>{selected}</strong></div><div><button title="Reload file" disabled={!dirty} onClick={() => { setText(opened?.text || ""); setConfirmed(false); }}><RotateCcw size={15} /></button><button className="saveConfigButton" disabled={!dirty || !confirmed || summary.trim().length < 3 || saving || Boolean(activeJob)} onClick={save}>{saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save</button></div></header>
          {error && <ControlError text={error} />}
      {notice && <div className="controlNotice" role="status"><Check size={15} />{notice}</div>}
          {!opened ? <ControlLoading label="Opening YAML" /> : (
            <>
              <textarea className="yamlEditor" spellCheck={false} value={text} onChange={(event) => { setText(event.target.value); setConfirmed(false); setNotice(""); }} aria-label={`Edit ${selected}`} />
              <footer><span>{text.split("\n").length} lines / {new Blob([text]).size.toLocaleString()} bytes</span><span>{dirty ? "Unsaved changes" : "No local changes"}</span></footer>
              <div className="configCommit">
                <label><span>Change summary</span><input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="Why this authoring change is needed" maxLength={300} /></label>
                <ControlCheck checked={confirmed} onChange={setConfirmed} label="I reviewed this YAML and want to update the current authoring configuration." />
              </div>
            </>
          )}
        </section>
        <aside className="revisionRail">
          <header><span>Revision trail</span><strong>{revisions.length}</strong></header>
          {revisions.map((revision) => <div key={revision.id}><span>{dateTime(revision.created_at)}</span><strong>{revision.change_summary}</strong><code>{String(revision.after_sha256).slice(0, 12)}</code></div>)}
          {!revisions.length && <p>No UI-authored revisions for this file.</p>}
        </aside>
      </div>
    </div>
  );
}

export function ReviewNotesPanel({ runId }: { runId: string }) {
  const [note, setNote] = useState<Json>(null);
  const [status, setStatus] = useState("open");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    controlFetch(`/control/notes/${encodeURIComponent(runId)}`)
      .then((value: Json) => {
        setNote(value);
        setStatus(value.status || "open");
        setBody(value.body || "");
      })
      .catch((nextError) => setError(message(nextError)));
  }, [runId]);
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const value = await controlFetch(`/control/notes/${encodeURIComponent(runId)}`, {
        method: "PUT",
        body: JSON.stringify({ status, body }),
      });
      setNote(value);
      setNotice(`Saved ${dateTime(value.updated_at)}.`);
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="reviewNotes">
      <header><div><span>Local review record</span><h3>Operator notes</h3></div><ControlSelect label="Disposition" value={status} onChange={setStatus} options={["open", "needs_changes", "approved"]} /></header>
      {error && <ControlError text={error} />}
      <textarea value={body} onChange={(event) => { setBody(event.target.value); setNotice(""); }} placeholder="Record review findings, follow-up questions, or approval context." />
      <footer><span>{notice || (note?.updated_at ? `Last saved ${dateTime(note.updated_at)}` : "Not saved yet")}</span><button className="saveNoteButton" disabled={saving || (note && note.body === body && note.status === status)} onClick={save}>{saving ? <Loader2 size={15} className="spin" /> : <Save size={15} />} Save note</button></footer>
    </section>
  );
}

export function ProvenanceMatches({
  runId,
  module,
  recordKey,
  storyId,
  sectionId,
}: {
  runId: string;
  module: string;
  recordKey?: string;
  storyId?: string;
  sectionId?: string;
}) {
  const [data, setData] = useState<Json>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [record, setRecord] = useState<Json>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const load = async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (recordKey) params.set("record_key", recordKey);
    if (storyId) params.set("story_id", storyId);
    if (sectionId) params.set("section_id", sectionId);
    try {
      setData(await apiFetch(`/api/runs/${encodeURIComponent(runId)}/provenance/llm/${encodeURIComponent(module)}?${params}`));
    } catch (nextError) {
      setError(message(nextError));
    } finally {
      setLoading(false);
    }
  };
  const open = async (index: number) => {
    if (openIndex === index) {
      setOpenIndex(null);
      setRecord(null);
      return;
    }
    setOpenIndex(index);
    setRecord(null);
    try {
      setRecord(await apiFetch(`/api/runs/${encodeURIComponent(runId)}/llm-calls/${encodeURIComponent(module)}/records/${index}`));
    } catch (nextError) {
      setRecord({ error: message(nextError) });
    }
  };
  if (!data) return <div className="provenanceLookup"><button onClick={load} disabled={loading}>{loading ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />} Find related LLM calls</button>{error && <span>{error}</span>}</div>;
  return (
    <section className="provenanceMatches">
      <header><div><OriginBadge origin="llm" /><strong>{data.matches.length} contextual match{data.matches.length === 1 ? "" : "es"}</strong></div><HelpTip text={data.precision_note} /></header>
      {(data.matches || []).map((match: Json) => (
        <React.Fragment key={match.index}>
          <button className="provenanceCall" onClick={() => open(match.index)}><ChevronRight size={14} /><strong>{titleCase(match.module_name || `Call ${match.index + 1}`)}</strong><span>{match.provider} / {match.model}</span><small>{(match.match_reasons || []).join(" / ")}</small></button>
          {openIndex === match.index && <div className="provenanceRecord">{!record ? <ControlLoading label="Opening persisted call" /> : record.error ? <ControlError text={record.error} /> : <CallPayload record={record} />}</div>}
        </React.Fragment>
      ))}
      {!data.matches.length && <p>No ledger metadata references this exact record, story, or section.</p>}
    </section>
  );
}

function CallPayload({ record }: { record: Json }) {
  const [section, setSection] = useState("prompt");
  const sections = ["prompt", "response", "raw", "diagnostics"];
  const value = section === "prompt"
    ? (record.complete_prompt || record.prompt || record.messages)
    : section === "response"
      ? (record.parsed_output || record.structured_response || record.response_text)
      : section === "raw"
        ? (record.raw_response ?? record.response_text)
        : (record.parsing_diagnostics ?? record.metadata);
  return <div><nav>{sections.map((key) => <button key={key} className={section === key ? "active" : ""} onClick={() => setSection(key)}>{titleCase(key)}</button>)}</nav><pre>{typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}</pre></div>;
}

function ControlHeading({ eyebrow, title, summary, icon }: { eyebrow: string; title: string; summary: string; icon: React.ReactNode }) {
  return <header className="controlHeading"><div>{icon}</div><span>{eyebrow}</span><h2>{title}</h2><p>{summary}</p></header>;
}

function BuilderSection({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <section className="builderSection"><header><span>{number}</span><h3>{title}</h3></header>{children}</section>;
}

function ControlSelect({ label, value, onChange, options, labels = {} }: { label: string; value: string; onChange: (value: string) => void; options: string[]; labels?: Record<string, string> }) {
  return <label className="controlField"><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{labels[option] || titleCase(option || "default")}</option>)}</select></label>;
}

function RunSelect({ label, value, runs, onChange }: { label: string; value: string; runs: RunOption[]; onChange: (value: string) => void }) {
  return <label className="runSelect"><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{titleCase(run.profile)} / {shortRun(run.run_id)}</option>)}</select><code>{value}</code></label>;
}

function ControlText({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return <label className="controlField"><span>{label}</span><input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function ControlCheck({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <label className="controlCheck"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span><i>{checked && <Check size={12} />}</i>{label}</span></label>;
}

function ControlError({ text }: { text: string }) {
  return <div className="controlError" role="alert"><CircleAlert size={16} /><span>{text}</span></div>;
}

function ControlLoading({ label }: { label: string }) {
  return <div className="controlLoading"><Loader2 size={15} className="spin" />{label}</div>;
}

async function controlFetch<T = Json>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function apiFetch<T = Json>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function titleCase(value: Json) {
  const text = String(value ?? "").replaceAll("_", " ").replaceAll("-", " ").trim();
  return text ? text.replace(/\b\w/g, (letter) => letter.toUpperCase()) : "Not available";
}

function shortRun(value: string) {
  return value.replace(/^run_/, "").replaceAll("_", " ");
}

function display(value: Json) {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

function formatNumber(value: Json) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "Not available";
}

function seconds(value: Json) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}s` : "Not available";
}

function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value || "Unknown" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function timeOnly(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour12: false });
}
