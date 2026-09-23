cmake_minimum_required(VERSION 3.22)
project(ABGroundTruth VERSION 1.0.0 LANGUAGES C CXX)

# Ground-truth fixture (SPEC §12): a small JUCE plugin WITH source. Built three ways by
# build_all.{ps1,sh}: Debug+PDB, Release+PDB, Release stripped. The stripped build is the
# recovery input; spec.json/truth.json is the answer key. Identity below is the fixture's own
# (this is our plugin), so FIDELITY builds of its recovery can be compared against it.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED JUCE_DIR)
    set(JUCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/JUCE")
endif()
if(NOT EXISTS "${JUCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "JUCE not found at ${JUCE_DIR}. Run build_all.ps1 / build_all.sh (they clone JUCE 8.0.9) or pass -DJUCE_DIR=...")
endif()
add_subdirectory("${JUCE_DIR}" JUCE EXCLUDE_FROM_ALL)

juce_add_plugin(ABGroundTruth
    COMPANY_NAME "Multibanded"
    PLUGIN_MANUFACTURER_CODE Mbnd
    PLUGIN_CODE Abgt
    FORMATS VST3
    PRODUCT_NAME "ABGroundTruth"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    COPY_PLUGIN_AFTER_BUILD FALSE
    VST3_CATEGORIES Fx Distortion)

juce_add_binary_data(ABGroundTruthData SOURCES
    Resources/knob.png
    Resources/ABMono.ttf
    Presets/Init.xml)

target_sources(ABGroundTruth PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp)

target_compile_definitions(ABGroundTruth PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(ABGroundTruth PRIVATE
    ABGroundTruthData
    juce::juce_audio_utils
    juce::juce_dsp
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)

# The three variants are selected by CMAKE_BUILD_TYPE + AB_STRIP (see build_all.*):
#   Debug            → Debug + symbols
#   Release          → Release + symbols (/Zi /DEBUG on MSVC, -g elsewhere)
#   Release, AB_STRIP=ON → Release stripped (no PDB / symbols removed) = the recovery input
option(AB_STRIP "Strip symbols from the Release build (recovery input)" OFF)
# juce_add_plugin creates the shared-code target ABGroundTruth and the format target ABGroundTruth_VST3;
# link options must go on the format target (the one that produces the .vst3/.so/.dll) or they never apply.
# (The first fixture build put -s on the shared-code target and shipped a .so with a full .symtab — see STATUS.)
foreach(tgt ABGroundTruth ABGroundTruth_VST3 ABGroundTruthData)
    if(MSVC)
        if(AB_STRIP)
            target_link_options(${tgt} PRIVATE /DEBUG:NONE)
        else()
            target_compile_options(${tgt} PRIVATE /Zi)
            target_link_options(${tgt} PRIVATE /DEBUG:FULL)
        endif()
    else()
        if(AB_STRIP)
            target_compile_options(${tgt} PRIVATE -fvisibility=hidden -fvisibility-inlines-hidden)
            target_link_options(${tgt} PRIVATE -s -Wl,--exclude-libs,ALL)
        else()
            target_compile_options(${tgt} PRIVATE -g)
        endif()
    endif()
endforeach()
