# Android application modules

The Android build now contains the first production Phase-1 foundation while preserving the already-proven Kotlin/JNI/Rust security boundary.

## Modules

- `:app` is the production Android application module. It provides the Material 3/Compose shell with top-level Vault/Settings navigation, verifies the native ABI/capability boundary on startup, invokes the existing bounded Rust `lock-all` lifecycle operation when the Activity is backgrounded, and uses Android SAF for scoped KDBX/key-file selection. A selected vault can now be unlocked with password-only, key-file-only, or password+key-file composite credentials and browsed through bounded ABI-v4 vault/group/entry metadata summaries. It still exposes no explicit secret retrieval, mutation, persistence, networking, telemetry or Autofill.
- `:native-bridge` is the single Android/Kotlin owner of `world.w3b.kdbxfortress.bridge.NativeBridge`. Both applications depend on this module, preventing the production and test callers from drifting onto different JNI class definitions.
- `:smoke-app` remains a CI-only runtime/lifecycle probe. It opens two deterministic fixture vaults, keeps only opaque handles in Kotlin, waits for an app-private `READY` marker, and reports `PASS` only after a real foreground → background transition causes Rust `lock-all` to invalidate both sessions.

All modules use the Phase-1 platform baseline (`minSdk 26`, `compileSdk 37`; application modules target SDK 37) and Android Gradle Plugin built-in Kotlin support.

## Native library wiring

CI cross-builds `kdbx-fortress-android-jni` and stages the generated `.so` under `:native-bridge`. The Android gate then:

1. assembles both the production and smoke APKs;
2. verifies mechanically that the production APK contains `lib/<abi>/libkdbx_fortress_android_jni.so`;
3. rejects the built production APK if it requests legacy/broad storage or media permissions;
4. cold-launches the real production Compose Activity on an emulator;
5. proves the real production Compose shell can hand off to Android DocumentsUI through `ACTION_OPEN_DOCUMENT`; and
6. launches the smoke application and exercises the same shared `NativeBridge` through Kotlin → JNI → Rust, including Vault → Root → Group → Entry metadata traversal before lifecycle locking.

The bridge is ABI v4 and exports exactly six approved native functions: capability probe, bounded open, per-handle lock, global lock-all, handle-validity check and the single bounded `nativeReadMetadata` channel. The read channel returns only versioned `KFM1` vault/group/entry summaries; password values, OTP material, notes/custom secret fields and attachment content remain unavailable.

The fixture password used by `:smoke-app` is deterministic test data, not a production credential. Temporary fixture password/KDBX byte arrays are cleared after use, while decrypted database ownership remains inside Rust.


## Production read-only browse path

The first real production vault session is deliberately narrow:

- Android streams the selected encrypted KDBX through a hard `64 MiB` ingress ceiling and an optional key file through a hard `1 MiB` ceiling. Unknown provider sizes are still bounded while streaming; temporary read buffers are cleared.
- Password material is collected through an Android `EditText` with view-state saving and Autofill disabled. Fortress copies characters directly to a short-lived UTF-8 byte array without creating a Kotlin password `String`; the editor is cleared on consumption/background/document changes and the byte array is cleared after the native open attempt. `null` means no password component, while a zero-length byte array preserves a deliberately empty password component.
- `VaultSessionController` is the only production owner of the opaque Rust vault handle. Kotlin keeps no decrypted `Database`/entry tree model; it holds only the current bounded `VaultSummary`, `GroupSummary`, direct child-group summaries and direct entry summaries. A group with more than 1,024 direct items fails closed until a paging/query API exists.
- Backgrounding increments a session epoch before Rust `lock-all`. In-flight unlock/browse work checks the epoch before publishing state; any handle created after an operation became stale is immediately locked rather than surfaced to Compose. Handles are never written to saved state, intents or bundles.
- Entries remain metadata-only. Protected title/username/URL values are withheld by the Rust boundary, and password/OTP values, notes/custom secret fields and attachment names/content remain unavailable.

`tools/check_android_vault_browse_policy.py` is part of Foundation CI and locks these source-level invariants against accidental regressions. The next Android read-only tranche is bounded Rust-backed search/filtering; it must not become an alternate secret-retrieval path.

## Scoped document access

Production file selection is provider-based rather than path-based:

- `ACTION_OPEN_DOCUMENT` is the active Phase-1 Open path. Android returns a `content://` URI, Fortress keeps only the URI plus a sanitized display name in Android state, and the app requests persistable read access only when the provider actually grants it.
- `ACTION_CREATE_DOCUMENT` is already wired with `.kdbx` naming and persistable read/write-grant handling, but its production button remains disabled until the verified Rust KDBX 4.1 writer can initialize a complete valid vault immediately. This avoids creating empty invalid `.kdbx` placeholders during the read-only phase.
- The manifest does not request legacy external-storage, all-files, media-library or document-management permissions; CI checks the permissions of the assembled APK so this boundary cannot silently regress.

SAF owns platform document I/O. Raw filesystem paths are not part of the vault-core API, and Rust remains Android/storage-provider independent.
