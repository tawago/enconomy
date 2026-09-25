// One lock can cover overlapping recordings. Each recording keeps its own diagnostics.
function createScreenAwakeController(onStatus) {
    const sessions = new Set();
    const supported = typeof navigator.wakeLock?.request === 'function';
    let sentinel = null;
    let pending = false;
    let retryWhenSettled = false;
    let state = 'idle';

    function report(next, message, tone = '') {
        state = next;
        const event = {
            time_ms: Date.now(),
            state,
            visibility: document.visibilityState,
        };
        for (const session of sessions) session.events.push({ ...event });
        onStatus(message, tone);
    }

    function release() {
        const old = sentinel;
        sentinel = null;
        if (old && !old.released) {
            // A release event from this old lock must not clear a newer lock.
            old.release().catch(() => {});
        }
    }

    async function acquire() {
        if (!sessions.size || (sentinel && !sentinel.released)) return;
        if (pending) {
            // A new session or a hide/show cycle can arrive before the old request settles.
            retryWhenSettled = true;
            return;
        }
        if (document.visibilityState !== 'visible') {
            report('hidden', 'Page hidden. Return to this page.', 'warning');
            return;
        }
        if (!supported) {
            report('unavailable', 'Unavailable. Keep the screen awake manually.', 'warning');
            return;
        }
        pending = true;
        report('requesting', 'Requesting screen wake lock…');
        try {
            const lock = await navigator.wakeLock.request('screen');
            if (!sessions.size || document.visibilityState !== 'visible') {
                await lock.release();
                return;
            }
            sentinel = lock;
            lock.addEventListener('release', () => {
                if (sentinel !== lock) return;
                sentinel = null;
                if (sessions.size) {
                    report('released', 'Released. Keep the screen awake manually.', 'warning');
                }
            });
            report('active', 'Keeping screen awake', 'success');
        } catch (error) {
            if (sessions.size) {
                report('unavailable', 'Unavailable. Keep the screen awake manually.', 'warning');
            }
        } finally {
            pending = false;
            const retry = retryWhenSettled;
            retryWhenSettled = false;
            if (retry && sessions.size && document.visibilityState === 'visible' && !sentinel) {
                void acquire();
            }
        }
    }

    document.addEventListener('visibilitychange', () => {
        if (!sessions.size) return;
        if (document.visibilityState === 'visible') {
            // Browsers release screen locks when the document becomes hidden.
            void acquire();
        } else {
            for (const session of sessions) session.page_hidden = true;
            release();
            report('hidden', 'Page hidden. Return to this page.', 'warning');
        }
    });

    window.addEventListener('pagehide', () => {
        for (const session of sessions) session.page_hidden = true;
        report('pagehide', 'Screen wake lock off');
        sessions.clear();
        release();
    });

    return {
        start() {
            const session = {
                supported,
                page_hidden: document.visibilityState !== 'visible',
                events: [{ time_ms: Date.now(), state, visibility: document.visibilityState }],
            };
            sessions.add(session);
            // Do not delay audio scheduling while the browser handles this request.
            void acquire();
            return {
                snapshot() {
                    return {
                        supported: session.supported,
                        page_hidden: session.page_hidden,
                        events: session.events.map((event) => ({ ...event })),
                    };
                },
                finish() {
                    if (!sessions.delete(session) || sessions.size) return;
                    release();
                    report('idle', 'Off until the next recording');
                },
            };
        },
    };
}
