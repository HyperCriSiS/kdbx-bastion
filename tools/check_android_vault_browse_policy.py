#!/usr/bin/env python3
"""Fast source-level policy gate for the production Android vault-browse path."""

from __future__ import annotations

import argparse
from pathlib import Path

APP_ROOT = Path("android/app/src/main/kotlin/world/w3b/kdbxfortress")
ACCESS_PATH = APP_ROOT / "storage/VaultDocumentAccess.kt"
ACTIVITY_PATH = APP_ROOT / "MainActivity.kt"
UI_PATH = APP_ROOT / "ui/KdbxFortressApp.kt"
SESSION_PATH = APP_ROOT / "vault/VaultSessionController.kt"
BRIDGE_PATH = Path(
    "android/native-bridge/src/main/kotlin/world/w3b/kdbxfortress/bridge/NativeBridge.kt"
)

FORBIDDEN_APP_FRAGMENTS = (
    ".readBytes(",
    "readBytes()",
    "password.toByteArray(",
    "password.encodeToByteArray(",
    "text.toString().toByteArray(",
    "String(password",
    "String(keyFile",
    "keepass::",
    "keepass.",
)
FORBIDDEN_UI_FRAGMENTS = (
    "rememberSaveable",
    'mutableStateOf("")',
    "var password by",
    "val password by",
)
REQUIRED_ACCESS_FRAGMENTS = (
    "MAX_ANDROID_VAULT_BYTES: Long = 64L * 1024 * 1024",
    "MAX_ANDROID_KEYFILE_BYTES: Long = 1024L * 1024",
    "readBoundedBytes(uri, MAX_ANDROID_VAULT_BYTES)",
    "readBoundedBytes(uri, MAX_ANDROID_KEYFILE_BYTES)",
    "if (total > maximumBytes)",
    "buf.fill(0)",
    "buffer.fill(0)",
)
REQUIRED_UI_FRAGMENTS = (
    "AndroidView(",
    "isSaveEnabled = false",
    "consumeUtf8Bytes()",
    "chars.fill('\\u0000')",
    "encoded.array().fill(0)",
    "credentialClearEpoch",
)
REQUIRED_ACTIVITY_FRAGMENTS = (
    "credentialClearEpoch += 1L",
    "override fun onStop()",
    "sessionController.onBackgrounded()",
)
REQUIRED_SESSION_FRAGMENTS = (
    "private val operationEpoch = AtomicLong(0L)",
    "private var foreground = true",
    "if (!isCurrent(token))",
    "safeLock(newHandle)",
    "password.fill(0)",
    "keyFileBytes?.fill(0)",
    "vaultBytes?.fill(0)",
    "NativeBridge.lockAllVaults()",
    "MAX_BROWSER_PAGE_ITEMS = 1024",
)
REQUIRED_BRIDGE_FRAGMENTS = (
    "EXPECTED_ADAPTER_ABI = 4L",
    "MAX_PASSWORD_BYTES = 4 * 1024",
    "MAX_KEYFILE_BYTES = 1024 * 1024",
    "fun openVault(",
    "fun readVaultSummary(",
    "fun readGroupSummary(",
    "fun readEntrySummary(",
)


class PolicyError(RuntimeError):
    """Raised when the production browse policy is violated."""


def _read(root: Path, relative: Path) -> str:
    path = root / relative
    if not path.is_file():
        raise PolicyError(f"missing {relative.as_posix()}")
    return path.read_text(encoding="utf-8")


def _require(source: str, fragments: tuple[str, ...], label: str) -> None:
    for fragment in fragments:
        if fragment not in source:
            raise PolicyError(f"{label} must retain: {fragment}")


def _forbid(source: str, fragments: tuple[str, ...], label: str) -> None:
    for fragment in fragments:
        if fragment in source:
            raise PolicyError(f"forbidden {label} fragment: {fragment}")


def check_sources(
    *,
    access: str,
    activity: str,
    ui: str,
    session: str,
    bridge: str,
) -> None:
    app_source = "\n".join((access, activity, ui, session))
    _forbid(app_source, FORBIDDEN_APP_FRAGMENTS, "production vault-browse")
    _forbid(ui, FORBIDDEN_UI_FRAGMENTS, "master-password UI")

    _require(access, REQUIRED_ACCESS_FRAGMENTS, "bounded SAF ingress")
    _require(ui, REQUIRED_UI_FRAGMENTS, "master-password UI")
    _require(activity, REQUIRED_ACTIVITY_FRAGMENTS, "activity lifecycle")
    _require(session, REQUIRED_SESSION_FRAGMENTS, "vault session controller")
    _require(bridge, REQUIRED_BRIDGE_FRAGMENTS, "native bridge wrapper")

    on_stop = activity.index("override fun onStop()")
    clear_at = activity.index("credentialClearEpoch += 1L", on_stop)
    lock_at = activity.index("sessionController.onBackgrounded()", on_stop)
    if clear_at > lock_at:
        raise PolicyError("onStop must clear transient credential UI before background lock")

    if session.count("NativeBridge.openVault(") != 1:
        raise PolicyError("production session controller must have exactly one native open call site")


def check(root: Path) -> None:
    check_sources(
        access=_read(root, ACCESS_PATH),
        activity=_read(root, ACTIVITY_PATH),
        ui=_read(root, UI_PATH),
        session=_read(root, SESSION_PATH),
        bridge=_read(root, BRIDGE_PATH),
    )


def expect_failure(sources: dict[str, str], expected_fragment: str) -> None:
    try:
        check_sources(**sources)
    except PolicyError as error:
        if expected_fragment not in str(error):
            raise AssertionError(
                f"expected failure containing {expected_fragment!r}, got: {error}"
            ) from error
    else:
        raise AssertionError(f"expected policy failure containing {expected_fragment!r}")


def self_test(root: Path) -> None:
    sources = {
        "access": _read(root, ACCESS_PATH),
        "activity": _read(root, ACTIVITY_PATH),
        "ui": _read(root, UI_PATH),
        "session": _read(root, SESSION_PATH),
        "bridge": _read(root, BRIDGE_PATH),
    }
    check_sources(**sources)

    mutated = dict(sources)
    mutated["access"] += "\nfun forbidden() = stream.readBytes()\n"
    expect_failure(mutated, "readBytes()")

    mutated = dict(sources)
    mutated["ui"] = mutated["ui"].replace(
        "isSaveEnabled = false", "isSaveEnabled = true", 1
    )
    expect_failure(mutated, "master-password UI must retain: isSaveEnabled = false")

    mutated = dict(sources)
    mutated["session"] = mutated["session"].replace("password.fill(0)", "// removed", 1)
    expect_failure(mutated, "vault session controller must retain: password.fill(0)")

    mutated = dict(sources)
    mutated["activity"] = mutated["activity"].replace(
        "credentialClearEpoch += 1L\n        sessionController.onBackgrounded()",
        "sessionController.onBackgrounded()\n        credentialClearEpoch += 1L",
        1,
    )
    expect_failure(mutated, "onStop must clear transient credential UI before background lock")

    print("Android vault-browse policy self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    try:
        if args.self_test:
            self_test(root)
        else:
            check(root)
            print("Android vault-browse policy OK")
    except (PolicyError, AssertionError, ValueError) as error:
        raise SystemExit(f"Android vault-browse policy FAILED: {error}") from error


if __name__ == "__main__":
    main()
