cmake_minimum_required(VERSION 3.22)
project(ABGroundTruthIP VERSION 1.0.0 LANGUAGES C CXX)

# Ground-truth fixture #2 on iPlug2 (ADDENDUM A5). Built by build_all.ps1 on Windows (BLOCKERS B-008:
# iPlug2 has no maintained Linux VST3 target, so this file is unverified in the dev environment).
# Uses iPlug2's CMake support (IPlug2/iPlug2.cmake); the VST3 SDK is fetched by iPlug2's own download script.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED IPLUG2_DIR)
    set(IPLUG2_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/iPlug2")
endif()
if(NOT EXISTS "${IPLUG2_DIR}/iPlug2.cmake")
    message(FATAL_ERROR "iPlug2 not found at ${IPLUG2_DIR}; run build_all.ps1 (clones the pinned iPlug2) or pass -DIPLUG2_DIR=...")
endif()
include("${IPLUG2_DIR}/iPlug2.cmake")
find_package(iPlug2 REQUIRED)

set(SRC ABGroundTruthIP.cpp ABGroundTruthIP.h Dsp.h LicenseStub.h GeneratedParams.h config.h)
set(RES_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../groundtruth")
set(RESOURCES "${RES_DIR}/Resources/knob.png" "${RES_DIR}/Resources/ABMono.ttf" "${RES_DIR}/Presets/Init.xml")

add_library(_base INTERFACE)
iplug_target_add(_base INTERFACE
    INCLUDE ${CMAKE_CURRENT_SOURCE_DIR}
    SOURCE ${SRC}
    RESOURCE ${RESOURCES}
    LINK iPlug2_IGraphics_Nano
)

option(AB_STRIP "Strip symbols from the Release build (recovery input)" OFF)
add_library(ABGroundTruthIP_vst3 MODULE ${SRC})
iplug_target_add(ABGroundTruthIP_vst3 PUBLIC LINK _base iPlug2_VST3)
iplug_configure_target(ABGroundTruthIP_vst3 vst3)
if(MSVC)
    if(AB_STRIP)
        target_link_options(ABGroundTruthIP_vst3 PRIVATE /DEBUG:NONE)
    else()
        target_compile_options(ABGroundTruthIP_vst3 PRIVATE /Zi)
        target_link_options(ABGroundTruthIP_vst3 PRIVATE /DEBUG:FULL)
    endif()
else()
    target_compile_options(ABGroundTruthIP_vst3 PRIVATE -fvisibility=hidden -fvisibility-inlines-hidden)
    if(AB_STRIP)
        target_link_options(ABGroundTruthIP_vst3 PRIVATE -s)
    else()
        target_compile_options(ABGroundTruthIP_vst3 PRIVATE -g)
    endif()
endif()
