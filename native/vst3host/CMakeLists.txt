cmake_minimum_required(VERSION 3.22)
project(vst3host VERSION 0.1.0 LANGUAGES C CXX)

# AB's isolated VST3 host (SPEC §7, EXECUTE 2.1). One plugin per process, JSON in,
# JSON out, hard timeout, documented exit codes. Links the Steinberg SDK hosting
# classes; the SDK is cloned into third_party/vst3sdk by build_all.{sh,ps1}
# (never vendored). Licence: BLOCKERS B-002.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release)
endif()

if(NOT DEFINED VST3_SDK_DIR)
    if(DEFINED ENV{VST3_SDK_DIR})
        set(VST3_SDK_DIR "$ENV{VST3_SDK_DIR}")
    else()
        set(VST3_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/vst3sdk")
    endif()
endif()
if(NOT EXISTS "${VST3_SDK_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "VST3 SDK not found at ${VST3_SDK_DIR}; run build_all.sh / build_all.ps1 or set VST3_SDK_DIR")
endif()

set(SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SMTG_ENABLE_VST3_HOSTING_EXAMPLES OFF CACHE BOOL "" FORCE)
set(SMTG_ENABLE_VSTGUI_SUPPORT OFF CACHE BOOL "" FORCE)
set(SMTG_ADD_VSTGUI OFF CACHE BOOL "" FORCE)
set(SMTG_RUN_VST_VALIDATOR OFF CACHE BOOL "" FORCE)
set(SMTG_CREATE_PLUGIN_LINK OFF CACHE BOOL "" FORCE)
set(SMTG_ENABLE_VST3_CORE_AUDIO_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory("${VST3_SDK_DIR}" vst3sdk EXCLUDE_FROM_ALL)

# sdk_hosting omits the platform module loader, PlugProvider and MemoryStream (the SDK's own
# validator adds them per target); they are compiled into the host here.
set(AB_SDK_EXTRA
    "${VST3_SDK_DIR}/public.sdk/source/common/memorystream.cpp"
    "${VST3_SDK_DIR}/public.sdk/source/vst/hosting/plugprovider.cpp")
if(WIN32)
    list(APPEND AB_SDK_EXTRA "${VST3_SDK_DIR}/public.sdk/source/vst/hosting/module_win32.cpp")
elseif(APPLE)
    list(APPEND AB_SDK_EXTRA "${VST3_SDK_DIR}/public.sdk/source/vst/hosting/module_mac.mm")
else()
    list(APPEND AB_SDK_EXTRA "${VST3_SDK_DIR}/public.sdk/source/vst/hosting/module_linux.cpp")
endif()
add_executable(vst3host src/main.cpp src/host.cpp ${AB_SDK_EXTRA})
target_include_directories(vst3host PRIVATE "${VST3_SDK_DIR}" src)
target_link_libraries(vst3host PRIVATE sdk_hosting base pluginterfaces)
target_compile_definitions(vst3host PRIVATE VST3HOST_VERSION="${PROJECT_VERSION}")
if(WIN32)
    target_compile_definitions(vst3host PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
elseif(APPLE)
    target_link_libraries(vst3host PRIVATE "-framework CoreFoundation")
else()
    find_package(Threads REQUIRED)
    target_link_libraries(vst3host PRIVATE Threads::Threads ${CMAKE_DL_LIBS})
endif()
if(MSVC)
    target_compile_options(vst3host PRIVATE /W3 /EHsc)
else()
    target_compile_options(vst3host PRIVATE -Wall -Wextra -Wno-unused-parameter)
endif()
install(TARGETS vst3host RUNTIME DESTINATION bin)
