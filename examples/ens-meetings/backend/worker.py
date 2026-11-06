"""One thread does everything onchain, in the backend process, so the shared key sends serially.

It sleeps until woken: at startup (a crash can leave pending rows) and on each claim or presence record. No poll.
A pass registers pending claims, then hands each undone presence record to the bridge.
"""
from __future__ import annotations

import logging
import threading

from backend.store import LABEL_RE, PARENT, Store

log = logging.getLogger("ens")


class Worker:
    def __init__(self, store: Store, chain, bridge):
        self.store, self.chain, self.bridge = store, chain, bridge
        self._wake = threading.Event()
        self._stop = False
        self._thread = None

    def start(self) -> None:
        self._stop = False
        self._wake.set()
        self._thread = threading.Thread(target=self._run, name="ens-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()   # before the pass, so a wake during it isn't lost
            if self._stop:
                return
            try:
                self.run_pass()
            except Exception:  # noqa: BLE001 - the thread must outlive one bad pass
                log.exception("worker pass failed")

    def run_pass(self) -> None:
        self.register_claims()
        self.bridge.once(stop=lambda: self._stop)

    def register_claims(self) -> None:
        for c in self.store.names_with_status("pending"):
            if self._stop:
                return
            label, dev = c["label"], c["device_id"]
            try:
                if not LABEL_RE.fullmatch(label):
                    self.store.set_claim(dev, label, "failed", error="bad label")
                    continue
                if self.chain.counts(label)[0]:  # already onchain: a crash after the tx, or registered by hand
                    self.store.set_claim(dev, label, "registered")
                    log.info("claim %s.%s already registered", label, PARENT)
                    continue
                tx = self.chain.register(label)
                self.chain.touch(label)
                self.store.set_claim(dev, label, "registered", tx=tx)
                log.info("claim %s.%s registered %s", label, PARENT, tx)
            except Exception as e:  # noqa: BLE001 - this row failed, the app can retry; others still go
                self.store.set_claim(dev, label, "failed", error=str(e)[:200])
                log.error("claim %s failed: %s", label, e)
