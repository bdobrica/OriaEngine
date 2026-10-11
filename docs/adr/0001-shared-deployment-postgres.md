# ADR 0001: Shared deployment PostgreSQL server

Status: Accepted — 2026-10-11

## Context

The operator requested separate standalone and combined published-image Compose
entry points, with one PostgreSQL server for the combined OriaEngine/SecondContext
stack. Component storage ownership and the versioned HTTP boundary remain in force.

## Decision

The combined stack shares one PostgreSQL server, with separate `oria` and
`secondcontext` databases owned by distinct, restricted login roles. Neither role
is a superuser, can create databases/roles, bypass row security, or connect to the
other database. Application and migration containers receive only their owner's
database credentials. The bootstrap administrator credential belongs only to the
PostgreSQL container; it is not an application credential.

Fresh-volume initialization provisions databases and roles, without copying either
component's schema. Each published application image runs its own migrations.
Oria accesses SecondContext exclusively through its versioned authenticated HTTP
contract. Qdrant remains SecondContext-owned and isolated from Oria networking.

## Consequences

Both databases share server availability, resource limits and a physical volume.
Logical backups/restores remain owner-specific, and existing separate-server data
requires an explicit operator-managed migration. The new shared volume does not
reuse or overwrite the old volumes. Bootstrap runs only on an empty volume;
password changes and recovery on populated storage require administrator action.
Standalone deployment continues to support an externally managed SecondContext.
