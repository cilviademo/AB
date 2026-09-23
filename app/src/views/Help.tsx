import { Section } from "../components/ui";

/** In-app help, sourced from docs/PLUGIN_RECOVERY_BENCH.md (the functional description). */
export function Help() {
  return (
    <div className="view enter">
      <div className="label">Help</div>
      <h1 className="title" style={{ marginTop: "var(--s3)" }}>How AB recovers a plugin</h1>
      <p className="copy" style={{ marginTop: "var(--s4)" }}>
        Drop the compiled plugin, then keep dropping anything else you have: presets, DAW sessions, old build
        folders, a .pdb, source fragments, assets, installers, related binaries. Each drop adds evidence and can
        fill in more of the reconstructed repo. Nothing leaves your device.
      </p>
      <div className="stack-8" style={{ marginTop: "var(--s7)" }}>
        <Section title="Evidence labels">
          <table className="grid"><tbody>
            <tr><td className="mono">VERIFIED</td><td>directly recovered or confirmed by authoritative runtime/build evidence</td></tr>
            <tr><td className="mono">INFERRED</td><td>strongly supported but not proven</td></tr>
            <tr><td className="mono">CANDIDATE</td><td>plausible evidence requiring validation</td></tr>
            <tr><td className="mono">GENERATED</td><td>reconstruction or scaffold created by the tool</td></tr>
            <tr><td className="mono">UNRECOVERABLE</td><td>removed or unavailable in the compiled artifact</td></tr>
          </tbody></table>
        </Section>
        <Section title="Stages">
          <table className="grid"><tbody>
            <tr><td className="mono">INGEST</td><td>inventory and hash everything; group by plugin bundle; attach presets, sessions, sources, symbols</td></tr>
            <tr><td className="mono">STATIC</td><td>Static Recovery v2: identity hints, strings, RTTI names, state XML, carved resources, BinaryData names, build paths</td></tr>
            <tr><td className="mono">RUNTIME</td><td>isolated vst3host: factory, FUIDs, exported parameters, units, buses, latency, state; the only source of VST3_EXPORTED_PARAMETER</td></tr>
            <tr><td className="mono">DECOMPILE</td><td>Ghidra: RTTI classes, vtables, callgraph from processBlock, DSP candidates, fingerprints</td></tr>
            <tr><td className="mono">PROBE</td><td>deterministic signals through the original: impulse, DC, ramp, sine, sweep, noise, two-tone</td></tr>
            <tr><td className="mono">RECONSTRUCT</td><td>evidence source → concise human source; promotion to Active only when BEHAVIOR_MATCHED</td></tr>
            <tr><td className="mono">BUILD</td><td>FIDELITY (recovered identity) or SURROGATE (temporary identity, never session-compatible)</td></tr>
            <tr><td className="mono">COMPARE</td><td>pluginval and the original-vs-rebuild differential: BIT_EXACT … FAILED</td></tr>
            <tr><td className="mono">EXPORT</td><td>00_manifest … 07_agent_handoff, UNRECOVERABLE.md, GIT_READY checklist, ZIP, agent handoff</td></tr>
          </tbody></table>
        </Section>
        <Section title="Parameters are not XML keys">
          <p className="copy">
            A <span className="mono">&lt;PARAM&gt;</span> in embedded XML proves a serialized key exists. Only the runtime host
            can say whether it is a VST3_EXPORTED_PARAMETER, a STATE_SCHEMA_FIELD, a PRESET_FIELD, a UI_ONLY_CONTROL or an
            UNKNOWN_PROPERTY. Observed values stay <span className="mono">observed_serialized_values</span> with
            representation UNKNOWN until the state-differential harness resolves them.
          </p>
        </Section>
        <Section title="Context tags">
          <p className="copy">
            AB runs the same pipeline on every artifact by technical capability and makes no ownership determination. Two
            optional tags — usage context (my recovery · known-source fixture · black-box reference · source-available
            reference) and source availability — only change how reports read: "binary-derived" versus "validated against
            known source". Known-source fixture source is withheld from recovery and read only by the evaluator; reference
            code is never copied into your project unless you choose to.
          </p>
          <p className="copy">
            Licensing and entitlement code is a normal subsystem (LICENSING_AND_ENTITLEMENT_SUBSYSTEM): recovered,
            reconstructed, transformed and validated like DSP. Replacing a validation with a constant is a
            TRANSFORMED_BREAKING transformation, recorded in the transformation graph — never labelled recovery and never
            silent.
          </p>
        </Section>
      </div>
      <div style={{ marginTop: "var(--s8)" }}>
        <Section title="Reference library">
          <p className="copy">
            Every entry AB can learn from is typed — user artifact, known-source fixture, black-box reference, framework
            signature, clean-room DSP reference — and records its origin, source artifact, licence, hash, analysis
            version, evidence state, verification date and relationships, so "where did AB learn this?" always has an
            answer. Actions (Compare Against Reference, Add as Fixture, Use as Black-Box Reference, Validate Recovery
            Against Source) are buttons you press; dropping two plugins together never implies any of them. Fixture
            source is checked byte-for-byte against every user project and reported if it ever leaks.
          </p>
        </Section>
      </div>
    </div>
  );
}
