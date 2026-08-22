# ADR 0004: Production Android vault-browse boundary

- Status: Accepted
- Date: 2026-08-22

## Context

ABI v4 already provides a bounded lifecycle API plus one metadata-only `nativeReadMetadata` channel. Phase 1 now needs a real Android path from a user-selected SAF document to visible groups and entries without creating a second decrypted vault model in Kotlin or widening metadata into secret retrieval.

The Android layer also has lifecycle races that do not exist in host tests: a slow provider read/KDF can finish after backgrounding, Activity state can be recreated, and composite credentials must distinguish an absent password component from a deliberately empty password.

## Decision

1. `VaultSessionController` is the only production Android owner of the opaque live Rust handle. The handle is process-memory state only and is never persisted in saved state, intents, bundles or URIs.
2. Android reads selected encrypted inputs through bounded streaming before JNI: `64 MiB` maximum KDBX input and `1 MiB` maximum key-file input. Provider-reported sizes are advisory; the streaming loop enforces the ceiling again.
3. Password input stays byte-oriented. Android view-state persistence and Autofill are disabled for the master-password editor. `null` represents an absent password component; `ByteArray(0)` represents a deliberately empty password component. Temporary password, key-file and encrypted-vault byte arrays are cleared after the open attempt.
4. Kotlin does not own or reconstruct a decrypted database tree. It keeps only the current `VaultSummary`, current `GroupSummary`, the direct child-group summaries and direct entry summaries obtained through ABI v4.
5. A production group is limited to 1,024 direct child groups plus entries until a dedicated paging/query API exists. Exceeding the UI ceiling fails closed instead of materializing an arbitrarily large Kotlin result set.
6. Each asynchronous unlock/browse operation carries a monotonically increasing lifecycle epoch. Backgrounding/explicit lock invalidates the epoch and calls Rust `lock-all`; stale work cannot publish state, and a handle produced after staleness is immediately locked.
7. The browse tranche remains metadata-only. Protected title/username/URL values remain withheld by the Rust boundary. Password/OTP values, notes/custom secret fields and attachment names/content are not added.
8. Foundation CI includes a source-policy self-test for bounded SAF ingress, byte-oriented credential handling, transient-buffer clearing, the single production `openVault` callsite, lifecycle epoch/lock-all behavior and the 1,024-item browser ceiling. Android CI additionally builds the production APK, checks JNI packaging/permissions and proves the Compose → DocumentsUI SAF handoff on an emulator.

## Consequences

- The production app can now open and browse supported KDBX vaults while Rust remains the sole owner of the decrypted database model.
- Large groups above the current direct-item ceiling are intentionally not browsable until paging/query support is designed. This is preferable to an unbounded Kotlin materialization path.
- Search/filtering must be implemented as a bounded Rust-backed query over the live handle. It may return metadata identities/summaries needed for the visible result set, but it must not introduce secret values.
- Explicit secret reveal/copy remains a separate audited Phase-1 tranche with its own API, memory, clipboard and lifecycle policy.
