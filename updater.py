"""Keeps the bot on the newest commit of its GitHub repo.

The hosting panel only runs `git pull` when the server folder is a git checkout,
and this one was uploaded by hand, so the bot updates itself: it reads the
branch's newest commit from GitHub, downloads that commit as a zip and writes
every file that changed. Local files (.env, keys, logs, saved lists) are never
touched, and a git checkout (a developer's PC) is left alone. After an update
the bot restarts itself so the new code runs.

main.py checks once at start; cogs/autoupdate.py checks every few minutes.
"""

import io
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".bot_update.json"
# Files that belong to this server, never replaced or removed by an update.
KEEP = {
    ".env", ".passkey_ok", ".coldd_key", ".bot_update.json",
    "bot.log", "remindlist.json", "ping_on_join.json",
}

log = logging.getLogger("updater")


def settings() -> dict:
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("auto_update") or {}
    except Exception:
        cfg = {}
    return {
        "enabled": cfg.get("enabled", True) is not False,
        "repo": str(cfg.get("repo") or "VxpeInjected/coldd-dc-bot"),
        "branch": str(cfg.get("branch") or "main"),
        "check_minutes": max(1, int(cfg.get("check_minutes") or 2)),
    }


def is_git_checkout() -> bool:
    return (ROOT / ".git").exists()


def _get(url: str, timeout: int, agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def remote_commit(repo: str, branch: str) -> str | None:
    # Git's own ref list: no API rate limit, unlike api.github.com.
    data = _get(f"https://github.com/{repo}.git/info/refs?service=git-upload-pack", 20, "git/2.45.0 coldd-dc-bot")
    match = re.search(rb"([0-9a-f]{40}) refs/heads/" + re.escape(branch.encode()) + rb"[\x00\n]", data)
    return match.group(1).decode() if match else None


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _apply(repo: str, commit: str) -> tuple[list[str], list[str]]:
    archive = zipfile.ZipFile(io.BytesIO(_get(f"https://codeload.github.com/{repo}/zip/{commit}", 60, "coldd-dc-bot-updater")))
    files: dict[str, bytes] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = info.filename.split("/", 1)
        if len(parts) < 2 or not parts[1]:
            continue
        rel = parts[1]
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or rel in KEEP:
            continue
        files[rel] = archive.read(info)
    if "main.py" not in files:
        raise RuntimeError("the download has no main.py")

    changed: list[str] = []
    for rel, data in files.items():
        dest = ROOT / rel
        if dest.is_file() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".tmp-update")
        temp.write_bytes(data)
        os.replace(temp, dest)
        changed.append(rel)

    # Only files an earlier update wrote are removed when the repo drops them.
    removed: list[str] = []
    for rel in set(_load_state().get("files") or []) - set(files):
        dest = ROOT / rel
        if rel not in KEEP and dest.is_file():
            dest.unlink()
            removed.append(rel)

    _save_state({"commit": commit, "files": sorted(files)})
    return changed, removed


def _install_requirements() -> None:
    command = [sys.executable, "-m", "pip", "install", "-U", "-r", str(ROOT / "requirements.txt")]
    if (ROOT / ".local").is_dir():
        command[5:5] = ["--prefix", str(ROOT / ".local")]
    print("[UPDATER] requirements.txt changed, installing packages...", flush=True)
    subprocess.run(command, cwd=ROOT, check=False)


def check_and_update() -> bool:
    """Returns True when new code was written and the bot should restart."""
    cfg = settings()
    if not cfg["enabled"] or is_git_checkout():
        return False
    commit = remote_commit(cfg["repo"], cfg["branch"])
    if not commit or _load_state().get("commit") == commit:
        return False
    changed, removed = _apply(cfg["repo"], commit)
    if "requirements.txt" in changed:
        _install_requirements()
    if changed or removed:
        print(f"[UPDATER] Updated to {commit[:7]}: {len(changed)} file(s) changed, {len(removed)} removed.", flush=True)
        log.info("updated to %s: changed %s, removed %s", commit, changed, removed)
        return True
    print(f"[UPDATER] Files already match {commit[:7]}.", flush=True)
    return False


def check_at_start() -> None:
    """Runs before the bot starts; a failed check never stops the bot."""
    try:
        if check_and_update():
            restart()
        elif not is_git_checkout() and settings()["enabled"]:
            commit = _load_state().get("commit")
            print(f"[UPDATER] Up to date ({commit[:7] if commit else 'unknown'}).", flush=True)
    except Exception as error:
        print(f"[UPDATER] Could not check for updates: {error}", flush=True)
        log.warning("update check failed", exc_info=True)


def restart() -> None:
    print("[UPDATER] Restarting to run the new code...", flush=True)
    logging.shutdown()
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable] + sys.argv)
