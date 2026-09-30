# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately.

**Do not open a public issue.**

Contact: matheus.boni.vicari@gmail.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Response Timeline

- Initial response: Within 48 hours
- Status update: Within 7 days
- Fix timeline: Depends on severity

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.x.x   | :white_check_mark: |

## Security Best Practices

Plumbline parses untrusted repository content by design (READMEs, wikis,
and source files from any repository it's pointed at) and invites AI
agents to propose changes. Its own security posture mirrors
[Ontolith's](https://github.com/mattbv/ontolith/blob/main/SECURITY.md),
the substrate it's built on:

- **No direct-write path for any AI principal, anywhere** (PRD §9.2). Every
  AI-authored proposal — a doc-fix, a flagged disagreement — goes through
  Ontolith's own governed `propose` path and always requires human review,
  with no trust-level escape hatch.
- **Untrusted parsing runs sandboxed.** Importers are Ontolith
  `PluginRegistry` plugins with `network=False, filesystem=False`,
  process-isolated and seccomp-enforced on Linux — the only supported
  production platform for this reason. On macOS/Windows, Plumbline logs the
  degraded enforcement loudly rather than claiming a guarantee it can't
  make (see Ontolith's own known-issues around plugin sandbox enforcement,
  KI-110/KI-111, which Plumbline inherits and does not claim away).
- **No code execution.** All analysis is static (PRD §4.2 non-goal).
- **Model egress is opt-in**, per path, and every model call is recorded in
  provenance (`model` field on the resulting assertion).
- **Rotate and revoke tokens proactively.** Both Plumbline's own MCP façade
  and the Ontolith knowledge base it wraps authenticate via per-principal
  API keys (Ontolith ADR-0014) — there is no OIDC/workload-identity support
  yet in either project.
