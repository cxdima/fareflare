# Security policy

## Report a vulnerability

Use [GitHub's private vulnerability report form](https://github.com/cxdima/fareflare/security/advisories/new)
for authentication failures, cross-account data access, exposed credentials,
webhook SSRF, or other security issues. Do not post exploit details or credentials
in a public issue.

Include the affected commit or deployment, reproduction steps using accounts and
systems you control, expected impact, and a minimal proof of concept. Redact API
keys, reset links, backup codes, cookies, bot tokens, and travel details.
The maintainer will coordinate investigation and disclosure through that report.
There is no guaranteed response time or paid bug-bounty program.

## Supported code

Security fixes target the current default branch. Fareflare is under active
development; older commits and custom deployments do not receive a separate
maintenance stream. Self-hosted operators are responsible for applying updates
and reviewing configuration changes.

## Deployment practices

- Keep `.env`, `.fareflare/`, Terraform state, backend settings, and variable files out
  of Git. Use Secrets Manager for deployed Telegram credentials.
- Keep account endpoints on HTTPS. Preserve secure cookies, CSRF checks, CSP,
  request limits, tenant authorization, passkey and two-step sign-in, and password-reset links.
- Verify webhook signatures over raw request bytes and deduplicate event IDs.
- Use immutable image digests and keep a private rollback record. Restrict AWS
  permissions and explicitly select the intended AWS account and state backend.
- Rotate exposed credentials promptly. Removing a value from the latest commit
  does not remove it from Git history.

See the [operations runbook](docs/OPERATIONS.md) for deployment and recovery.
