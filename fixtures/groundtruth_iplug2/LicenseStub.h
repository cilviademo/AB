#pragma once
#include <string>
#include <vector>

namespace abgt
{

/** Deliberate LICENSING_AND_ENTITLEMENT_SUBSYSTEM stub (ADDENDUM C2), framework-free twin of the JUCE fixture's:
    serial format ABGT-XXXX-XXXX-CCCC, CCCC = hex16 of the sum of the 8 middle characters; not licensed = demo state
    with a render budget. Recovered, reconstructed and validated like the DSP; `checkSerial → true` is TRANSFORMED_BREAKING. */
class LicenseStub
{
public:
    virtual ~LicenseStub() = default;

    static int checksumOf (const std::string& middle) noexcept
    {
        int sum = 0;
        for (unsigned char c : middle) sum += (int) c;
        return sum & 0xFFFF;
    }

    bool checkSerial (std::string serial) noexcept
    {
        ++checks;
        for (auto& c : serial) c = (char) toupper ((unsigned char) c);
        std::vector<std::string> parts;
        size_t start = 0;
        for (;;)
        {
            const size_t dash = serial.find ('-', start);
            parts.push_back (serial.substr (start, dash == std::string::npos ? std::string::npos : dash - start));
            if (dash == std::string::npos) break;
            start = dash + 1;
        }
        if (parts.size() != 4 || parts[0] != "ABGT") return licensed = false;
        for (int i = 1; i < 4; ++i) if (parts[i].size() != 4) return licensed = false;
        lastChecksum = checksumOf (parts[1] + parts[2]);
        licensed = (int) std::stoul (parts[3], nullptr, 16) == lastChecksum;
        if (licensed) demoRenders = -1;
        return licensed;
    }

    bool isLicensed() const noexcept { return licensed; }
    bool isDemo() const noexcept { return ! licensed; }
    int demoRendersRemaining() const noexcept { return demoRenders; }
    int lastSerialChecksum() const noexcept { return lastChecksum; }
    void noteRender() noexcept { if (! licensed && demoRenders > 0) --demoRenders; }
    std::string serialNumberBackground() const { return "serial_number_background"; }

private:
    bool licensed = false;
    int demoRenders = 100000;
    int lastChecksum = 0;
    mutable int checks = 0;
};

} // namespace abgt
