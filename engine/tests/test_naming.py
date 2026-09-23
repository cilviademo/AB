"""docs/NAMING_CANONICALIZATION.md — names are evidence + transformable identifiers, never a capability gate."""
from __future__ import annotations

from ab_engine.naming import canonical as nm

CLASSES = [
    {"original": "SSLChannelStripProcessor", "address": "0x1000", "source": "MSVC_RTTI", "role": "AUDIO_LOOP", "role_status": "VERIFIED_CALLGRAPH"},
    {"original": "SSLComp", "address": "0x2000", "source": "MSVC_RTTI", "role": "COMPRESSOR", "role_status": "VERIFIED_CALLGRAPH"},
    {"original": "SSLBusComp", "address": "0x2100", "source": "MSVC_RTTI", "role": "COMPRESSOR", "role_status": "VERIFIED_CALLGRAPH"},
    {"original": "SSL_EQ", "address": "0x3000", "source": "MSVC_RTTI", "role": "FILTER", "role_status": "CANDIDATE"},
    {"original": "SSLDrive", "address": "0x4000", "source": "ITANIUM_RTTI_STRUCTURAL", "role": "WAVESHAPER", "role_status": "BEHAVIOR_MATCHED"},
    {"original": "SSLMystery", "address": "0x5000", "source": "MSVC_RTTI", "role": "UNKNOWN", "role_status": "CANDIDATE"},
    {"original": "SSL1176", "address": "0x5100", "source": "MSVC_RTTI", "role": "UNKNOWN", "role_status": "CANDIDATE"},
    {"original": "Comp1176", "address": "0x6000", "source": "MSVC_RTTI", "role": "COMPRESSOR", "role_status": "CANDIDATE"},
    {"original": "juce::AudioProcessor", "address": "0x7000", "source": "MSVC_RTTI", "role": "FRAMEWORK"},
    {"original": "PlainHelper", "address": "0x8000", "source": "MSVC_RTTI", "role": "UNKNOWN"},
]
PARAMS = [{"runtime_param_id": "SSLDrive", "display_name": "SSL Drive"}, {"runtime_param_id": 1234, "display_name": "Cutoff"}]
STATE = [{"key": "SSLCompThreshold"}, {"key": "cutoff"}]
RES = [{"binarydata_name": "ssl_knob_png", "filename": "ssl_knob.png", "sha256": "ab" * 32}]


def test_vendor_terms_are_inferred_from_recurring_prefixes_and_declared_identity():
    terms = nm.infer_vendor_terms([c["original"] for c in CLASSES], declared=["Multibanded"])
    assert terms["SSL"] == "VENDOR_REFERENCE" and terms["Multibanded"] == "VENDOR_REFERENCE"
    assert nm.categorize("Comp1176", terms) == "MODEL_NUMBER" and nm.categorize("PlainHelper", terms) == "NONE"
    assert nm.categorize("_ZN3abc3fooEv", terms) == "GENERATED_MANGLED" and nm.categorize("CON", terms) == "WINDOWS_ILLEGAL"


def test_preserve_mode_keeps_every_original_name():
    m = nm.build_map(classes=CLASSES, parameters=PARAMS, state_keys=STATE, resources=RES, mode="PRESERVE_ORIGINAL_NAMES")
    by = {r["original"]: r for r in m["identifiers"]}
    assert "juce::AudioProcessor" not in by                                   # framework never in the map
    assert all(r["active"] == r["original"].split("::")[-1] for r in m["identifiers"])
    assert by["SSLComp"]["semantic"] == "Compressor" and by["SSLComp"]["evidence_status"] == "VERIFIED_ORIGINAL_NAME"
    assert m["parameters"][0]["transformed_display_name"] == "SSL Drive" and m["state_keys"][0]["migration_status"] == "NOT_NEEDED"
    assert m["resources"][0]["new_filename"] == "ssl_knob.png" and m["reversible"] is True


def test_canonicalize_mode_neutralizes_names_but_never_ids_or_evidence():
    m = nm.build_map(classes=CLASSES, parameters=PARAMS, state_keys=STATE, resources=RES, mode="CANONICALIZE_NAMES")
    by = {r["original"]: r for r in m["identifiers"]}
    # supported roles get semantic names; architecture tokens keep two compressors apart (directive §7, §14)
    assert by["SSLChannelStripProcessor"]["active"] == "ChannelProcessor"
    assert by["SSLComp"]["active"] == "Compressor" and by["SSLBusComp"]["active"] == "BusCompressor"
    assert by["SSLDrive"]["active"] == "Saturation"
    # a CANDIDATE role gets no invented meaning: the vendor term is stripped, nothing more
    assert by["SSL_EQ"]["active"] == "EQ" and "no semantic claim" in by["SSL_EQ"]["semantic_basis"]
    # an unknown role keeps the original's own residue (not invented meaning); nothing left → placeholder, not a guess
    assert by["SSLMystery"]["active"] == "Mystery" and "no semantic claim" in by["SSLMystery"]["semantic_basis"]
    assert by["SSL1176"]["active"].startswith("RecoveredClass_") and "placeholder" in by["SSL1176"]["semantic_basis"]
    assert by["Comp1176"]["active"] == "Compressor_2" or by["Comp1176"]["active"].startswith("Compressor")   # model number stripped, collision-safe
    assert by["PlainHelper"]["active"] == "PlainHelper" and by["PlainHelper"]["reason"].startswith("no vendor")
    # every row keeps the original, its address and evidence; identity is declared untouched
    assert all(r["original"] and r["original_address"] and "function fingerprint" in r["identity_unchanged"] for r in m["identifiers"])
    # parameter ids untouched, display proposal made; state key gets a PROPOSED migration only; resource renamed with provenance
    assert m["parameters"][0]["runtime_param_id"] == "SSLDrive" and m["parameters"][0]["transformed_display_name"] == "Drive"
    assert m["parameters"][1]["transformed_display_name"] == "Cutoff"
    assert m["state_keys"][0] == {**m["state_keys"][0], "legacy": "SSLCompThreshold", "new": "CompressorThreshold", "migration_status": "PROPOSED"}
    assert m["resources"][0]["new_filename"] == "Knob.png" and m["resources"][0]["original_binarydata_name"] == "ssl_knob_png" and m["resources"][0]["sha256"] == "ab" * 32
    # no two originals collapse into one active name
    actives = [r["active"] for r in m["identifiers"]]
    assert len(actives) == len(set(actives))


def test_custom_map_and_search_both_name_spaces():
    m = nm.build_map(classes=CLASSES, mode="CUSTOM_RENAME_MAP", custom={"SSLChannelStripProcessor": "ConsoleChannelProcessor"})
    by = {r["original"]: r for r in m["identifiers"]}
    assert by["SSLChannelStripProcessor"]["active"] == "ConsoleChannelProcessor" and by["SSLChannelStripProcessor"]["reason"].startswith("CUSTOM_RENAME_MAP")
    assert by["SSLComp"]["active"] == "Compressor"                                  # unmapped names still canonicalize
    assert [h["original"] for h in nm.search(m, "consolechannel")] == ["SSLChannelStripProcessor"]   # transformed → original
    assert "SSLComp" in [h["original"] for h in nm.search(m, "SSLComp")]                                # original → transformed
    md = nm.to_markdown(m)
    assert "`SSLChannelStripProcessor`" in md and "`ConsoleChannelProcessor`" in md and "reversible" in md
