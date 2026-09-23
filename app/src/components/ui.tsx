/**
 * AB UI primitives (Prosody's system).
 *
 * Presentation only — no business logic, no data fetching. Every screen is
 * assembled from these so spacing, states and typography stay consistent.
 */

import type { CSSProperties, ReactNode } from "react";

/* ------------------------------------------------------------- layout -- */

export function Panel({
  children, inset = false, pad = true, className = "", style,
}: {
  children: ReactNode; inset?: boolean; pad?: boolean;
  className?: string; style?: CSSProperties;
}) {
  return (
    <div
      className={`panel${inset ? " panel-inset" : ""}${pad ? " panel-pad" : ""} ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="label">{children}</div>;
}

/** A titled block with a hairline underline and optional right-hand meta. */
export function Section({
  title, meta, children, className = "",
}: { title: string; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className}>
      <header className="section-head">
        <span className="label">{title}</span>
        {meta && <span className="mono faint num">{meta}</span>}
      </header>
      {children}
    </section>
  );
}

export function Rule() {
  return <hr className="rule" />;
}

/* ------------------------------------------------------------ buttons -- */

type ButtonVariant = "default" | "primary" | "quiet";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  children, onClick, variant = "default", size = "md",
  disabled = false, title, type = "button",
}: {
  children: ReactNode; onClick?: () => void; variant?: ButtonVariant;
  size?: ButtonSize; disabled?: boolean; title?: string;
  type?: "button" | "submit";
}) {
  const classes = [
    "btn",
    variant === "default" ? "" : variant,
    size === "md" ? "" : size,
  ].filter(Boolean).join(" ");
  return (
    <button className={classes} onClick={onClick} disabled={disabled}
            title={title} type={type}>
      {children}
    </button>
  );
}

export function Back({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button className="back" onClick={onClick} type="button">
      <span aria-hidden="true">←</span>
      {children}
    </button>
  );
}

/* --------------------------------------------------------- segmented -- */

export interface SegmentOption<T> {
  value: T;
  label: string;
  caption?: string;
  disabled?: boolean;
}

/** The product's main selector: genre, structure, creativity, on/off. */
export function Segmented<T extends string | number | boolean>({
  options, value, onChange, block = false, tall = false, ariaLabel,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  block?: boolean;
  tall?: boolean;
  ariaLabel?: string;
}) {
  const classes = ["segmented", block ? "block" : "", tall ? "tall" : ""]
    .filter(Boolean).join(" ");
  return (
    <div className={classes} role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.caption && <span className="cap">{option.caption}</span>}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ toggles -- */

export function Toggle({
  on, onChange, label, why, disabled = false,
}: {
  on: boolean; onChange: () => void; label: string;
  why?: string; disabled?: boolean;
}) {
  return (
    <button
      className="toggle"
      type="button"
      aria-pressed={on && !disabled}
      disabled={disabled}
      onClick={onChange}
    >
      <span className="box" aria-hidden="true">✓</span>
      <span>{label}</span>
      {why && <span className="why">{why}</span>}
    </button>
  );
}

/* ------------------------------------------------------------ options -- */

/** A full-width choice row. Used for Extract / Arrange / Extract + Arrange. */
export function Option({
  title, detail, onClick, disabled = false, emphasis = false,
}: {
  title: string; detail: string; onClick: () => void;
  disabled?: boolean; emphasis?: boolean;
}) {
  return (
    <button
      className={`option${emphasis ? " emphasis" : ""}`}
      type="button"
      onClick={onClick}
      disabled={disabled}
    >
      <span className="grow">
        <span className="t">{title}</span>
        <span className="d">{detail}</span>
      </span>
      <span className="chev" aria-hidden="true">→</span>
    </button>
  );
}

/* -------------------------------------------------------------- notes -- */

/** Quiet explanatory copy behind a left rule. Never a filled alert box. */
export function Note({
  children, heading, strong = false,
}: { children: ReactNode; heading?: string; strong?: boolean }) {
  return (
    <div className={`note${strong ? " strong" : ""}`}>
      {heading && <span className="hd">{heading}</span>}
      {children}
    </div>
  );
}

/* ------------------------------------------------------------ readout -- */

export interface Reading { value: string; caption: string }

export function Readout({ items }: { items: Reading[] }) {
  return (
    <div className="readout">
      {items.map((item) => (
        <div className="cell" key={item.caption}>
          <span className="v">{item.value}</span>
          <span className="k">{item.caption}</span>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- badge -- */

export function Badge({ children, on = false }: { children: ReactNode; on?: boolean }) {
  return <span className={`badge${on ? " on" : ""}`}>{children}</span>;
}

/* ----------------------------------------------------------- advanced -- */

export function Advanced({
  title = "Advanced", children,
}: { title?: string; children: ReactNode }) {
  return (
    <details className="advanced">
      <summary>{title}</summary>
      <div className="advanced-body">{children}</div>
    </details>
  );
}

export function Data({ children }: { children: ReactNode }) {
  return <pre className="data">{children}</pre>;
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* -------------------------------------------------------------- empty -- */

export function Empty({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="empty">
      <div className="t">{title}</div>
      {detail && <div className="d">{detail}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ evidence -- */

export type EvidenceState =
  | "VERIFIED" | "INFERRED" | "CANDIDATE" | "GENERATED" | "UNRECOVERABLE" | "UNKNOWN";

/** Evidence-state badge. The only coloured element in the product (SPEC §14);
 *  the state is also in the text, so colour is never the sole carrier. */
/** Validation / promotion vocabulary (SPEC §1) rendered with the evidence hues: equivalence reads as
 *  verified, PERCEPTUALLY_CLOSE / STRUCTURALLY_PLAUSIBLE as inferred, scaffolds as generated, FAILED as unrecoverable. */
const EV_ALIASES: Record<string, EvidenceState> = {
  BIT_EXACT: "VERIFIED", NUMERICALLY_EQUIVALENT: "VERIFIED", BEHAVIORALLY_EQUIVALENT: "VERIFIED", CROSS_LOAD_VALIDATED: "VERIFIED",
  BEHAVIOR_MATCHED: "VERIFIED", STATIC_RECONSTRUCTED: "VERIFIED", BUILT: "VERIFIED", PASSED: "VERIFIED",
  PERCEPTUALLY_CLOSE: "INFERRED", STRUCTURALLY_PLAUSIBLE: "INFERRED", SCAFFOLD_ONLY: "GENERATED", PENDING: "UNKNOWN", NOT_VALIDATED: "UNKNOWN", NOT_RUN: "UNKNOWN",
  FAILED: "UNRECOVERABLE", BUILD_FAILED: "UNRECOVERABLE", CONFIGURE_FAILED: "UNRECOVERABLE", TIMEOUT: "UNRECOVERABLE",
};

export function Ev({ state, title }: { state: string; title?: string }) {
  const up = state.toUpperCase();
  const alias = Object.keys(EV_ALIASES).find((k) => up.startsWith(k));
  const known: EvidenceState = alias ? EV_ALIASES[alias]
    : (["VERIFIED", "INFERRED", "CANDIDATE", "GENERATED", "UNRECOVERABLE"] as const).find((s) => up.startsWith(s)) ?? "UNKNOWN";
  return <span className="ev" data-ev={known} title={title ?? state}>{state}</span>;
}

/* --------------------------------------------------------- stage rail -- */

export interface RailStage {
  key: string;            // INGEST · STATIC · RUNTIME · …
  status: "PENDING" | "RUNNING" | "OK" | "FAILED" | "SKIPPED" | "BLOCKED";
  detail?: string;        // elapsed, completeness flag, skip reason
}

const RAIL_GLYPH: Record<RailStage["status"], string> = {
  PENDING: "·", RUNNING: "◌", OK: "●", FAILED: "✕", SKIPPED: "–", BLOCKED: "⊘",
};

export function StageRail({
  stages, current, onSelect,
}: { stages: RailStage[]; current?: string; onSelect?: (key: string) => void }) {
  return (
    <div className="rail" role="tablist" aria-label="Recovery stages">
      {stages.map((s) => (
        <button
          key={s.key}
          type="button"
          role="tab"
          className="st"
          data-status={s.status}
          aria-current={current === s.key ? "true" : undefined}
          onClick={onSelect ? () => onSelect(s.key) : undefined}
          title={s.detail}
        >
          <span className="k">
            <span className="g" aria-hidden="true">
              {s.status === "RUNNING" ? <span className="spin">◌</span> : RAIL_GLYPH[s.status]}
            </span>
            {s.key}
          </span>
          <span className="v">{s.detail ?? s.status.toLowerCase()}</span>
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------- scorecard -- */

export interface ScoreCell {
  key: string;      // "Identity", "Runtime parameters", …
  value: string;    // "14 / 14", "UNVERIFIED", "0 %"
  detail?: string;  // evidence state carried in the label, e.g. "VERIFIED_RUNTIME"
  onOpen?: () => void;
}

export function Scorecard({ cells }: { cells: ScoreCell[] }) {
  return (
    <div className="score">
      {cells.map((c) => (
        <button key={c.key} type="button" className="cell" onClick={c.onOpen} disabled={!c.onOpen}>
          <span className="k">{c.key}</span>
          <span className="v">{c.value}</span>
          {c.detail && <span className="d">{c.detail}</span>}
        </button>
      ))}
    </div>
  );
}
