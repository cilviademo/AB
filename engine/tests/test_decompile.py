"""Phase 3 unit tests: role scoring (§8.2/§8.6), BinaryData resolution by content (§8.4), fingerprint stability."""
from __future__ import annotations

from ab_engine.decompile import binarydata as bd
from ab_engine.decompile import roles, stability


def _fn(**kw):
    base = {"name": "FUN_1000", "size": 400, "float_ops": 40, "simd_ops": 0, "loops": 1, "libm_calls": 1, "sample_rate_refs": 0, "constant_refs": 0,
            "string_refs": 0, "dist_from_processBlock": 1, "seed_basis": "symbol"}
    base.update(kw)
    return base


def test_role_scoring_prefers_reachable_owned_dsp():
    ws = roles.score(_fn(), None, class_static_role="WAVESHAPER", is_owned=True, param_refs=1, noise=False, wrapper=False, demangled="abgt::TanhShaper::process(float)")
    assert ws["role"] == "WAVESHAPER" and ws["role_status"] == "VERIFIED_CALLGRAPH" and "agrees with the static class role" in ws["role_basis"]
    lib = roles.score(_fn(dist_from_processBlock=-1), None, class_static_role=None, is_owned=False, param_refs=0, noise=False, wrapper=False, demangled="OT::glyf_impl::Glyph::get_points")
    assert lib["priority"] < ws["priority"] and lib["role_status"] == "CANDIDATE"
    noise = roles.score(_fn(name="__cxa_throw"), None, class_static_role=None, is_owned=False, param_refs=0, noise=True, wrapper=False, demangled="__cxa_throw")
    assert noise["priority"] == 0.0 and noise["role_basis"] == ["noise suppression"]
    lic = roles.score(_fn(float_ops=0, loops=0, libm_calls=0), None, class_static_role=None, is_owned=True, param_refs=0, noise=False, wrapper=False, demangled="abgt::LicenseStub::isLicensed()")
    assert lic["role"] == "PROTECTED_SUBSYSTEM"
    coeff = roles.score(_fn(), {"CONSTANT_SIGNATURE": ["3.14159265", "48000"]}, class_static_role=None, is_owned=True, param_refs=0, noise=False, wrapper=False, demangled="FUN_2000")
    assert coeff["role"] == "FILTER_COEFFICIENT" and coeff["constants"].get("pi") == 1


def test_binarydata_resolution_by_content():
    carved = [{"name": "png_000.png", "sha256": "a" * 64}, {"name": "ttf_000.ttf", "sha256": "b" * 64}, {"name": "xml_001.xml", "sha256": "c" * 64}]
    # symbol path: names proven directly
    res = {"names": ["knob_png", "ABMono_ttf", "Init_xml"], "resources": [{"name": "knob_png", "basis": "symbol", "size": 790, "pointer": "0x1", "sha256": "a" * 64},
                                                                         {"name": "ABMono_ttf", "basis": "symbol", "size": 2288, "pointer": "0x2", "sha256": "b" * 64}]}
    rows = bd.resolve(res, carved, [])
    by = {r["binarydata_name"]: r for r in rows}
    assert by["knob_png"]["carved"] == "png_000.png" and by["knob_png"]["mapping_status"].startswith("VERIFIED (symbol")
    assert by["Init_xml"]["mapping_status"].startswith("UNRESOLVED")
    idx, renames = bd.apply_to_index([dict(c) for c in carved], rows)
    assert renames == {"png_000.png": "knob.png", "ttf_000.ttf": "ABMono.ttf"}
    # positional path: equal-length tables, name by position; unequal → bytes proven, name withheld
    res2 = {"names": ["x_png", "y_ttf"], "resources": [{"size": 1, "pointer": "0x1", "sha256": "a" * 64}, {"size": 2, "pointer": "0x2", "sha256": "b" * 64}]}
    rows2 = bd.resolve(res2, carved, [])
    assert [r["binarydata_name"] for r in rows2] == ["x_png", "y_ttf"] and all(r["mapping_status"].startswith("VERIFIED (getNamedResource") for r in rows2)
    res3 = {"names": ["x_png", "y_ttf", "z_xml"], "resources": [{"size": 1, "pointer": "0x1", "sha256": "a" * 64}]}
    rows3 = bd.resolve(res3, carved, [])
    assert rows3[0]["binarydata_name"] is None and rows3[0]["mapping_status"].startswith("VERIFIED_BYTES_NAME_UNRESOLVED")
    assert bd.juce_name_hash("knob_png") == bd.juce_name_hash("knob_png")
    # stripped path: the getNamedResource branch names the pair through its case constant (JUCE name hash)
    res4 = {"names": ["knob_png", "ABMono_ttf", "Init_xml"],
            "resources": [{"function": "0x81fc30", "name": "knob_png", "name_basis": "getNamedResource case constant -0x16f8fb20 == JUCE name hash of knob_png", "size": 790, "pointer": "0xa84658", "sha256": "a" * 64},
                          {"function": "0x81fc30", "name": None, "name_basis": None, "size": 360, "pointer": "0xa84668", "sha256": "c" * 64}]}
    rows4 = bd.resolve(res4, carved, [])
    by4 = {r["binarydata_name"]: r for r in rows4}
    assert by4["knob_png"]["carved"] == "png_000.png" and by4["knob_png"]["mapping_status"].startswith("VERIFIED (getNamedResource case constant == JUCE name hash")
    assert any(r["binarydata_name"] is None and r["mapping_status"].startswith("VERIFIED_BYTES_NAME_UNRESOLVED") for r in rows4)   # unnamed pair, tables of unequal length


def test_fingerprint_stability_matches_on_normalized_hash():
    def fp(addr, norm, cfg, raw, name=None, size=64):
        return {"addr": addr, "name": name, "size": size, "NORMALIZED_INSTRUCTION_HASH": norm, "CFG_SIGNATURE": {"hash": cfg}, "RAW_BYTE_HASH": raw}
    a = [fp("0x1", "n1", "c1", "r1", "processBlock"), fp("0x2", "n2", "c2", "r2", "tanh_shaper"), fp("0x3", "n3", "c3", "r3", "tiny", size=8)]
    b = [fp("0x10", "n1", "c1", "r9"), fp("0x20", "n2", "c2", "r2"), fp("0x30", "nX", "cX", "rX")]
    r = stability.compare(a, b)
    assert r["functions_a"] == 2 and r["matched"] == 2 and r["ok"] and r["raw_hash_equal"] == 1
    assert {m["name_a"] for m in r["matches"]} == {"processBlock", "tanh_shaper"}
