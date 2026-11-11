# Fareflare domain and public access

The public application is https://fareflare.dev. Registration needs an email address and a
password, and is open to anyone. The address is confirmed by email and is where a
password-reset link goes; passkeys and two-step sign-in are available in account
settings. Billing
remains disabled. Each account may track 20 flights. Collection is shared and has
an independent deployment capacity ceiling; reaching it rejects additional targets
rather than starting unbounded browser work. Polling remains periodic.

## Naming and migration

The repository, local project folder and Python package are named `fareflare`.
Application settings use `FAREFLARE_` environment keys. Deploy API and worker
images together with the corresponding Terraform environment changes. Stored
account, monitor and credential formats are preserved. The original CSRF
key-derivation label is intentionally stable so active sessions remain valid.

Existing physical AWS resource IDs and Terraform state coordinates are preserved
to avoid replacing the database, repositories or functions. New installations use
`fareflare-` resource names. The contributor instructions in `AGENTS.md` were
preserved as requested. Historical verification documents describe earlier releases.

## HTTPS and DNS

Terraform manages a Regional API Gateway custom domain, a DNS-validated ACM
certificate and Route 53 alias. Keep the ACM validation CNAME for automatic renewal.
`domain_name`, `hosted_zone_id` and `monitor_limit` are explicit deployment inputs.
The apex uses TLS 1.2 or newer and the application sends HSTS. No wildcard
certificate or unrelated hosted-zone records are required.

The configured public origin drives canonical metadata, sitemap, OAuth issuer,
MCP discovery and Telegram links. Browser pages at the former AWS endpoint redirect
to the domain. Existing API and Telegram ingress paths remain reachable there.
Browser cookies belong to their origin: users must sign in again on the new domain.
MCP clients should reconnect using https://fareflare.dev/mcp and repeat OAuth consent.

## Abuse protection

- Gateway limits: default 10 requests/second, burst 20; authentication 1/second,
  burst 3; signup 0.2/second, burst 2. AWS throttles are best-effort traffic targets.
- Durable atomic application counters: eight authentication attempts/minute/IP,
  three signups/minute/IP, username login/recovery limits, and 120 requests/minute
  for authenticated account/API access. Forwarding headers cannot choose the IP key.
- Sessions use Secure, HttpOnly, SameSite cookies, CSRF tokens and strict origin
  checks. Trusted hosts are explicit. Request bodies are limited to 16 KiB.
- Passwords use scrypt; credentials are hashed, revocable and account-scoped.
  CSP, frame blocking, no-store private responses and escaped user content remain enforced.
- Collection quotas and reserved Lambda concurrency bound expensive work.

Fixed-minute windows allow boundary bursts and per-IP limits affect shared networks.
These controls do not establish sustained collection reliability or complete bot/DDoS
protection. API Gateway HTTP APIs do not provide direct WAF association. See
[development status](DEVELOPMENT_STATUS.md) for remaining operational work.

## Release verification — November 6, 2026

Implementation `e4884da688a53d1532c3c523dc13647f6a4b36ae` passed 949 backend
checks (92.83% coverage), 78 frontend checks, build/types/lint/formatting, a
100-file secret scan and 60 isolated container checks with matching source hashes.
GitHub CI passed. The initially flagged secret was an existing deterministic
webhook test vector; it is now constructed explicitly from `bytes(range(32))`.

Terraform applied three additions and six updates with zero destruction. Readback
confirmed the certificate is ISSUED, the domain AVAILABLE, both functions Active
with successful updates, and their environments match the reviewed migration.
The original tracker's image, environment and modification time were preserved.

All 45 live browser/account checks passed, including 15 accessibility scans, normal
signup without an invitation, secure sessions, API-key lifecycle, 20-tool MCP
discovery, preference persistence, login and account deletion. The temporary
account was deleted; tests created no monitors or external notifications. No
runtime, CSP, asset or server errors were recorded.

Public resolvers and Route 53 delegation resolve the new domain correctly. This
Mac retained an earlier negative DNS result, so browser verification used a local
CONNECT relay to a published DNS address. HTTPS certificate/hostname validation
remained enabled end to end; no certificate checks were bypassed. Other cached
resolvers may need time to refresh.

Immutable images:

- API: `sha256:c315b6b4d9588244d82b7e372ef89bb7aac4f2081498c075d4e53e25dd691e0a`
- Worker: `sha256:903ddfcadfbe7bd2fbafbcba34a07bda4f56aa048b312d950a62651052d233fc`
