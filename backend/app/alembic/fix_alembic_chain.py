# fix_alembic_chain.py
import re, sys, pathlib, datetime

PAT_REV = re.compile(r'^\s*revision\s*=\s*["\']([^"\']+)["\']', re.M)
PAT_DOWN = re.compile(r'^\s*down_revision\s*=\s*(None|["\']([^"\']+)["\'])', re.M)
PAT_CREATE = re.compile(r'Create Date:\s*(.+)')

def parse_create_date(text):
    m = PAT_CREATE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # Try a couple formats; default to file mtime if parse fails
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None

def main(versions_dir: pathlib.Path, apply=True):
    files = sorted(versions_dir.glob("*.py"))
    if not files:
        print("No migration files found.")
        return 1

    # Load and extract metadata
    metas = []
    for f in files:
        txt = f.read_text(encoding="utf-8")
        rev = PAT_REV.search(txt)
        down = PAT_DOWN.search(txt)
        created = parse_create_date(txt)
        if not created:
            # fallback: file modified time
            created = datetime.datetime.fromtimestamp(f.stat().st_mtime)
        metas.append({
            "path": f,
            "text": txt,
            "revision": rev.group(1) if rev else None,
            "down_revision": (None if (down and down.group(1) == "None") else (down.group(2) if down else None)),
            "created": created,
            "has_placeholder": (down and (down.group(1) != "None") and ("PUT_PREVIOUS_REVISION_ID_HERE" in down.group(0)))
        })

    # Sort by Create Date (oldest -> newest)
    metas.sort(key=lambda x: x["created"])

    # Build linear chain by date
    changes = []
    prev_rev = None
    for i, m in enumerate(metas):
        if not m["revision"]:
            print(f"ERROR: {m['path'].name} has no 'revision =' line. Aborting.")
            return 2

        desired_down = None if i == 0 else prev_rev
        prev_rev = m["revision"]

        # Only change if placeholder present or wrong down_revision
        if m["down_revision"] != desired_down:
            reason = "placeholder" if m["has_placeholder"] else "mismatch"
            changes.append((m, desired_down, reason))

    # Show plan
    print("Plan:")
    for m, new_down, why in changes:
        print(f"  - {m['path'].name}: set down_revision -> {repr(new_down)} ({why})")

    if not apply:
        print("\nDry run complete. Re-run with apply=True.")
        return 0

    # Apply changes in-place
    for m, new_down, _ in changes:
        new_text = m["text"]
        if PAT_DOWN.search(new_text):
            repl = f'down_revision = {("None" if new_down is None else repr(new_down))}'
            new_text = PAT_DOWN.sub(repl, new_text, count=1)
        else:
            # Insert right after revision =
            ins_repl = f'revision = "{m["revision"]}"\ndown_revision = {("None" if new_down is None else repr(new_down))}'
            new_text = PAT_REV.sub(ins_repl, new_text, count=1)
        m["path"].write_text(new_text, encoding="utf-8")

    print("\nApplied.")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_alembic_chain.py <path-to-alembic/versions>")
        sys.exit(1)
    versions = pathlib.Path(sys.argv[1]).resolve()
    sys.exit(main(versions, apply=True))
