# quip-export

Export everything from a personal Quip account to Markdown before Quip shuts down (subscriptions can't be renewed after March 1, 2027, and data deletion after that is permanent).

Quip has no bulk export button in the UI, so this script uses the Quip Automation API instead.

## What you get

```
quip-export/
├── Private/
│   ├── Some Doc.md        # Markdown + YAML front matter
│   ├── Some Doc.html      # raw Quip HTML (lossless fallback)
│   ├── Budget.md
│   ├── Budget.html
│   ├── Budget.xlsx        # spreadsheets also get native xlsx
│   └── _assets/           # images/attachments, relinked from the .md
├── Starred/ Archive/ <shared folders>/ ...
├── _Unfiled/              # docs shared with you but never filed in a folder
└── _index.json            # manifest of every exported thread
```

Each `.md` starts with front matter:

```yaml
---
title: "Some Doc"
quip_id: AbC123XyZ456
quip_link: https://quip.com/AbC123XyZ456
type: document
created: 2016-04-02T10:14:33
updated: 2019-11-20T08:01:12
---
```

## Setup

1. Get a personal API token (while logged in): https://quip.com/dev/token
2. Install dependencies (a virtualenv keeps them out of your system Python):

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install requests markdownify
   ```

## Usage

```sh
export QUIP_TOKEN=your_token_here
.venv/bin/python quip_export.py ~/quip-export
```

The output directory defaults to `./quip-export` if omitted.

## What to expect while it runs

- **Rate limits, so be patient.** Quip allows roughly 50 API requests per minute per user. Each doc costs one request, plus one per embedded image or attachment, so a few hundred docs takes tens of minutes. When the script prints `rate limited, sleeping Ns` it is backing off deliberately; this is normal, not an error.
- **Ctrl-C is safe.** Re-running picks up where it left off and skips docs that were already written.
- **`FAIL` lines are per-thread errors** that did not stop the run. Note the thread ID and re-run afterwards; if it fails again, check the endpoint against the API docs.
- **Folder names come from the API,** so the top-level directories may not match the `Private/`, `Starred/`, ... names shown above exactly.
- **Verify the count** when it finishes. The final line reports how many threads were exported this run; every thread produces exactly one `.md`, so this should match:

  ```sh
  find ~/quip-export -name '*.md' | wc -l
  ```

  Counting all files would overcount, because each doc also has an `.html`, spreadsheets add an `.xlsx`, and images land in `_assets/`.

## How it works

- **Folders:** Starts from `/1/users/current` and walks the private, desktop, starred and archive folders plus any shared and group folders, recursively. Folders and threads are deduplicated, so a doc that lives in two folders is only exported once.
- **Unfiled docs:** Sweeps `/1/threads/recent` to catch docs shared with you directly that aren't in any folder.
- **Per thread:** Fetches the HTML and downloads any `/blob/...` images or attachments into `_assets/`, rewriting the links to point at the local copies. It then writes `.html` and `.md` (converted with `markdownify`), plus `.xlsx` for spreadsheets. Chat threads are skipped.
- **Rate limits:** On a 429 or 503 it sleeps until `X-RateLimit-Reset`; the limit is about 50 requests per minute per user.
- **Resumable:** A thread is skipped if a `.md` with its `quip_id` already exists. Delete a file to re-export it.
- **Duplicate titles:** Two docs with the same title in one folder are written as `Title.md` and `Title (2).md` (then `(3)`, ...). The `quip_id` in the front matter decides which file belongs to which doc, so re-runs stay stable.

## Limitations

- **Comments:** Inline comments and conversation threads are not exported.
- **Live elements:** Salesforce data mentions and Live Apps don't carry over.
- **Markdown fidelity:** Complex tables, checklists and odd formatting may convert imperfectly. The `.html` sits alongside for exactly this reason.
- **Slides:** Slides docs export as whatever HTML the API returns, which may be sparse.
- **`_index.json` only lists threads exported in the most recent run.** After a resumed run it will not include threads written earlier. Count `.md` files instead (see above) if you need the full total.
- **API docs:** https://quip.com/dev/automation/documentation, if an endpoint misbehaves.

## Tips

- **Check before you delete anything:** Diff `_index.json` against what you've already moved to Apple Notes.
- **Re-run before shutdown:** The script is idempotent, so a final pass close to the deadline is cheap.
- **Revoke the token** at https://quip.com/dev/token when you're done.
