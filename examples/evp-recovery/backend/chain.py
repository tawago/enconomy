"""Chain helpers on cast and plain JSON-RPC. Paths, the deploy record and L's key. Happy path only."""
import json
import os
import pathlib
import subprocess
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
RUN = HERE / ".run"
DEPLOY = RUN / "deploy.json"
ENV_FILE = HERE / ".env"
RPC = os.environ.get("EVP_RPC", "https://altmempool.forshtat.com")
SIDECAR = os.environ.get("EVP_SIDECAR", "http://localhost:14337/rpc/")
CORE = os.environ.get("EVP_CORE", "http://127.0.0.1:8001")
GAS_PRICE = "2000000"
EMAIL = "alice@tawago.test"
ORIGIN = "https://recover.tawago.test"


def l_key() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("EVP_L_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("no EVP_L_KEY in .env, run scripts/setup.py")


def run(*a, key=None) -> str:
    p = subprocess.run(a, capture_output=True, text=True)
    if p.returncode:
        msg = p.stderr.replace(key, "<key>") if key else p.stderr
        raise RuntimeError(f"{a[0]} {a[1]}: {msg[:1500]}")
    return p.stdout.strip()


def cast(*a, key=None) -> str:
    return run("cast", *a, key=key)


def call(to, sig, *args) -> str:
    return cast("call", to, sig, *[str(x) for x in args], "--rpc-url", RPC).split()[0]


def send(key, gas, *a) -> dict:
    r = json.loads(cast("send", "--legacy", "--gas-price", GAS_PRICE, "--gas-limit", str(gas), "--json",
                        "--rpc-url", RPC, "--private-key", key, *a, key=key))
    if r["status"] != "0x1":
        raise RuntimeError(f"tx failed: {r['transactionHash']}")
    return r


def rpc(method, *params):
    req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "curl/8"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def get_json(url):
    return json.load(urllib.request.urlopen(url, timeout=30))
