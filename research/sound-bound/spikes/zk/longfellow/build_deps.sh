#!/bin/sh
# Build googletest + google/benchmark from vendor/ into vendor/deps (no brew install needed).
# usage (from zk/): tools/heavy.sh lf-deps sh longfellow/build_deps.sh
set -e
V=$(cd "$(dirname "$0")/../vendor" && pwd)
cmake -S $V/googletest -B $V/googletest/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$V/deps -DBUILD_GMOCK=ON >/dev/null
cmake --build $V/googletest/build -j 4 >/dev/null && cmake --install $V/googletest/build >/dev/null
cmake -S $V/benchmark -B $V/benchmark/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$V/deps -DBENCHMARK_ENABLE_TESTING=OFF -DBENCHMARK_ENABLE_GTEST_TESTS=OFF >/dev/null
cmake --build $V/benchmark/build -j 4 >/dev/null && cmake --install $V/benchmark/build >/dev/null
echo deps ok
