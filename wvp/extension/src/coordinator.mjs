import * as core from "./core.mjs";
self.onmessage = async ({ data: { id, fn, arg } }) => {
  try { self.postMessage({ id, ok: await core[fn](arg) }); }
  catch (e) { self.postMessage({ id, err: String(e?.stack ?? e), code: e?.code }); }
};
