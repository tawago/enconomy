# World App crashes on iOS 16.7 (iPhone X) after approving a World ID 4.0 request

World ID app 1.0.601 aborts on an iPhone X running iOS 16.7.16. The App Store lists this version as "Requires iOS 16.0 or later", so the device is in the supported range.

The first crash came right after the user tapped approve on a Proof of Human request. The next nine came 6–8 s after World App launched. There are 10 crash reports between 22:49 and 23:09 JST on 2026-09-26, and all have the same signature.

Screen recording: [`worldid-app-ios16-crash.mp4`](worldid-app-ios16-crash.mp4) (23:09, matches the last report).

## Environment

| | |
| --- | --- |
| Device | iPhone X (`iPhone10,3`) |
| OS | iPhone OS 16.7.16 (20H392) |
| App | World ID — Proof of Human, `org.world.id` |
| Version | 1.0.601, build 33419 (App Store release 2026-09-21), App Store id 6760839426 |
| Binary slice UUID | `c2d18406-0e5d-32b1-96ac-76d61121aca5` |
| App Store minimum | iOS 16.0 |

## How the calling app invokes World App

- The request is built server-side with `@worldcoin/idkit-core` 4.2.4:
  - `IDKit.request({ app_id, action, rp_context, allow_legacy_proofs: false, environment: "production", return_to })`, then `.preset(proofOfHuman({ signal }))`.
  - One action per session (`pop:<session_id>`). The signal is a 0x-hex string of 33 bytes.
- The phone gets the resulting `connectorURI` (`https://world.org/verify?...`). It opens the URI on the same device with `UIApplication.open(_:options:completionHandler:)`.
- `return_to` is a custom scheme (`enconomy://worldid`). The calling app polls the bridge status through the server; it does not depend on the return link.
- Nothing else is passed to World App.

## Steps

1. The calling app opens the `world.org/verify` connector URI. World App comes forward and shows the Proof of Human request.
2. Tap approve.
3. World App aborts.

The proof still reaches the bridge before the abort: the server's Portal `/api/v4/verify` call succeeded in the same second as the first crash. Later launches of World App on the same phone kept aborting 6–8 s after launch.

## Crash signature (identical in all 10 reports)

```
Exception Type:  EXC_CRASH (SIGABRT)
Termination:     SIGNAL 6, Abort trap: 6
ASI:             libsystem_c.dylib: abort() called
Process role:    Foreground

Triggered thread:
0  libsystem_kernel.dylib     __pthread_kill
1  libsystem_pthread.dylib    pthread_kill
2  libsystem_c.dylib          __abort
3  libsystem_c.dylib          abort
4  libswift_Concurrency.dylib swift_task_reportIllegalTaskLocalBindingWithinWithTaskGroupImpl(...)
5  libswift_Concurrency.dylib swift_task_reportIllegalTaskLocalBindingWithinWithTaskGroup
6  libswift_Concurrency.dylib specialized String.withCString<A>(_:)
7  libswift_Concurrency.dylib TaskLocal.withValue<A>(_:operation:file:line:)
8  WorldID                    +6559064
9  WorldID                    +31856632
10 WorldID                    +31852173
11 WorldID                    +10827989
12 WorldID                    +39197413
13 WorldID                    +39149721
14 WorldID                    +39147333
15 WorldID                    +22089
```

## Reports

| Time (JST, 2026-09-26) | Seconds from launch to crash |
| --- | --- |
| 22:49:19 | 23037 (long-running, crash right after approve) |
| 23:02:29 | 7 |
| 23:03:01 | 6 |
| 23:03:07 | 7 |
| 23:03:50 | 8 |
| 23:05:55 | 7 |
| 23:06:49 | 8 |
| 23:07:37 | 6 |
| 23:07:45 | 6 |
| 23:09:18 | 6 |

## Likely cause

The Swift runtime is reporting a `TaskLocal.withValue` binding made directly inside a `withTaskGroup` / `withThrowingTaskGroup` body, which the concurrency runtime treats as illegal and aborts on. The Swift runtime that ships with iOS 16 enforces this. We have not confirmed whether newer iOS runtimes relax the check, but the app works for other users on newer devices, which points that way. A likely fix is to move the `withValue` call out of the group body, or into a child task, such as inside `group.addTask { ... }`.

Since this version was released five days before these crashes, it is probably a regression in 1.0.601. We did not test earlier versions.

## Impact

- Any integration that sends users to World App on an iOS 16 device loses the user at the approve step: World App dies instead of returning.
- Relaunching World App keeps crashing.
- The raw `.ips` reports are available on request. They are not attached here because they contain device identifiers.
