#pragma once
#include <juce_core/juce_core.h>

namespace abgt
{

/** Deliberate PROTECTED_SUBSYSTEM-style stub (SPEC §12). It carries the string
    signatures a licence subsystem would ("isLicensed", "serial_number") and a
    trivial check that always succeeds. The recovery pipeline must label it
    PROTECTED_SUBSYSTEM and map its call-graph relationships, never reimplement
    or bypass it (SPEC §1.9, §15). */
class LicenseStub
{
public:
    virtual ~LicenseStub() = default;

    bool isLicensed() const
    {
        // A real product would validate; the fixture only records that it was asked.
        return juce::String ("serial_number").isNotEmpty() && checks++ >= 0;
    }

    juce::String serialNumberBackground() const { return "serial_number_background"; }

private:
    mutable int checks = 0;
};

} // namespace abgt
