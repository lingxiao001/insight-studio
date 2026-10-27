# Security policy

Do not post API keys, passwords, session cookies, uploaded datasets,
database files, private server addresses or full operational logs in public
issues or pull requests.

For a vulnerability, use this repository's private vulnerability reporting
feature on GitHub when available. If it is unavailable, open a minimal issue
requesting a private channel without publishing exploit details or secrets.
Do not include live credentials in a proof of concept.

## Deployment boundaries

- Use HTTPS and a persistent random `SESSION_SECRET` in production.
- Generate a unique initial administrator password; never use an example
  value from documentation as a production password.
- Keep the data directory outside the web/static root. Restrict access to
  environment files, credential files and backups.
- Registration grants each account a lifetime USD 1 application allowance.
  It is not proof of a unique person; rate limiting is not complete abuse
  prevention. Choose a registration policy appropriate to your deployment.
- Administrators have no application-wide cumulative spending cap. Provider
  account limits, per-request limits and billing checks still apply.
- Only aggregated data is sent for optional model analysis. Aggregates,
  column names and goals can still contain sensitive information.
- Do not execute model-generated code. Review narrative claims against the
  computed evidence; model-risk checks are not a complete fact checker.

## Before contributing or publishing

Keep `.env*` (except `.env.example`), `.local`, data, backups, credentials,
build output and dependency directories out of Git. Avoid screenshots of
real accounts or browser address bars. Review all staged files and commit
metadata, not only the latest diff; deleting a secret from a later commit
does not remove it from history. Rotate any credential that was exposed.
