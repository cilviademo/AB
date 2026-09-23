// AB — Artifact Bench · candidate-family rules (EXECUTE_ADDENDUM_A §A4)
// Derived from corpus evidence (reference/music_reference_corpus_21/catalog/plugin_families.json,
// docs/CLAUDE_CODE_PROMPT.md corpus priors). Output is CANDIDATE_FAMILY only: markers, never lineage proof.
// Rule names map to AB.Family.* (underscores in YARA identifiers).

rule AB_Family_GenA_StudioSafari : family gen_a
{
    meta:
        family = "GEN_A_STUDIO_SAFARI"
        label = "Gen A Studio/Safari"
        basis = "corpus class-set signals: StudioChainEffect/StudioNodeEffect/SafariPlugin/ModulationManager, Morph* chain, SoundTouch, pitch/tuner family"
    strings:
        $s1 = "StudioChainEffect" ascii wide
        $s2 = "StudioNodeEffect" ascii wide
        $s3 = "SafariPlugin" ascii wide
        $s4 = "ModulationManager" ascii wide
        $s5 = "MorphEffect" ascii wide
        $s6 = "pitchcommon" ascii wide
        $s7 = "tdps" ascii wide fullword
    condition:
        2 of ($s*)
}

rule AB_Family_GenB_MorphWDF : family gen_b
{
    meta:
        family = "GEN_B_MORPH_WDF"
        label = "Gen B Morph/WDF"
        basis = "corpus class-set signals: chowdsp::wdft, MorphDiodeClipper, MorphBaxendell, MorphCurrentDivider, resonators"
    strings:
        $s1 = "MorphDiodeClipper" ascii wide
        $s2 = "MorphBaxendell" ascii wide
        $s3 = "MorphCurrentDivider" ascii wide
        $s4 = "wdft" ascii wide fullword
        $s5 = "Resonator" ascii wide
    condition:
        2 of ($s*)
}

rule AB_Family_GenC_Hammer : family gen_c
{
    meta:
        family = "GEN_C_HAMMER"
        label = "Gen C Hammer"
        basis = "corpus class-set signals: HammerEffectBase, DisotrtionEffect (typo), ParametericEQ (typo), CompressorEffect, GlobalPresetBox/RotaryKnob/ImageToggleButton kit"
    strings:
        $s1 = "HammerEffectBase" ascii wide
        $s2 = "DisotrtionEffect" ascii wide
        $s3 = "ParametericEQ" ascii wide
        $s4 = "CompressorEffect" ascii wide
        $s5 = "GlobalPresetBox" ascii wide
        $s6 = "ImageToggleButton" ascii wide
        $s7 = "RotaryKnob" ascii wide
    condition:
        2 of ($s*)
}

rule AB_Lineage_TypoFingerprint : supporting
{
    meta:
        label = "SYMBOL_LINEAGE_FINGERPRINT (recurring uncommon spellings) — supporting evidence only"
    strings:
        $t1 = "DisotrtionEffect" ascii wide
        $t2 = "ParametericEQ" ascii wide
    condition:
        any of them
}
