# email-manager

My own personal Gmail manager. The goal is to have it read my mail on a
timer, work out what's important, file it under my own labels, archive the
noise, and let me know about anything urgent — without me babysitting it.

This is a learning project. I'm building it in Python to actually understand
the Gmail API, OAuth, and a bit of ML, not to ship a product.

## Where it's at

- [x] OAuth2 login (my own Google account, desktop client, refresh tokens)
- [ ] Layer 1 — read-only fetch loop that lists new mail and changes nothing
- [ ] Layer 0 — Gmail's built-in filters (server-side, no code running)
- [ ] Classifier — TF-IDF + LinearSVC to sort mail
- [ ] Local LLM (Ollama) for anything the classifier isn't sure about
- [ ] Weekly clustering to discover categories I didn't think of

Right now auth works end to end. Everything after that is still stubs, and
I'm writing those by hand.

## How it works (the plan)

Layered, cheapest-first. Gmail's own filters are free and run even when this
project isn't running, so they do the obvious stuff. The Gmail API sync pulls
whatever's new. A small classifier handles the bulk. An LLM only gets the
messages the classifier is unsure about, so I don't burn compute on every
email. Once a week, clustering looks for groups I didn't set up myself.

## Safety rules I'm holding myself to

- **Read-only first.** No labels, no archives, no deletes until I've watched
  it be boring.
- **Dry run before real.** Every action gets logged and reversible until I
  say otherwise.
- **Never permanently delete.** Trash at most, and only for obvious junk.
- **Never touch starred or important mail.**
- **Kill switch.** One config flag turns off every write.
- **Every decision is logged**, so when it files something wrong I can see why.

## Setup

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
git clone <this-repo>
cd email-manager
uv sync
```

Then set up the Google side, once:

1. Google Cloud Console -> create a project.
2. Enable the Gmail API for it.
3. OAuth consent screen -> Desktop app, add myself as a test user
   (or publish it to Production).
4. Download the client secret and put it at `credentials.json` in the repo
   root. It's gitignored, never commit it.

`credentials.json` and `token.json` are both secrets. Don't commit either.

## Usage

Log in once (opens a browser, you click Allow):

```sh
uv run python -m email_manager.auth
```

It should print `refresh_token: OK`. If it says `MISSING`, revoke the app at
<https://myaccount.google.com/permissions>, delete `token.json`, run it again.

After that, credentials refresh themselves silently.

## Dev

```sh
uv run python -m email_manager.fetch 8   # read-only preview (stub for now)
uv run ruff check src/
uv run ruff format src/
```

## Layout

```
src/email_manager/
  auth.py    # OAuth + token refresh (done)
  gmail.py   # Gmail service wrapper (stub)
  fetch.py   # read-only fetch + preview (stub)
```

Python 3.12, `uv`, Google API client. Lint and format with Ruff.
