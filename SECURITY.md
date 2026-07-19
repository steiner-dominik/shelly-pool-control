# Security Policy

## Reporting a vulnerability

Please report security issues privately via
[GitHub security advisories](https://github.com/steiner-dominik/shelly-pool-control/security/advisories/new)
or by email to `contact@dominik.st`. Do **not** open a public issue for
security-relevant bugs.

You can expect an initial response within a few days. Fixes are released as a
new CalVer version as soon as they are verified.

## Scope notes

This application controls a physical pump. Security and safety design notes:

- The web panel is designed to run behind a TLS-terminating reverse proxy and
  ships with mandatory local authentication (argon2id, server-side sessions,
  CSRF protection, login rate limiting).
- The Shelly device is the sole control authority. The server only writes
  validated parameters and sends override *requests* which the on-device
  script re-validates against its own interlocks. A compromised or
  malfunctioning server cannot bypass the on-device safety limits, with the
  single documented exception of the explicit emergency-stop path (which only
  turns the pump **off**).
- No secrets are ever committed to this repository. Configuration secrets are
  supplied via environment variables or the Home Assistant options schema.

## Supported versions

Only the latest released version is supported. Releases are cheap
(CalVer, fully automated) — please update before reporting.
