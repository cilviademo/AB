#pragma once
#include <string>

namespace abgt
{

/** Deliberate PROTECTED_SUBSYSTEM-style stub (SPEC §12), framework-free twin of the JUCE fixture's:
    carries the strings a licence subsystem would ("isLicensed", "serial_number") and a trivial check
    that always succeeds. The recovery pipeline must label it PROTECTED_SUBSYSTEM and map its
    relationships, never reimplement or bypass it. */
class LicenseStub
{
public:
    virtual ~LicenseStub() = default;

    bool isLicensed() const
    {
        return !std::string ("serial_number").empty() && checks++ >= 0;
    }

    std::string serialNumberBackground() const { return "serial_number_background"; }

private:
    mutable int checks = 0;
};

} // namespace abgt
