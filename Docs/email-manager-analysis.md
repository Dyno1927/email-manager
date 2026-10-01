# Building an Autonomous Email Manager — Full Analysis

Written by me (Khanishk) for my own reference, Sept 2026. My goal: a tool that
sorts, labels, archives and summarizes my Gmail **on its own**, without me
supervising it. This doc is the "what are my real options" deep dive I did before
writing a single line of code.

Everything below is either (a) quoted from official docs with a link, or (b)
clearly marked as my own estimate. I checked the important claims myself rather
than trusting blog posts — two things I found were flat-out wrong at first, and
I'll call those out because they're the kind of trap I'd otherwise have walked
into.

---

## 1. What I Actually Want (requirements)

Let me be honest about the requirements before comparing solutions, because
"email manager" is vague and most bad decisions here come from not pinning it down.

| # | Requirement | Why |
|---|---|---|
| R1 | Runs **unattended** on a schedule (cron / systemd timer) | I don't want to remember to run it |
| R2 | **Autonomous** — decides without asking me | The whole point |
| R3 | Works on **one personal @gmail.com** account | Not a Workspace org, not multi-user |
| R4 | Runs on my box: Arch, 8 cores, 23GB RAM, **no GPU**, 35GB disk | No rented servers, I'm cheap |
| R5 | Python, `uv` project-local venv | My rule, no global packages |
| R6 | Cheap to run — ideally $0 | It's for me, not a product |
| R7 | **Reversible / safe** — it must never lose mail | Worst outcome is silently deleting something important |
| R8 | Privacy is nice-to-have, not blocking | I send my email to Google's own servers anyway (I use gmail.com) |

R7 is the one people skip and I think it's the one that matters most. An
autonomous tool that can trash mail needs a **kill switch** and a **dry-run mode**
from day one.

---

## 2. The Two Decisions That Actually Matter

Every option reduces to two orthogonal choices. People mix them up, so let me
separate them clearly:

**Decision A — How do I read/write the mailbox?**
(A1) Gmail API · (A2) IMAP · (A3) Apps Script · (A4) Gmail's own filters only

**Decision B — Who decides what category an email is?**
(B1) Gmail's built-in filters · (B2) My own if/else rules ·
(B3) Classical ML (TF-IDF / fastText) · (B4) Embeddings + clustering ·
(BB5) Local LLM (Ollama) · (B6) Gemini API · (B7) Fine-tuned transformer (PyTorch)

These combine. The best answer is almost certainly a **stack**, not a single pick.

---

## 3. Decision A — The Access Layer

### A1. Gmail API v1 — the main character

REST API, OAuth2, proper label semantics. This is the modern, correct choice.

**Quota system** (verified, [official usage limits](https://developers.google.com/workspace/gmail/api/reference/quota)):

Two buckets, both per project:
- Per minute per project: **1,200,000 quota units**
- Per minute per user per project: **6,000 quota units**
- Daily billing threshold: **80,000,000 units/project/day** — under this you are
  not billed at all.

Per-method costs (the ones that matter):

| Method | Units |
|---|---|
| `history.list` | 2 |
| `messages.list` | 5 |
| `messages.get` | 20 |
| `messages.modify` | 5 |
| `messages.batchModify` (≤1000 ids) | 50 |
| `labels.create` | 5 |
| `watch` | 100 |

**Do I need a credit card?** No. I checked this carefully because a vendor blog
(Unipile) confidently claims Gmail API requires linking a billing account. I
grepped Google's own Python quickstart end to end: the words `billing`, `credit
card`, `charge`, `cost`, `free tier`, `quota`, `pricing` appear **zero times**.
The prerequisites are just: Python 3.10+, pip, a Cloud project, a Gmail account.
Gmail API is free within quota. The 80M/day threshold exists but you'd need to
be ~12,000× over my daily usage to ever think about it.

> **Correction logged:** my first research pass told me a billing account was
> mandatory. It isn't. Flagging this because vendor blogs are not docs.

**Scopes** (verified, [scope table](https://developers.google.com/workspace/gmail/api/auth/scopes)):

- `gmail.modify` — **restricted** scope. Read, label, archive (remove `INBOX`),
  trash (add `TRASH`), compose. **Cannot permanently delete** — that needs
  `https://mail.google.com/`, the full-access restricted scope.
- `gmail.labels` — non-sensitive. Just label CRUD.
- `gmail.settings.basic` — restricted. Needed to manage **filters** server-side.

I need `gmail.modify` + `gmail.labels`. That's the minimum that does everything I
listed. Permanent-delete I'll live without — trash is reversible, which is what
R7 wants anyway.

**Pros**
- Clean label semantics. "Archive" is literally `removeLabelIds: ["INBOX"]`.
- Incremental sync via `history.list` (2 units) is 2.5× cheaper than
  `messages.list` (5 units) and tells you *what changed* (added/removed labels).
- No connection to maintain; it's stateless HTTP.
- Python client `google-api-python-client` is alive, weekly releases, supports
  Python 3.10–3.14.
- Free at my volume, by a factor of ~12,000.

**Cons**
- OAuth dance (see §4 — this is the real cost).
- Needs a Cloud project even though it's free.
- Per-minute-per-user cap of 6,000 units means the **initial backfill of a big
  mailbox needs throttling**. At 20 units/message, 6,000 units = 300 messages
  per minute. If I have 50k old messages that's ~3 minutes of deliberate,
  rate-limited work. Not a problem, but it must be *coded* deliberately, not
  assumed.

### A2. IMAP

Works on gmail.com, enabled by default, no Cloud project. Gmail advertises a
rich capability set (`X-GM-EXT-1`, `UIDPLUS`, `QRESYNC`, `CONDSTORE`, `IDLE`,
`LITERAL+`).

**The killer gotcha**, and this is the one that would have burned me: Gmail's
IMAP does not behave like standard IMAP for deletion. `STORE +FLAGS (\Deleted)`
auto-expunges in most folders, but in `[Gmail]/All Mail` the message **just
reappears** after `EXPUNGE`. To actually delete you have to `COPY` to
`[Gmail]/Trash` and expunge *there*. Also: nested labels must be created layer
by layer, and renaming labels over IMAP is unreliable.

**Pros**: no Cloud project, no billing question, works entirely offline-ish,
`IDLE` gives real push on the selected mailbox.
**Cons**: a stateful connection to babysit (max ~15 concurrent per account),
those non-standard deletion semantics, a 15-connection cap that my phone +
laptop + script can collectively approach, and it wants the full
`mail.google.com/` scope for XOAUTH2.

**Verdict**: viable, but every one of those quirks is a bug waiting to happen
when a script runs unattended. The Gmail API is the same information without the
foot-guns. IMAP is what I'd use if I *didn't* want a Google Cloud project at all,
and even then I'd use `imapclient`, not stdlib `imaplib` (which has no
`LITERAL+` support).

### A3. Google Apps Script

Genuinely underrated for this specific job, and it dodges the entire OAuth
problem in §4 because there's no refresh token to expire — the script runs *as
me* under Google's own auth.

Relevant quotas (consumer/free account):
- **6 min max per execution** (this used to be 30 for Workspace; it's 6 for both now)
- **90 min/day total trigger runtime** (Workspace gets 6h)
- **20,000 UrlFetch calls/day**
- Trigger-based min interval: 1 hour for consumer accounts

**Pros**: zero setup, zero auth code, GmailApp is a first-class API, free,
runs on Google's infra so it never dies when my laptop sleeps, and the trigger
system is the built-in "autonomous scheduler."
**Cons**: JavaScript only (not Python, which breaks my R5), the 6-minute
execution ceiling is a real ceiling — I can't run a slow local model in it, and
calling out to a local Ollama on my box means the script needs a public
endpoint, which breaks the model; 90 min/day is tight if I ever add something
slow; the whole ecosystem is quirky and hard to version-control.

**Verdict**: this is the *pragmatic champion* if I'm honest about wanting results
fast. But it locks me into JS and a 6-min ceiling, and I want the local-model
option later. I'll keep it as a documented alternative and as a fallback if the
OAuth thing proves painful.

### A4. Gmail's built-in filters, used as an API

Not really an "access layer" but a fourth option that deserves its own row,
because it does a surprising amount of the job. Via
`users.settings.filters` (needs `gmail.settings.basic`), I can create filters
programmatically that Gmail itself evaluates server-side. Rules match on
`from`, `subject`, `query` (full Gmail search syntax), `hasAttachment`, `size`,
`negatedQuery`, etc. Actions: add/remove labels, forward.

**Pros**: runs on Google's servers — zero cost, zero CPU, zero latency for my
box, and it fires the *instant* mail arrives, before any cron of mine could wake
up. It never breaks, never needs a token refresh, can't fail because my laptop
is asleep.
**Cons**:
- **Hard cap of 1,000 filters per mailbox** (verified, [filters/create
  reference](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.filters/create))
- **Only ONE user-defined label per filter** (verified, [Manage Gmail filters
  guide](https://developers.google.com/workspace/gmail/api/guides/filter_settings)).
  System labels are unlimited but a custom label is 1:1. So one filter can't
  stamp both `Newsletters` and `Low Priority`. That's a genuinely annoying cap.
- **Filters don't retroactively apply to existing mail** — a filter only affects
  future arrivals. Backfilling my existing 20k messages is a separate script.
- Can only match on *what's* the email, not on what it *means*.

That last one is the key limitation and it's what makes B1 necessary-but-not-
sufficient.

---

## 4. THE TRAP: the 7-day refresh token

This is the single most important operational detail in the whole project, and
almost every tutorial skips it. If I get this wrong my "autonomous" tool
silently breaks every 7 days and I have to be there to re-click a consent
screen. That directly violates R1/R2.

**The rule, quoted from [Google's OAuth docs](https://developers.google.com/identity/protocols/oauth2):**

> "A Google Cloud Platform project with an OAuth consent screen configured for an
> external user type and a publishing status of 'Testing' is issued a refresh
> token expiring in 7 days, unless the only OAuth scopes requested are a subset
> of name, email address, and user profile."

I'm requesting `gmail.modify` — not a subset of name/email/profile. So **Testing
status = my refresh token dies every 7 days.** Every new OAuth app starts in
Testing. This is the default trap.

**The fix**, and it's much cheaper than it looks:

Switch the publishing status from **Testing** to **In production**. Confirmed from
[Google's OAuth app state table](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview),
the *Published / External / Unverified* row reads:

> "Any Google user can access. ... for apps requesting sensitive or restricted
> scopes, unverified app warnings (Danger UI) will be displayed to users, and a
> hard cap of 100 total users applies."

So publishing while unverified gives me:
- ✅ **No 7-day refresh token expiry** (the 7-day rule is scoped to *Testing*
  status; the same doc's "Trusted" override paragraph explicitly calls it "the
  7-day refresh token expiration limit for apps in the **Testing** status")
- ✅ Verification is explicitly *not* required — [Google's own policy page](https://support.google.com/cloud/answer/13464323)
  says: "**Personal Use apps**: If the app is for your personal use (fewer than
  100 users), you and your limited number of users can continue using the app
  without going through verification"
- ⚠️ A scary "Google hasn't verified this app" warning screen — I click through
  once, at consent time, and never see it again
- ⚠️ 100-user cap — irrelevant, I'm the only user

**The trade is: one scary-looking consent screen, once, in exchange for
permanent auth.** That's obviously right for a personal tool. Verification
(review process, demo video, privacy policy, weeks of waiting) buys me nothing
here because there's no user cap for me to exceed and no branding to protect.

Refresh tokens can still die for reasons I can't control (I revoke access, 6
months unused, password change with Gmail scopes). So the tool still needs to
detect `invalid_grant` and tell me loudly — but that's a rare edge case, not a
weekly chore.

---

## 5. Decision B — The Intelligence Layer

This is where "gemini free api vs a rule based system with pytorch" actually gets
answered. Let me go in order of increasing complexity.

### B1/B2. Gmail built-in filters + my own if/else rules

Gmail search operators give me a lot: `from:`, `list:`, `has:attachment`,
`larger:`, `is:unread`, `-from:`, `{from:a from:b}`, `subject:`. Combined with
`List-Id` / `Precedence` headers (newsletter detection is basically `list:`
presence — very reliable, this is a nearly perfect signal).

- **Accuracy**: perfect, but only for patterns I thought of in advance
- **Effort**: near zero
- **Cost**: zero
- **CPU**: zero (server-side)
- **Big weakness**: doesn't generalize. A newsletter from a sender I've never seen
  slips right through. This is exactly the hard part of the problem.

I should not skip this layer. My estimate is that sender/subject/header rules
catch 60–70% of mail with perfect precision, and the AI only ever sees the
annoying remaining 30–40%. That reduces cost and risk more than any clever
model choice.

### B3. Classical ML — TF-IDF + linear model, or fastText

This is the answer to "is PyTorch too much". **Yes, for the classifier, PyTorch
is too much.**

- **TF-IDF + LinearSVC / LogisticRegression** (scikit-learn): train on
  `subject + first ~500 chars + sender domain`. Trains in **seconds** on a few
  hundred labeled examples. Inference is **sub-millisecond**. Model file is
  tens of MB. Handles 7–10 classes comfortably. On short text like email
  subjects this is a genuinely strong baseline — it regularly matches small
  transformers.
- **fastText** (Facebook, C++, MIT): n-grams + linear, trained in **under a
  minute** on 8 threads. Native multi-label. Quantized models are tiny. The
  2016 paper reports ~500k sentences/min inference. Doesn't need PyTorch at all.

- **Accuracy**: good, noticeably worse than a real LLM on genuinely ambiguous
  mail ("is this a personal email or a phishing attempt?")
- **Effort**: low. The annoying part is *labeling* — I need a few hundred
  examples, which I mostly get for free by running the rules for a month and
  fixing its mistakes.
- **Cost**: $0
- **Privacy**: perfect, local
- **CPU**: irrelevant — the whole 200-email day takes under a second

The killer feature: **it's retrainable in 30 seconds.** When it gets something
wrong I add that example and regenerate. That feedback loop is much tighter than
prompt-engineering an LLM.

### B4. Embeddings + clustering

`bge-small-en-v1.5` (133MB, 512 tokens) or `all-MiniLM-L6-v2` (90MB) or
model2vec's `potion-base-32M` (125MB, distilled static embeddings — ~100x faster
than a transformer, ~89% of MiniLM quality). Then HDBSCAN over the vectors.

- **Accuracy**: no labels needed. Finds *categories I didn't think of*, which is
  the thing rules structurally cannot do
- **Effort**: medium
- **Best use**: a **weekly discovery run**. "Here's a cluster of 40 emails from
  a sender I've never seen that all look alike" → I look, decide, then promote
  it into a B1 filter or a B3 training example. It closes the loop between "rule
  system" and "ML" — it *proposes* new rules.
- **Cost**: $0, privacy perfect, CPU fine

This is the sleeper pick. It's how a rule-based system stops being a dead end.

### BB5. Local LLM (Ollama)

Pull a small quantised GGUF — `qwen3:4b` (~2.5GB), `llama3.2:3b` (~2GB),
`gemma3:4b` (~3.3GB), `llama3.2:1b` (~1.3GB) — run a few-shot prompt, get
structured JSON back. Ollama takes a JSON Schema in the `format` field, so the
output is guaranteed-parseable, not "usually parseable". No API key, nothing
leaves the box.

Measured CPU decode throughput on 8 cores (Zen 4 class, from a public benchmark):
roughly 200 tok/s for 1B, 110 tok/s for 3B, 78 tok/s for 4B. At 512 tokens per
email, a 3B model is **~5 seconds/email** — so 200 emails is ~15 min of CPU
spread over a day. Totally fine for a cron job. Memory is 2–4GB, I have 23.

- **Accuracy**: best local option. Handles "what is this email *about*"
- **Effort**: medium. Installing Ollama, pulling a model, writing a prompt,
  tuning it. Also: 2.5–4GB of models to store on my 35GB disk
- **Cost**: $0
- **Privacy**: perfect — nothing leaves the machine
- **Cons**: prompt engineering is fiddly, it's slower, and a 3B model's
  classification accuracy is *not* dramatically better than B3 for clean cases.
  Its real win is handling the *messy* 30% that rules can't touch.

### B6. Gemini API (free tier)

My original instinct, and it's a reasonable one. Free, no local compute, best
raw quality.

**Free tier mechanics** ([rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)):
- No billing account needed — the Free tier just needs "an active project"
- Limits are **per project, not per API key**; RPD resets midnight Pacific
- Google **no longer publishes a stable universal RPM/TPM table** — active limits
  are shown in the AI Studio console, and the docs explicitly say "specified rate
  limits are not guaranteed." So I should not plan against a number I read on a
  blog; I should read my console.
- Current free models include the 2.5/3.x Flash and Flash-Lite families
- JSON mode / structured output / function calling all work on free tier
- India and Pakistan are both supported regions

**The catch, and it's a real one** — from the official [pricing page](https://ai.google.dev/gemini-api/docs/pricing),
the table literally has a row called *"Used to improve our products"*:
- Free tier: **Yes**
- Paid tier: **No**

So on the free tier, **my email content — subjects, senders, body text — may be
used to improve Google products**, and human reviewers may read it. On paid
tiers you get Zero Data Retention instead.

Let me be honest with myself about this. R8 said privacy is nice-to-have, not
blocking, and I *am* already giving Google my entire mailbox. So this is
defensible. But it's not nothing: my email corpus includes things I wouldn't
want a stranger reading, and the "human reviewers may read" clause is the part
that actually gives me pause, not the model training.

**Cost math** (my estimate, using current Flash rates — check the pricing page,
they change): ~500 input + ~50 output tokens per email. At Flash-tier prices
that's well under a cent per email, so a few dollars per month at 200 emails/day
on the paid tier. Free tier is $0.

**Cons beyond privacy**: 15 RPM means I need to batch and rate-limit; a network
dependency in a tool that's supposed to run autonomously; and the free tier is
documented as *not guaranteed* — I could be throttled unpredictably. Also
relevant: since March 2026 Gemini API spend is **excluded from the $300 GCP free
trial**, and accounts opened after Mar 2 2026 can't use GCP credits for it at
all — paid Gemini needs a Prepay plan, minimum $5 top-up.

### B7. Fine-tuned transformer in PyTorch

A small encoder (DistilBERT / MiniLM / `bge-small`) fine-tuned on my labeled mail.
BERT-family classifiers are the standard strong baseline.

- **Accuracy**: high on known categories
- **Effort**: **high**. This is the one that needs a real dataset, a training
  loop, checkpoints, evaluation, and then a retraining story when things drift
- **Cost**: $0, CPU-trainable in minutes for a small model on 8 cores
- **Good news on the version risk**: I checked, and **PyTorch supports Python
  3.14** — 2.9+ covers 3.10–3.14, and the 2.10 release notes explicitly mention
  Python 3.14 support. So the "torch won't install on 3.14" worry I had is
  resolved; CPU wheels exist. (I'd still probably use my uv 3.12 for the ML
  project since that ecosystem is more settled.)
- **Verdict**: **this is the "too much" instinct and it is correct.** Not because
  it's hard, but because B3 gets ~85% of the accuracy for 5% of the effort and
  retrains in 30 seconds. I'm keeping this in my back pocket for *if* the
  classical version plateaus and I have real labeled data.

---

## 6. Side-by-side

Scoring is my judgment for *this* task (email triage, 1 user, no GPU,
unattended), on a 1–5 scale.

| Option | Accuracy | Effort | $/mo | Privacy | CPU OK | Verdict |
|---|---|---|---|---|---|---|
| **A4+B1** Gmail built-in filters | 2 | 1 | 0 | perfect | free (server) | **Foundation — do this first** |
| **B2** my own if/else rules | 2 | 2 | 0 | perfect | free | Foundation, same layer |
| **B3** TF-IDF + LinearSVC | 3 | 2 | 0 | perfect | instant | **Best value overall** |
| **B3'** fastText | 3 | 2 | 0 | perfect | instant | Same, C++ and multi-label |
| **B4** embeddings + HDBSCAN | 3 | 3 | 0 | perfect | seconds | **Best rule-discovery tool** |
| **BB5** Ollama 3–4B local | 4 | 3 | 0 | perfect | ~5s/email | **Best quality, fully private** |
| **B6** Gemini free tier | 5 | 2 | 0 | ⚠️ see §5 | free | Best quality, ToS cost |
| **B6'** Gemini paid (ZDR) | 5 | 2 | ~$3 | good (ZDR) | free | Same, no ToS cost |
| **B7** PyTorch fine-tune | 4 | 5 | 0 | perfect | minutes | Overkill for now |
| **A2** IMAP | n/a | 3 | 0 | perfect | fine | Only if avoiding Cloud project |
| **A3** Apps Script | 3 | 1 | 0 | good (Google-side) | free | Fastest to prototype |

Note B6 scores best on accuracy and near-worst on privacy, and B1 scores worst on
accuracy and best on everything else. That's the whole trade in one table.

---

## 7. What I'm Actually Going To Do

A layered stack, each layer doing what it's good at, with the cheap reliable one
underneath the expensive smart one.

**Layer 0 — Gmail built-in filters (A4+B1).** Server-side, zero CPU, instant.
Header and sender rules: `list:` → `Newsletters` + archive + mark read.
Known senders (GitHub, banks, orders) → labels. Managed as code through the
`settings.filters` API, not clicked into the UI, so it's version-controllable.
*Watch the 1-label-per-filter and 1,000-filter caps.*

**Layer 1 — The fetch + sync loop (A1).** Gmail API, `gmail.modify` +
`gmail.labels`. A systemd timer / cron every 10 min. Cheap and dumb: fetch
unseen message metadata, fetch bodies only for things layers 0–2 haven't already
claimed. Persist a cursor. Handle `invalid_grant` loudly. Rate-limit myself
under 6,000 units/min.

**Layer 2 — Classical classifier (B3).** TF-IDF + LinearSVC over
`sender domain + subject + first N chars`. Retrain in seconds as I correct it.
This is the workhorse and it will handle most of what layer 0 misses.

**Layer 3 — Local LLM for the hard remainder (BB5).** Only for messages layer 2
is unsure about. Few-shot prompt + JSON schema → `{"label": ..., "confidence":
...}`. Low confidence → leave it in the inbox and optionally flag it for me.
Fully local, so no ToS compromise, and it only runs on maybe 10–20 emails/day
rather than 200.

**Layer 4 — Weekly discovery (B4).** Embed the last week's unclassified mail,
HDBSCAN, show me the clusters, promote findings into layer 0 or layer 2. This is
how the system keeps getting better without me maintaining rules forever.

**Explicitly not doing, for now**: PyTorch fine-tuning (B7), Gemini (B6), IMAP
(A2). All still on the table as escape hatches — if the local LLM turns out to be
too slow, Gemini is a one-function swap. If the 6-min ceiling of Apps Script ever
becomes the bottleneck, that's the fallback architecture.

**Safety requirements before any auto-archive goes live** (R7):
- Dry-run mode that logs every decision without touching the mailbox
- Auto-archive only, never auto-delete, until I've watched it run clean for weeks
- Every decision written to a local log with the reason, so I can audit
- A config kill-switch I can flip without touching code
- Never let it touch anything already in a starred or important label

**Roadmap order**: Layer 0 (a weekend) → Layer 1 (a week, mostly auth) →
Layer 2 (a week) → observe and correct for a month → Layer 4 → Layer 3 only if
Layer 2 actually plateaus. The temptation will be to start at Layer 3. Don't.
Layers 0–2 will handle most mail and cost nothing.

---

## 8. Hard Constraints Checklist

Things that will bite, gathered from the research:

1. **OAuth apps start in Testing → 7-day refresh token expiry.** Fix: publish to
   In production, stay unverified. Non-negotiable for autonomy. (§4)
2. **`gmail.modify` cannot permanently delete.** Only trash. Fine — that's safer.
3. **6,000 quota units/min/user.** 20 units per `messages.get` = 300 messages/min
   ceiling. Backfill needs deliberate throttling.
4. **historyId can go stale** — if a `history.list` 404s, fall back to a full
   re-sync. Store the cursor persistently.
5. **Gmail filters: 1,000 max, 1 user-defined label each, no retroactive
   application.** (§A4)
6. **10,000 labels max per mailbox** — not a real constraint, but it's a documented
   ceiling.
7. **IMAP: `\Deleted`+`EXPUNGE` doesn't delete in All Mail; 15 connections max.**
   Only relevant if I go the IMAP route.
8. **Gmail push/Pub/Sub is overkill here** and Google's own docs recommend
   *polling* over push for most cases. `watch` expires in 7 days (renew daily),
  and notifications are **dropped at 1 event/sec/user** with a documented
  "notifications might be delayed or dropped" caveat, so a real deployment needs
  a periodic `history.list` fallback anyway. Polling every 10 min is simpler and
  has no expiry to babysit. **Not doing push.**
9. **Gemini free tier may use my email content for product improvement, readable
  by human reviewers.** And free-tier rate limits aren't guaranteed. (§B6)
10. **PyTorch does support Python 3.14** (2.9+), CPU wheels included. The old
    blocker is gone.
11. **Gemini API can't be paid for with GCP free-trial credits** since March 2026;
    paid tier needs Prepay, min $5.
12. **Apps Script: 6 min/execution, 90 min/day trigger runtime, 20k UrlFetch/day**
    on a consumer account. And min 1-hour trigger interval.

---

## 9. Things I Could Not Verify

Being honest rather than confident:

- **Exact Gemini free-tier RPM/RPD numbers.** Google has stopped publishing a
  stable universal table; limits are per-project and visible in the AI Studio
  console. Any blog quoting exact free-tier numbers for current models is
  probably quoting a stale table. **Read my own console before planning around it.**
- **My own mailbox size and daily volume.** Every cost estimate scales off
  "200 emails/day" which I guessed. The real number changes the math.
- **Local LLM decode throughput on *my* CPU.** The benchmarks I found are on
  Zen 4 mobile parts. My machine will be in the same ballpark but I should
  measure, not assume.
- **Whether classification accuracy actually plateaus with B3.** I don't know yet
  how separable my mail is. Might be easier than I think (email is very
  structured) or might need layer 3 sooner.

---

## 10. Sources

The load-bearing ones — everything I corrected or made a decision on:

- [Gmail API usage limits (quota)](https://developers.google.com/workspace/gmail/api/reference/quota)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Gmail API Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python) — the source that disproved the billing-card myth
- [OAuth 2.0 refresh token expiration (the 7-day rule)](https://developers.google.com/identity/protocols/oauth2)
- [OAuth app state overview (Testing vs Published, verified vs unverified)](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)
- [When verification is not needed (personal-use exemption)](https://support.google.com/cloud/answer/13464323)
- [Manage Gmail filters (1,000 cap, 1-label-per-filter)](https://developers.google.com/workspace/gmail/api/guides/filter_settings)
- [filters.create reference](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.filters/create)
- [Configure push notifications (watch expiry, 1 event/sec, dropped notifications)](https://developers.google.com/workspace/gmail/api/guides/push)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API pricing (the "used to improve our products" row)](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API terms of service (unpaid services data use)](https://ai.google.dev/gemini-api/terms)
- [Gemini billing and tiers](https://ai.google.dev/gemini-api/docs/billing)
- [PyTorch 2.10 release blog (Python 3.14 support)](https://pytorch.org/blog/pytorch-2-10-release-blog)
- [PyTorch on PyPI (current version + Python requires)](https://pypi.org/project/torch)
- [Apps Script quotas and limits](https://developers.google.com/apps-script/guides/services/quotas)
- [Gmail IMAP extensions (X-GM-LABELS, X-GM-THRID)](https://developers.google.com/workspace/gmail/imap/imap-extensions)
- [Gmail IMAP XOAUTH2](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol)
- [fastText paper](https://arxiv.org/abs/1607.01759) · [fastText repo](https://github.com/facebookresearch/fastText)
- [gmailctl — Gmail filters as code, Jsonnet](https://github.com/mbrt/gmailctl)
