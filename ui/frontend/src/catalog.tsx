import React, { createContext, useContext, useEffect, useState } from "react";
import { Info } from "lucide-react";

export type OriginKey = "source" | "llm" | "model" | "deterministic" | "mixed";

export type OriginDefinition = {
  label: string;
  short_label: string;
  description: string;
};

export type OutputOrigin = {
  label: string;
  origin: OriginKey;
  description: string;
  fields: string[];
};

export type GenerationDefinition = {
  primary_origin?: OriginKey;
  generation_note?: string;
  outputs?: OutputOrigin[];
};

export type GenerationEvidence = {
  llm_ledger_persisted?: boolean;
  tts_ledger_persisted?: boolean;
  classification_source?: string;
};

export type CatalogStage = {
  key: string;
  label: string;
  desk_summary: string;
  purpose: string;
  consumes: string;
  produces: string;
  primary_origin: OriginKey;
  modules: string[];
};

export type CatalogModule = GenerationDefinition & {
  stage: string;
  path: string;
  label: string;
  purpose: string;
  consumes: string;
  produces: string;
};

export type InspectorCatalog = {
  version: number;
  read_only: boolean;
  origins: Record<OriginKey, OriginDefinition>;
  help: Record<string, string>;
  glossary: Record<string, string>;
  stages: CatalogStage[];
  modules: Record<string, CatalogModule>;
};

const CatalogContext = createContext<InspectorCatalog | null>(null);

export function InspectorCatalogProvider({ children }: { children: React.ReactNode }) {
  const [catalog, setCatalog] = useState<InspectorCatalog | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/catalog")
      .then((response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        return response.json() as Promise<InspectorCatalog>;
      })
      .then((value) => {
        if (!cancelled) setCatalog(value);
      })
      .catch(() => {
        if (!cancelled) setCatalog(null);
      });
    return () => { cancelled = true; };
  }, []);

  return <CatalogContext.Provider value={catalog}>{children}</CatalogContext.Provider>;
}

export function useInspectorCatalog() {
  return useContext(CatalogContext);
}

export function useHelp(key?: string) {
  const catalog = useInspectorCatalog();
  return key ? catalog?.help?.[key] || "" : "";
}

export function useGlossary(term?: string) {
  const catalog = useInspectorCatalog();
  if (!term) return "";
  const key = term.replaceAll("_", " ").replaceAll("-", " ").trim().toLowerCase();
  return catalog?.glossary?.[key] || "";
}

export function GlossaryTip({ term }: { term: string }) {
  const text = useGlossary(term);
  return text ? <HelpTip text={text} label={term} /> : null;
}

export function HelpTip({ helpKey, text, label = "Explanation" }: { helpKey?: string; text?: string; label?: string }) {
  const catalogText = useHelp(helpKey);
  const content = text || catalogText;
  if (!content) return null;
  return (
    <span className="helpTip" tabIndex={0} aria-label={`${label}: ${content}`}>
      <Info size={13} aria-hidden="true" />
      <span className="helpBubble" role="tooltip">{content}</span>
    </span>
  );
}

export function OriginMark({ origin = "deterministic" }: { origin?: OriginKey }) {
  const catalog = useInspectorCatalog();
  const definition = catalog?.origins?.[origin];
  return (
    <span className={`originMark origin-${origin}`} title={definition?.description || origin}>
      {definition?.short_label || origin}
    </span>
  );
}

export function OriginBadge({ origin = "deterministic" }: { origin?: OriginKey }) {
  const catalog = useInspectorCatalog();
  const definition = catalog?.origins?.[origin];
  return (
    <span className={`originBadge origin-${origin}`}>
      <i aria-hidden="true" />
      <span>{definition?.label || origin}</span>
      <HelpTip text={definition?.description} label={definition?.label || "Data origin"} />
    </span>
  );
}

export function GenerationLegend() {
  const catalog = useInspectorCatalog();
  if (!catalog) return null;
  return (
    <section className="generationLegend" aria-label="Data origin legend">
      <div><strong>Data origin</strong><HelpTip helpKey="generation_origin" /></div>
      <div>{(["source", "llm", "model", "deterministic", "mixed"] as OriginKey[]).map((origin) => <OriginMark key={origin} origin={origin} />)}</div>
    </section>
  );
}

export function GenerationMap({ definition, evidence, compact = false }: { definition?: GenerationDefinition; evidence?: GenerationEvidence; compact?: boolean }) {
  if (!definition?.primary_origin && !definition?.outputs?.length) return null;
  const outputs = definition.outputs || [];
  return (
    <section className={`generationMap ${compact ? "compact" : ""}`}>
      <header>
        <div><span className="sectionLabel">Generation provenance</span><h3>How this data was produced</h3></div>
        <OriginBadge origin={definition.primary_origin || "deterministic"} />
      </header>
      {definition.generation_note && <p>{definition.generation_note}</p>}
      {evidence && (
        <div className="generationEvidence">
          <strong>Run evidence</strong>
          <span>{evidence.llm_ledger_persisted ? "LLM call ledger persisted" : evidence.tts_ledger_persisted ? "TTS request ledger persisted" : "No LLM or TTS ledger attached to this module"}</span>
          {evidence.llm_ledger_persisted && evidence.tts_ledger_persisted && <span>TTS request ledger persisted</span>}
        </div>
      )}
      <div className="generationRows">
        {outputs.map((output) => (
          <div key={`${output.label}-${output.origin}`}>
            <OriginMark origin={output.origin} />
            <div><strong>{output.label}</strong><span>{output.description}</span>{!!output.fields?.length && <small>{output.fields.join(" / ")}</small>}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
