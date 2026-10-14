#!/usr/bin/env python3
"""
Export everything from a personal Quip account to Markdown (+ originals).

Setup:
  1. Get a personal token: https://quip.com/dev/token
  2. pip install requests markdownify
  3. QUIP_TOKEN=xxxx python3 quip_export.py ./quip-export

Output, mirroring your Quip folder tree:
  <folder>/<Title>.md     Markdown with YAML front matter (title, link, dates)
  <folder>/<Title>.html   raw Quip HTML (lossless fallback)
  <folder>/<Title>.xlsx   for spreadsheets
  <folder>/_assets/...    images/attachments, relinked from the .md
Re-runnable: already-exported threads are skipped (delete a file to redo it).
Same-titled docs in one folder get ' (2)', ' (3)', ... suffixes rather than colliding.
"""
import os, re, sys, time, json, datetime
import requests
from markdownify import markdownify as md

API = "https://platform.quip.com"
TOKEN = os.environ.get("QUIP_TOKEN") or sys.exit("Set QUIP_TOKEN (get one at https://quip.com/dev/token)")
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "quip-export")
S = requests.Session()
S.headers["Authorization"] = f"Bearer {TOKEN}"

def get(path, raw=False, **params):
    while True:
        r = S.get(API + path, params=params, timeout=60)
        if r.status_code == 429 or r.status_code == 503:   # rate limited (~50 req/min/user)
            reset = r.headers.get("X-RateLimit-Reset")
            wait = max(5, int(float(reset) - time.time()) + 1) if reset else 30
            print(f"  rate limited, sleeping {wait}s"); time.sleep(wait); continue
        r.raise_for_status()
        return r.content if raw else r.json()

def safe(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", (name or "Untitled")).strip(" .")
    return name[:120] or "Untitled"

def ts(usec):
    return datetime.datetime.fromtimestamp(usec / 1e6).isoformat(timespec="seconds") if usec else ""

def existing_id(md_path):
    """quip_id from the front matter of an already-exported .md, or None."""
    try:
        with open(md_path, encoding="utf-8") as f:
            m = re.search(r"^quip_id: (\S+)", f.read(2000), re.M)
        return m.group(1) if m else None
    except OSError:
        return None

def pick_base(folder_dir, title, tid):
    """Choose <folder>/<Title>, adding ' (2)', ' (3)', ... when a *different* thread
    already owns that name. Returns (base, already_exported)."""
    stem, n = safe(title), 1
    while True:
        base = os.path.join(folder_dir, stem if n == 1 else f"{stem} ({n})")
        if not os.path.exists(base + ".md"):
            return base, False
        if existing_id(base + ".md") == tid:
            return base, True
        n += 1

seen_threads, seen_folders = set(), set()
log = []

def export_thread(tid, folder_dir):
    if tid in seen_threads: return
    seen_threads.add(tid)
    data = get(f"/1/threads/{tid}")
    t = data["thread"]
    kind = t.get("type", "document")
    if kind == "chat":                       # 1:1 / group chats, not docs
        return
    base, done = pick_base(folder_dir, t.get("title"), tid)
    if done:                                 # resume support
        print(f"  skip  {t.get('title')}"); return
    html = data.get("html", "") or ""
    os.makedirs(folder_dir, exist_ok=True)

    # pull embedded images/files, rewrite links to local paths
    assets = os.path.join(folder_dir, "_assets")
    def grab(m):
        b_tid, blob = m.group(1), m.group(2)
        try:
            content = get(f"/1/blob/{b_tid}/{blob}", raw=True)
        except Exception as e:
            print(f"    blob failed {blob}: {e}"); return m.group(0)
        os.makedirs(assets, exist_ok=True)
        with open(os.path.join(assets, blob), "wb") as f: f.write(content)
        return f"_assets/{blob}"
    html = re.sub(r"/blob/([A-Za-z0-9]+)/([A-Za-z0-9_\-]+)", grab, html)

    with open(base + ".html", "w", encoding="utf-8") as f: f.write(html)

    if kind == "spreadsheet":
        try:
            with open(base + ".xlsx", "wb") as f: f.write(get(f"/1/threads/{tid}/export/xlsx", raw=True))
        except Exception as e:
            print(f"    xlsx export failed: {e}")

    front = (f"---\ntitle: {json.dumps(t.get('title') or 'Untitled')}\n"
             f"quip_id: {tid}\nquip_link: {t.get('link','')}\ntype: {kind}\n"
             f"created: {ts(t.get('created_usec'))}\nupdated: {ts(t.get('updated_usec'))}\n---\n\n")
    body = md(html, heading_style="ATX", bullets="-")
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    with open(base + ".md", "w", encoding="utf-8") as f: f.write(front + body)
    log.append({"id": tid, "title": t.get("title"), "type": kind, "path": os.path.relpath(base, OUT)})
    print(f"  ok    {t.get('title')}  [{kind}]")

def walk(fid, parent_dir):
    if fid in seen_folders: return
    seen_folders.add(fid)
    try:
        data = get(f"/1/folders/{fid}")
    except requests.HTTPError as e:
        print(f"folder {fid} unreadable: {e}"); return
    d = os.path.join(parent_dir, safe(data["folder"].get("title")))
    print(f"[{os.path.relpath(d, OUT)}]")
    for child in data.get("children", []):
        if "thread_id" in child:
            try: export_thread(child["thread_id"], d)
            except Exception as e: print(f"  FAIL  {child['thread_id']}: {e}")
        elif "folder_id" in child:
            walk(child["folder_id"], d)

me = get("/1/users/current")
print(f"Exporting for {me.get('name')} -> {OUT}")
roots = [me.get(k) for k in ("private_folder_id", "desktop_folder_id", "starred_folder_id", "archive_folder_id")]
roots += me.get("shared_folder_ids", []) + me.get("group_folder_ids", [])
for fid in filter(None, roots):
    walk(fid, OUT)

# Sweep threads that live outside any folder (e.g. shared directly with you)
print("[Unfiled]")
cursor = None
while True:
    params = {"count": 50}
    if cursor: params["max_updated_usec"] = cursor
    batch = get("/1/threads/recent", **params)
    if not batch: break
    for tid, d in batch.items():
        try: export_thread(tid, os.path.join(OUT, "_Unfiled"))
        except Exception as e: print(f"  FAIL  {tid}: {e}")
    oldest = min(d["thread"]["updated_usec"] for d in batch.values())
    if cursor == oldest - 1 or len(batch) < 50: break
    cursor = oldest - 1

with open(os.path.join(OUT, "_index.json"), "w") as f: json.dump(log, f, indent=2)
print(f"\nDone: {len(log)} threads exported to {OUT}")
