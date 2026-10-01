# email-manager — project rules

My autonomous Gmail triage tool: sorts, labels, archives, summarizes my mail
without me supervising it. Full decision writeup lives at
`~/Documents/email-manager-analysis.md` — read that before relitigating any
architecture choice.

## Voice
First person ("I", "my"), like my other repos.

## Conventions
- **Python 3.12, deliberately.** Not my system 3.14. The ML half of this project
  (torch / sentence-transformers) is better supported on 3.12, and uv manages it.
- uv project, no global packages. Current deps: `google-api-python-client`,
  `google-auth-oauthlib`, `google-auth-httplib2`.
- `src/` layout, package name `email_manager`.
- Ruff for both lint and format (my one-tool-per-job Python rule).
- Secrets never committed — `credentials.json` and `token.json` are gitignored.

## How I want to be taught here (IMPORTANT)
This is a learning project. Do NOT write code for me and do NOT scaffold files
unasked. Teach the concept first, in plain-English "monkey terms" bites, one
topic per message. Give me the algorithm in words and blanks to fill; I type
everything and drive. I get frustrated by over-delivery — pasting a full
solution or creating files I didn't ask for is the failure mode. Toolchain
setup is fine; the rest is mine.

**Vocabulary:** use normal, spelled-out terminology. Relative-import shorthand
(`from .auth import ...`) is opaque to me — explain a leading dot as "the file in
this same folder", and write imports out in full (`from email_manager.auth import
get_credentials`) when showing examples.

## Current phase (as of 2026-10-01)
- Repo on `main`, Python 3.12, deps installed, `credentials.json` down, gitignored. ✓
- `src/email_manager/auth.py` is **done and working** — full OAuth desktop-app flow,
  three-state credential handling (cached / refresh / re-consent), token persisted to
  `token.json` (gitignored). Access token + refresh token confirmed.
- `gmail.py` and `fetch.py` are **stubs** (TODO + `raise NotImplementedError`),
  created with opencode, deliberately left for me to fill.
- Build order: `gmail.py` → `fetch.py`. fetch.py depends on gmail.py, so gmail first.
- NEXT: write `get_service()` in `gmail.py`. Three steps: call `get_credentials()`,
  hand it to Google's service builder with `"gmail"`/`"v1"`, return the result.
- Gate: `uv run python -m email_manager.auth` then `uv run python -m email_manager.fetch N`
- Check: `uv run ruff check src && uv run ruff format src && uv run pyright`
- OAuth consent screen must be set to "In production" or the refresh token dies
  every 7 days. Token currently good, but verify `refresh_token: OK` before trusting
  any unattended run.

## Access-layer decisions (settled — don't relitigate)
- Gmail API v1, OAuth **desktop-app** client. Scopes: `gmail.modify` + `gmail.labels`.
- `gmail.modify` = read / label / archive (`removeLabelIds:["INBOX"]`) / trash
  (`addLabelIds:["TRASH"]`). It **cannot permanently delete** — that needs the
  full `https://mail.google.com/` restricted scope. We never permanent-delete
  anyway; trash is reversible, which is what I want.
- `gmail.readonly` is a dead end for this project — it can't be widened in
  place. Must delete `token.json` and re-consent with the right scopes.

## Gotchas learned (verified against Google's own docs, not blogs)
- **OAuth apps start in "Testing" status → refresh token DIES EVERY 7 DAYS.**
  Fix: set the consent-screen publishing status to **"In production"**.
  Verification is NOT required for personal use (<100 users) — I click through
  one scary warning screen once. This is THE thing that makes unattended
  operation possible; without it the tool needs me weekly.
- `google-auth-oauthlib` sets `access_type=offline` **automatically**
  (`flow.py` → `authorization_url` does `kwargs.setdefault("access_type","offline")`).
  I don't need to pass it.
- **The Gmail API does NOT require a billing account or credit card.** A vendor
  blog claimed it does — that's wrong. Google's own quickstart never mentions
  billing. Free within quota.
- Quotas: 6,000 units/min/user. Per-call: `messages.get`=20, `messages.list`=5,
  `history.list`=2, `modify`=5, `batchModify`=50, `watch`=100. Daily billing
  threshold is 80M/project/day and we're nowhere near it. A full backfill of a
  big mailbox will hit the 6,000/min ceiling → throttle deliberately.
- Gmail built-in filters: **1,000 max per mailbox**, only **one user-defined
  label per filter**, and they do **not** apply retroactively to existing mail.
- `historyId` can go stale; on a 404 fall back to a full `messages.list` re-sync.
- IMAP (if ever used): `\Deleted`+`EXPUNGE` does NOT delete in All Mail, and
  max 15 concurrent connections. Reason we chose the API over IMAP.

## Architecture (build in this order)
- **Layer 0** — Gmail built-in filters via `settings.filters`. Server-side, free,
  instant, zero CPU, never breaks.
- **Layer 1** — fetch + sync loop over the Gmail API. Metadata first, bodies last.
- **Layer 2** — classifier: **TF-IDF + LinearSVC**, retrains in seconds. NOT
  PyTorch — that's overkill for this.
- **Layer 3** — local Ollama 3–4B model, only for the low-confidence leftovers.
- **Layer 4** — weekly embeddings + HDBSCAN to discover new rule candidates.

Decided against for now: PyTorch fine-tuning, Gemini API (free tier may use my
mail to improve Google products), IMAP. All are documented escape hatches.

## Gate commands
- Auth: `uv run python -m email_manager.auth`
- (add lint / test commands here once they exist)

## Safety rules for the tool itself (non-negotiable)
Dry-run mode first. Log every decision with its reason. Auto-archive only, never
auto-delete. A config kill-switch. Never touch anything starred or important.
