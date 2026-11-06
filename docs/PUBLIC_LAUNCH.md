# Fareflare domain and public access

The public application is https://fareflare.dev. Registration needs a username
and password; keep the recovery code because recovery does not use email. Billing
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
