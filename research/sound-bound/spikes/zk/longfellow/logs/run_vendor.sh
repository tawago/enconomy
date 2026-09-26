set -x
vendor/longfellow-zk/clang-build-release/circuits/ecdsa/verify_test --benchmark_filter='BM_ECDSAZK' --benchmark_min_time=2x 
vendor/longfellow-zk/clang-build-release/circuits/tests/anoncred/small_test --benchmark_filter=BM_AnonCred --benchmark_min_time=3x
vendor/longfellow-zk/clang-build-release/circuits/sha/flatsha256_circuit_test --gtest_filter='*block_size*' --benchmark_filter='BM_ShaZK_fp2_128/(1|2|4|8)$' --benchmark_min_time=2x
