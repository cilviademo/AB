#pragma once
#include <juce_core/juce_core.h>

namespace abgt
{

/** Deliberate LICENSING_AND_ENTITLEMENT_SUBSYSTEM stub (SPEC §12, ADDENDUM C2): a serial check and a demo
    state, so licensing recovery is measured with the same metrics as the DSP. It carries the strings a
    licence subsystem would ("isLicensed", "serial_number", "demo") and a small, fully specified algorithm:

      serial format  ABGT-XXXX-XXXX-CCCC   (groups of 4 upper-case alphanumerics)
      CCCC           hex16 of the sum of the 8 middle characters' ASCII codes (upper case)
      licensed       every group present, CCCC equals the checksum
      demo           not licensed: a render budget counts down (no audible effect in the fixture)

    The recovery pipeline classifies it LICENSING_AND_ENTITLEMENT_SUBSYSTEM, recovers the interface, the
    state relationships (demoMode / serialChecksum in the ValueTree) and the algorithm like any other
    subsystem. Replacing checkSerial with `return true` is a TRANSFORMED_BREAKING transformation. */
class LicenseStub
{
public:
    virtual ~LicenseStub() = default;

    static int checksumOf (const juce::String& middle) noexcept
    {
        int sum = 0;
        for (auto c : middle) sum += (int) c;
        return sum & 0xFFFF;
    }

    bool checkSerial (const juce::String& serial) noexcept
    {
        ++checks;
        auto parts = juce::StringArray::fromTokens (serial.trim().toUpperCase(), "-", "");
        if (parts.size() != 4 || parts[0] != "ABGT")
            return licensed = false;
        for (int i = 1; i < 4; ++i)
            if (parts[i].length() != 4)
                return licensed = false;
        lastChecksum = checksumOf (parts[1] + parts[2]);
        licensed = parts[3].getHexValue32() == lastChecksum;
        if (licensed) demoRenders = -1;
        return licensed;
    }

    bool isLicensed() const noexcept { return licensed; }
    bool isDemo() const noexcept { return ! licensed; }
    int demoRendersRemaining() const noexcept { return demoRenders; }
    int lastSerialChecksum() const noexcept { return lastChecksum; }
    void noteRender() noexcept { if (! licensed && demoRenders > 0) --demoRenders; }

    juce::String serialNumberBackground() const { return "serial_number_background"; }

private:
    bool licensed = false;
    int demoRenders = 100000;
    int lastChecksum = 0;
    mutable int checks = 0;
};

} // namespace abgt
