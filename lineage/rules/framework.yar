// Framework markers (CANDIDATE_LIBRARY): a plugin built on JUCE / the VST3 SDK.
rule AB_Framework_JUCE : framework
{
    meta:
        framework = "JUCE"
    strings:
        $a = "juce::" ascii
        $b = "_ZN4juce" ascii
        $c = "JUCE v" ascii
        $d = "juce_" ascii
        $e = "AudioProcessorValueTreeState" ascii wide
    condition:
        2 of them
}

rule AB_Framework_VST3SDK : framework
{
    meta:
        framework = "VST3 SDK"
    strings:
        $a = "GetPluginFactory" ascii
        $b = "Steinberg" ascii wide
        $c = "IPluginFactory" ascii
    condition:
        $a and 1 of ($b, $c)
}

rule AB_Framework_iPlug2 : framework
{
    meta:
        framework = "iPlug2"
    strings:
        $a = "iplug::" ascii
        $b = "_ZN5iplug" ascii
        $c = "IPlugAPIBase" ascii
        $d = "IGraphics" ascii
    condition:
        2 of them
}
