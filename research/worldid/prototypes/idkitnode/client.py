import json, os, sys, urllib.request, subprocess
env = dict(l.strip().split("=",1) for l in open(os.path.expanduser("~/dev/worldid-spike/.env")) if "=" in l)
sys.path.insert(0, os.path.expanduser("~/dev/worldid-spike/backend"))
os.environ.update({k:v for k,v in env.items()})
from app.signing import sign_request
action = "pop:sidecar-py-test"
s = sign_request(env["WORLD_SIGNING_KEY"], action=action, ttl=300)
payload = {"app_id": env["WORLD_APP_ID"], "action": action, "signal": "0x"+"22"*32+"42", "return_to": "enconomy://worldid",
  "rp_context": {"rp_id": env["WORLD_RP_ID"], "nonce": s["nonce"], "created_at": s["created_at"], "expires_at": s["expires_at"], "signature": s["sig"]}}
r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8787/requests", json.dumps(payload).encode(), {"content-type":"application/json"}))
o = json.load(r); import re; print(re.sub(r"k=[^&]*", "k=<redacted>", json.dumps(o)))
print(urllib.request.urlopen(f"http://127.0.0.1:8787/requests/{o['request_id']}").read().decode())
