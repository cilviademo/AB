"""ADDENDUM C2: licensing is a normal subsystem; a check replaced by a constant is TRANSFORMED_BREAKING."""
from __future__ import annotations

from pathlib import Path

from ab_engine.decompile import roles
from ab_engine.transform import licensing as lic

EVIDENCE = """
bool abgt::LicenseStub::checkSerial(juce::String *serial)
{
  ++this->checks;
  parts = StringArray::fromTokens(serial);
  if (parts.size != 4 || parts[0] != "ABGT") { this->licensed = false; return false; }
  this->lastChecksum = checksumOf(parts[1] + parts[2]);
  this->licensed = parts[3].getHexValue32() == this->lastChecksum;
  return this->licensed;
}
bool abgt::LicenseStub::isLicensed(void) { return this->licensed; }
"""

FAITHFUL = """
bool LicenseStub::checkSerial (const juce::String& serial)
{
    ++checks;
    auto parts = juce::StringArray::fromTokens (serial, "-", "");
    if (parts.size() != 4 || parts[0] != "ABGT") return licensed = false;
    lastChecksum = checksumOf (parts[1] + parts[2]);
    licensed = parts[3].getHexValue32() == lastChecksum;
    return licensed;
}
bool LicenseStub::isLicensed() const { return licensed; }
"""

BYPASS = """
// "just make it work"
bool LicenseStub::checkSerial (const juce::String& serial)
{
    return true;
}
bool LicenseStub::isLicensed() const { licensed = true; return true; }
"""


def test_role_alias_and_vocabulary():
    assert roles.canonical_role("PROTECTED_SUBSYSTEM") == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
    assert roles.STATIC_TO_FINAL["PROTECTED_SUBSYSTEM"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
    assert "PROTECTED_SUBSYSTEM" not in roles.ROLES and roles.LICENSING_ROLE in roles.ROLES
    assert lic.is_licensing_role("PROTECTED_SUBSYSTEM") and lic.is_licensing_role(roles.LICENSING_ROLE) and not lic.is_licensing_role("FILTER")
    assert lic.looks_like_license_state("serialChecksum") and lic.looks_like_license_state("demoMode") and not lic.looks_like_license_state("cutoff")


def test_faithful_reconstruction_is_not_a_bypass():
    assert lic.detect_bypass(FAITHFUL, symbols=["abgt::LicenseStub::checkSerial", "abgt::LicenseStub::isLicensed"], evidence_text=EVIDENCE) == []
    # isLicensed returns a member in both: constant-looking but not a constant — no finding
    assert lic.detect_bypass("bool X::isLicensed() const { return licensed; }", evidence_text=EVIDENCE) == []


def test_bypass_edit_is_transformed_breaking_never_recovery():
    f = lic.detect_bypass(BYPASS, symbols=["abgt::LicenseStub::checkSerial", "abgt::LicenseStub::isLicensed"], evidence_text=EVIDENCE)
    by = {x["symbol"].split("::")[-1]: x for x in f}
    assert by["checkSerial"]["status"] == "TRANSFORMED_BREAKING" and by["checkSerial"]["kind"] == "CONSTANT_RETURN"
    assert by["checkSerial"]["labelled_as"] == "transformation (never recovery)" and by["checkSerial"]["subsystem"] == "LICENSING_AND_ENTITLEMENT_SUBSYSTEM"
    # the original isLicensed() only reads the member; forcing the flag there changes state → breaking too
    assert by["isLicensed"]["kind"] == "FORCED_FLAG" and by["isLicensed"]["status"] == "TRANSFORMED_BREAKING"


def test_bypass_without_evidence_needs_manual_review(tmp_path: Path):
    f = lic.detect_bypass(BYPASS, symbols=["checkSerial"])
    assert f and f[0]["status"] == "LICENSE_REQUIRES_MANUAL_REVIEW"
    # tree scan: Source/Active with the bypass, evidence_source with the decompiled original
    (tmp_path / "Source" / "Active").mkdir(parents=True)
    (tmp_path / "evidence_source").mkdir()
    (tmp_path / "Source" / "Active" / "LicenseStub.cpp").write_text(BYPASS, encoding="utf-8")
    (tmp_path / "evidence_source" / "LicenseStub.c").write_text(EVIDENCE, encoding="utf-8")
    rows = lic.scan_tree(tmp_path / "Source" / "Active", symbols=["abgt::LicenseStub::checkSerial"], evidence_root=tmp_path / "evidence_source")
    assert rows and rows[0]["file"] == "LicenseStub.cpp" and rows[0]["status"] == "TRANSFORMED_BREAKING"
