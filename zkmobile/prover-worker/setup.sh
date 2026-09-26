#!/bin/bash
# Remote prover worker on a fresh Ubuntu 24.04 x86_64 box (DigitalOcean c-16, sgp1). Run as root ON THE DROPLET
# from a copy of this directory plus the app/zkprove crate at /opt/zk/src/zkprove:
#   laptop: tar czf - --exclude target -C app zkprove | ssh root@<ip> 'mkdir -p /opt/zk/src && tar xzf - -C /opt/zk/src'
#           scp zkmobile/prover-worker/* root@<ip>:/opt/zk/worker/
#           gzip -9c ~/.enconomy/zk/optA/noir/phone/target/phone.json | ssh root@<ip> 'mkdir -p /opt/zk/art && gunzip > /opt/zk/art/oaN_s48.json'
#           scp ~/.enconomy/zk/pinned/vk/vk root@<ip>:/opt/zk/art/oaN_s48.vk
#           /etc/enconomy-prover/worker.env (0600): WORKER_SECRET=<hex>  HARDWARE_CONCURRENCY=16
#           /etc/cloudflared/{config.yml,<tunnel-id>.json} (cloudflared.yml template here)
#   droplet: bash /opt/zk/worker/setup.sh
# Builds zkprove (witness + bbapi prove) against the pinned bb static lib, fetches the 2^20 CRS, installs the
# worker + cloudflared as systemd services. Idempotent.
set -euo pipefail
BBV=v5.0.0-nightly.20260522
REL=https://github.com/AztecProtocol/barretenberg/releases/download/$BBV
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential clang pkg-config curl git time libc++-dev libc++abi-dev >/dev/null
[ -x ~/.cargo/bin/cargo ] || curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal -q
mkdir -p /opt/zk/bb /opt/zk/bin /opt/zk/art
cd /opt/zk/bb
[ -f libbb-external.a ] || { curl -sSLO $REL/barretenberg-static-amd64-linux.tar.gz; tar xzf barretenberg-static-amd64-linux.tar.gz; }
[ -x bb ] || { curl -sSLO $REL/barretenberg-amd64-linux.tar.gz; tar xzf barretenberg-amd64-linux.tar.gz; }
cd /opt/zk/src/zkprove
BB_LIB_DIR=/opt/zk/bb ~/.cargo/bin/cargo build --release --bin zkprove --features witness
install -m 755 target/release/zkprove /opt/zk/bin/zkprove
cd /opt/zk/art
[ -f bn254_g1_2p20.dat ] || curl -sS -r 0-67108863 -o bn254_g1_2p20.dat https://crs.aztec.network/g1.dat
sha256sum -c <<'SUMS'
5d0ff516149e0c6644ab16567b914c9d02bf41f872c1129af8436b41d4d82c62  bn254_g1_2p20.dat
5499f99eed7aecfd6615ab470cfed7a3345e28954385005d8080b810aaf04f3a  oaN_s48.json
769ac93112de4ec2f970d33233108d19124612b9b2ae54b8b531a23ecaa23f06  oaN_s48.vk
SUMS
chmod 644 /opt/zk/art/*
id zkw >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin zkw
install -m 644 /opt/zk/worker/zk-worker.service /etc/systemd/system/zk-worker.service
chmod 600 /etc/enconomy-prover/worker.env
if ! command -v cloudflared >/dev/null; then
  curl -sSLo /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i /tmp/cloudflared.deb
fi
[ -f /etc/cloudflared/config.yml ] && { cloudflared service install 2>/dev/null || true; }
systemctl daemon-reload
systemctl enable --now zk-worker
systemctl restart zk-worker
systemctl enable --now cloudflared 2>/dev/null || true
sleep 1; curl -sf http://127.0.0.1:8090/health && echo " worker up"
