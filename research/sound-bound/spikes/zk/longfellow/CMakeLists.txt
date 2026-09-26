# Builds sbzk against the vendored longfellow-zk sources (header-only circuits
# plus a few .cc files). No gtest/benchmark needed for sbzk itself.
cmake_minimum_required(VERSION 3.13)
project(sbzk CXX)
set(CMAKE_CXX_STANDARD 17)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(LF ${CMAKE_CURRENT_SOURCE_DIR}/../vendor/longfellow-zk/lib)
add_compile_definitions(OPENSSL_SUPPRESS_DEPRECATED=1)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64")
  add_compile_options(-mcpu=apple-m1 -march=armv8-a+crypto)
endif()
# test-only forging prover (see gen_forge.sh), generated from vendor sources
execute_process(COMMAND sh ${CMAKE_CURRENT_SOURCE_DIR}/gen_forge.sh ${LF} ${CMAKE_BINARY_DIR}/forge
                COMMAND_ERROR_IS_FATAL ANY)
include_directories(${LF} ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_BINARY_DIR}/forge /opt/homebrew/include)
link_directories(/opt/homebrew/lib)
add_executable(sbzk sbzk.cc
  ${LF}/util/log.cc ${LF}/util/crypto.cc
  ${LF}/algebra/nat.cc ${LF}/algebra/crt.cc
  ${LF}/ec/p256.cc
  ${LF}/circuits/sha/flatsha256_witness.cc ${LF}/circuits/sha/sha256_constants.cc)
target_link_libraries(sbzk crypto zstd)
