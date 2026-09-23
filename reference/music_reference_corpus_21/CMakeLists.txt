cmake_minimum_required(VERSION 3.20)
project(music_reference_corpus LANGUAGES CXX)

add_library(musicref INTERFACE)
target_include_directories(musicref INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(musicref INTERFACE cxx_std_17)

option(MUSICREF_BUILD_TESTS "Build smoke tests" ON)
if(MUSICREF_BUILD_TESTS)
    add_executable(musicref_smoke tests/smoke.cpp)
    target_link_libraries(musicref_smoke PRIVATE musicref)
endif()

add_executable(musicref_example examples/reference_chain.cpp)
target_link_libraries(musicref_example PRIVATE musicref)
