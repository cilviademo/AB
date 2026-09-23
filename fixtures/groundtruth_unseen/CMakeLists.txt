cmake_minimum_required(VERSION 3.22)
project(ABUnseen VERSION 0.3.1 LANGUAGES C CXX)
# Unseen known-source fixture (ADDENDUM B8 acceptance test 1). Same build rules as fixtures/groundtruth.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT DEFINED JUCE_DIR)
    set(JUCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../groundtruth/third_party/JUCE")
endif()
if(NOT EXISTS "${JUCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "JUCE not found at ${JUCE_DIR}. Build fixtures/groundtruth first (it clones JUCE 8.0.9) or pass -DJUCE_DIR=...")
endif()
add_subdirectory("${JUCE_DIR}" JUCE EXCLUDE_FROM_ALL)
juce_add_plugin(ABUnseen
    COMPANY_NAME "Multibanded"
    PLUGIN_MANUFACTURER_CODE Mbnd
    PLUGIN_CODE Abus
    FORMATS VST3
    PRODUCT_NAME "ABUnseen"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    COPY_PLUGIN_AFTER_BUILD FALSE
    VST3_CATEGORIES Fx Distortion)
juce_add_binary_data(ABUnseenData SOURCES Resources/dial.png Presets/Default.xml)
target_sources(ABUnseen PRIVATE Source/PluginProcessor.cpp Source/PluginEditor.cpp)
target_compile_definitions(ABUnseen PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0 JUCE_DISPLAY_SPLASH_SCREEN=0)
target_link_libraries(ABUnseen PRIVATE ABUnseenData juce::juce_audio_utils juce::juce_dsp PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
option(AB_STRIP "Strip symbols from the Release build (recovery input)" OFF)
foreach(tgt ABUnseen ABUnseen_VST3 ABUnseenData)
    if(MSVC)
        if(AB_STRIP)
            target_link_options(${tgt} PRIVATE /DEBUG:NONE)
        else()
            target_compile_options(${tgt} PRIVATE /Zi)
            target_link_options(${tgt} PRIVATE /DEBUG:FULL)
        endif()
    else()
        target_compile_options(${tgt} PRIVATE -fvisibility=hidden -fvisibility-inlines-hidden)
        if(AB_STRIP)
            target_link_options(${tgt} PRIVATE -s)
        else()
            target_compile_options(${tgt} PRIVATE -g)
        endif()
    endif()
endforeach()
