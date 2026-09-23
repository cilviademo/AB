"""AB (Artifact Bench) engine.

The Python sidecar behind the Tauri shell: job system, object store, ingest,
worker supervision (vst3host, Ghidra, build, pluginval), correlation,
fingerprints, behaviour fits, reconstruction generators and bundle assembly.
Every method exposed over the stdio RPC has a CLI twin in ``ab_engine.cli``.
"""

__version__ = "0.1.0"

#: Identifies the engine in every ``{schema, schema_version, tool, generated, data}`` envelope.
TOOL = f"ab-engine {__version__}"
