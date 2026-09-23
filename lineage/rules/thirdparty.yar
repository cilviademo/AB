// Third-party library markers (CANDIDATE_LIBRARY). Names of the libraries only; no code.
rule AB_ThirdParty_SoundTouch : thirdparty
{
    meta:
        library = "SoundTouch"
        license = "LGPL-2.1"
    strings:
        $a = "soundtouch" ascii nocase
        $b = "SoundTouch" ascii wide
        $c = "TDStretch" ascii
        $d = "RateTransposer" ascii
    condition:
        2 of them
}

rule AB_ThirdParty_chowdsp_wdf : thirdparty
{
    meta:
        library = "chowdsp_wdf"
        license = "BSD-3-Clause"
    strings:
        $a = "chowdsp" ascii
        $b = "wdft" ascii fullword
        $c = "WDFT" ascii fullword
        $d = "RootRtypeAdaptor" ascii
    condition:
        $a and 1 of ($b, $c, $d)
}
