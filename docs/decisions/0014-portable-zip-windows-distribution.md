# ADR 0014: Portable ZIP Windows Distribution

- Status: Accepted
- Date: 2026-08-19
- Supersedes: ADR 0013's per-user Setup distribution layer

## Context

The self-contained Windows Runtime and native Manager are already movable as
one folder. For the foreseeable release cycle, the project owner wants to build
the official CPU package locally and upload it manually to GitHub Releases.
Maintaining an installer adds upgrade, uninstall, signing, and user-data
semantics that are not needed while the product is distributed as a portable
tool.

## Decision

The only official ordinary-user Windows artifact is:

```text
Nota-ASR-Runtime-<version>-Windows-x64-CPU.zip
```

It contains one versioned top-level folder with the self-contained Python
Runtime, native Manager, configuration template, launchers, legal inventories,
and empty model/data/log directories. It contains no model weights. The owner
runs `scripts/build-windows-release.ps1 -UnsignedRelease` from a clean worktree;
the script performs offline diagnosis, creates the ZIP, and emits its SHA-256
and release manifest. The manifest records that the Manager is unsigned. The
script does not upload the artifact and is not run by CI.

Portable and installed configuration modes are distinguished by an explicit
program-directory marker:

- without `.nota-installed`, Manager uses adjacent `config/server.toml`;
- with `.nota-installed`, a future installed build uses
  `%APPDATA%\NotaASR\server.toml`;
- an explicit `--config` argument overrides either default.

A future installer must create the marker, but no installer implementation is
part of the current release path or official product.

```mermaid
flowchart LR
    S["Clean source worktree"] --> R["Build self-contained CPU Runtime"]
    R --> M["Build Rust Manager"]
    M --> V["Notices, SBOMs, offline doctor"]
    V --> Z["Versioned portable ZIP"]
    Z --> H["SHA-256 + release manifest"]
    H --> U["Owner manually uploads to GitHub Release"]
```

## Consequences

- Ordinary users extract one folder; no installation, administrator access,
  system Python, Windows service, firewall rule, or `PATH` change is required.
- A new version should be extracted to a fresh folder. Absolute external model
  and data roots can be reused directly; relative roots move with their
  portable folder and must be migrated or copied deliberately.
- The ZIP's published SHA-256 verifies that downloaded bytes match the release
  asset; it is not a publisher identity signature. Public release notes disclose
  that the Manager is unsigned and Windows may show unknown-publisher or
  SmartScreen warnings.
- The Git tag identifies the released source commit. GitHub Release assets are
  uploaded together with the checksum and manifest before publication; release
  immutability should be enabled when the hosting account supports it.
- Installer upgrade and uninstall behavior are deferred. If an installed
  edition returns, its marker and `%APPDATA%` behavior must be tested separately
  without changing portable configuration ownership.
