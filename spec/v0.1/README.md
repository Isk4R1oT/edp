# EDP Specification — v0.1 (`edp/2026-05-24`)

This directory contains the versioned artifacts for EDP specification version `edp/2026-05-24`.

## Contents

- `schema.json` — JSON Schema for the decision record (Decision object)
- See the top-level `../../SPEC.md` for the prose specification

## Conformance

An implementation conforms to `edp/2026-05-24` if:

1. It accepts and produces decision records that validate against `schema.json`
2. It exposes at least the four required tools described in `SPEC.md` §5 (`show`, `check`, `record`, `supersede`)
3. It produces active blocks matching the format in `SPEC.md` §4
4. It honours the append-only invariant of the storage contract in `SPEC.md` §7

Implementations MUST declare the specification version(s) they conform to in their documentation.

## Version policy

EDP uses **date-stamped versions**, not semver, following the convention established by MCP. A new version date is published when any breaking change occurs to the protocol. Backward-compatible additions live under the same date until the next breaking change.
