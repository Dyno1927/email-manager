# email-manager — project rules

My autonomous Gmail triage tool: sorts, labels, archives, summarizes my mail
without me supervising it. Full decision writeup lives at
`Docs/email-manager-analysis.md` **in this repo** (tracked in git — read that
before relitigating any architecture choice).

Note: this used to say `~/Documents/email-manager-analysis.md`. That path no
longer exists; the doc moved into `Docs/`.

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

**Running the modules:** always `-m`, never a file path —
`uv run python -m email_manager.fetch`, not `uv run python src/email_manager/fetch.py`.
A file path leaves Python with no package context, so sibling imports fail with
`ImportError: attempted relative import with no known parent package`. `auth.py`
appears to work that way only because it imports nothing from the package.

## Current phase (as of 2026-10-01)
- Repo on `main`, Python 3.12, deps installed, `credentials.json` down, gitignored. ✓
- **No stubs left.** All three modules written, all gates green:
  - `auth.py` — OAuth desktop-app flow, three-state credential handling
    (cached / refresh / re-consent), token persisted to `token.json` (gitignored).
  - `gmail.py` — `get_service()` builds the Gmail v1 handle via
    `build("gmail", "v1", credentials=creds)`.
  - `fetch.py` — `list_recent()` + `main()`. **Written by opencode at khanishk's
    explicit request**, which overrode the teach-don't-write rule for this file only.
    Read-only by design: lists recent mail, changes nothing.
- NEXT (khanishk's call): he has been offered, and has deferred, three options —
  Layer 0 server-side filters, the Layer 1 sync cursor, or the first write via
  `modify()`. He picked `modify()`, then immediately reframed it as a Gemini-based
  classifier. See "PENDING DECISION" below. Nothing built yet; `config/` still empty.
- Gate: `uv run python -m email_manager.auth` (must print `refresh_token: OK`) and
  `uv run python -m email_manager.fetch N` (default 10). Both verified working
  against the live mailbox on 2026-10-01.
- Check: `uv run ruff check src && uv run ruff format src && uv run pyright`
  - **pyright was installed into the `dev` group on 2026-10-01.** It had never been
    installed, so that gate command was failing before this. Don't assume it's there.
  - `pyrightconfig.json` sets `reportUnknownVariableType: none` alongside the other
    three Unknown reports — Google's API libs ship no type info, so `build()` resolves
    to `Unknown` and strict mode flags it. Not a code defect.
  - `fetch.py` needs a **local** `# type: ignore[reportAttributeAccessIssue]` on the
    `service.users()` chain. Chaining off the service object is invisible to pyright.
    Keep it local — relaxing `reportAttributeAccessIssue` in the config would hide
    genuine attribute errors everywhere else.
  - **Trap that cost me a wrong suggestion:** `Resource.get_service()` does not exist.
    `Resource` is a type used for the *return annotation* only; the builder is the
    separate module-level function `build` from `googleapiclient.discovery`. Verified:
    `Resource` has exactly one member, `close()`.
- OAuth consent screen must be set to "In production" or the refresh token dies
  every 7 days. Token currently good, but verify `refresh_token: OK` before trusting
  any unattended run.

## Gmail API shapes I verified by running them (2026-10-01)
Don't re-derive these; they're facts about the live API, not guesses.
- **Nothing happens until `.execute()`.** Every method on the service object returns
  an `HttpRequest`, not data. Forget it and you get
  `AttributeError: 'HttpRequest' object has no attribute 'keys'` — I hit this myself.
- Chain: `service.users().messages().list(userId="me", maxResults=N).execute()`.
  `userId="me"` = the account that authorized the token. `messages()` exposes
  `list, get, modify, trash, batchModify, batchDelete, insert, import_`.
- `list()` returns a **dict** with keys `messages`, `nextPageToken`,
  `resultSizeEstimate`. Each entry has only `id` and `threadId` — **no sender,
  no subject.** That's why a second `get()` call per message is required.
- `get(id=..., format="metadata")` returns `id`, `threadId`, `labelIds`, `snippet`,
  `payload`, `sizeEstimate`, `historyId`, `internalDate`.
- `payload` holds `mimeType` and `headers`. **`headers` is a flat LIST of
  `{"name":..., "value":...}` dicts (29 on a real message), not a dict** — you cannot
  do `headers["From"]`. Fold it into a dict first.
  Real first entries are mail-server plumbing: `Delivered-To`, `Received`, `X-Received`,
  `ARC-Seal`. **`From` and `Subject` sit far down the list — never assume index 0.**
- `labelIds` came back as `['UNREAD', 'IMPORTANT', 'CATEGORY_UPDATES', 'INBOX']`.
- Real quota cost of `list_recent(N)`: 5 units for `list` + 20 per `get`, so
  5 + 20N. Ten messages = 205 units against the 6,000/min ceiling. A full-mailbox
  backfill would blow through it, which is why throttling is still outstanding.

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
  instant, zero CPU, never breaks. **Not started.**
- **Layer 1** — fetch + sync loop over the Gmail API. Metadata first, bodies last.
  Half done: read-only listing works, the *sync cursor* half (persisting `historyId`
  so reruns don't refetch everything) is not built. Note Layer 0 is listed first
  because it does the same job for free — khanishk may want it before going further.
- **Layer 2** — classifier: **TF-IDF + LinearSVC**, retrains in seconds. NOT
  PyTorch — that's overkill for this.
- **Layer 3** — local Ollama 3–4B model, only for the low-confidence leftovers.
- **Layer 4** — weekly embeddings + HDBSCAN to discover new rule candidates.

## PENDING DECISION — Gemini classifier (raised 2026-10-01, nothing built)
khanishk proposed **replacing Layer 2/3 with the Gemini API**: send each email,
ask where it belongs, apply the label, star if important, auto-trash junk.
**No code written. No API key set** (nothing in env, `config/` is empty).
He asked me to save this rather than start, so this is a parked design question.

If he confirms it, these are the open questions I raised and he has NOT yet answered:
1. **Paid or free tier?** Free tier's published pricing has a row called *"Used to
   improve our products" = Yes*, so his mail may train Google products and be read
   by human reviewers (his own analysis doc §B6, which is why Gemini was ruled out).
   Paid = Zero Data Retention, but needs Prepay min $5 top-up, and Gemini API spend
   has been excluded from GCP free credits since March 2026.
2. **Does trash stay supervised?** He asked for auto-trash unattended. I pushed back:
   that's the exact failure mode his own safety rules exist to prevent.
3. Answer to my sequencing: **classify read-only → show the plan → approve →
   apply.** Never classify and write in the same pass. He has not objected.

Things I verified while discussing it (reusable):
- `modify()` is `POST gmail/v1/users/{userId}/messages/{id}/modify`, body keys
  `addLabelIds` / `removeLabelIds` (plus two `addClassification*` keys). 100 labels
  max per call. Cost: **5 units**. `batchModify` is 50 units for many at once.
- **Archive == `removeLabelIds: ["INBOX"]`** — reversible by re-adding INBOX. This is
  the cheapest safe first write.
- Live mailbox system labels: `CHAT SENT INBOX IMPORTANT TRASH DRAFT SPAM
  CATEGORY_FORUMS CATEGORY_UPDATES CATEGORY_PERSONAL CATEGORY_PROMOTIONS
  CATEGORY_SOCIAL YELLOW_STAR STARRED UNREAD`.
- **Do NOT ask the LLM "is this important"** — Gmail already computes `IMPORTANT`
  and puts it in `labelIds`. Free and more reliable. Let the model handle only
  user-defined labels.
- `YELLOW_STAR` and `STARRED` are both real labels, so starring is expressible.
  Note `STARRED` is also a boolean field on the message, distinct from `labelIds`.

Still unwritten, deliberately: kill switch + dry-run wrapper (`config/` is empty),
sync cursor. These were agreed as prerequisites for any write path.

## Gate commands
- Auth: `uv run python -m email_manager.auth` → must print `refresh_token: OK`
- Fetch: `uv run python -m email_manager.fetch 8` → read-only preview, live-verified ✓
- Lint/format/types: `uv run ruff check src && uv run ruff format --check src && uv run pyright`
  (no tests yet — when they exist, add them here)

## Commit workflow
- Edit loop: `uv run ruff check --fix src && uv run ruff format src` (these *write*)
- Then `git add -A && git commit -m "type(scope): description"`
- Message style in use: `add(x): ...`, `docs(memory): ...`, `fix(...)`.
- **A pre-commit hook exists** at `.git/hooks/pre-commit` — runs ruff check,
  ruff format --check, and pyright, and blocks the commit on failure. It *checks*,
  it never rewrites, so the fix commands above still have to run first.
  - Verified working both ways on 2026-10-01: clean tree exits 0, four injected
    ruff errors printed with line numbers and exited 1.
  - Needs `chmod +x` or git silently skips it.
  - **`.git/` is not tracked by git**, so this hook exists only on this machine.
    A fresh clone will not have it. Recreate or copy it over if that bites.

## Safety rules for the tool itself (non-negotiable)
Dry-run mode first. Log every decision with its reason. Auto-archive only, never
auto-delete. A config kill-switch. Never touch anything starred or important.
