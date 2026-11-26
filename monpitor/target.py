"""Works out what to show from the overnight-runs repo.

The overnight-runs skill writes one line to ``monitor/target`` in that repo:

    auto                  follow whichever host is running; else the newest report
    <project>             live log of the host that runs <project>
    host:<host>           live log of one host
    <project>@latest      newest finished report for <project>
    <project>@<folder>    one report folder, e.g. gigbuddy@tbot-20261126-020000

The Pi keeps a clone of the repo and checks it with ``git ls-remote`` every few
seconds, so a new target shows within about one poll interval.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("monpitor.target")

TARGET_FILE = os.path.join("monitor", "target")
STATUS_FILES = {"blackbox": "STATUS.md", "tbot": "STATUS-tbot.md", "whitebox": "STATUS-whitebox.md"}
REPORT_PREFIX = {"blackbox": "", "tbot": "tbot-", "whitebox": "whitebox-"}
TS_RE = re.compile(r"(\d{8}-\d{6})$")
# Guess: STATUS files say "Running" while a pass is going. Checked case-insensitively.
RUNNING_RE = re.compile(r"\brunning\b", re.I)
FINISHED_RE = re.compile(r"\b(finished|done|blocked|stopped|idle)\b", re.I)


@dataclass
class View:
    """What the screen should show right now.

    Attributes:
        kind: "live", "report" or "empty".
        title: Header line.
        host: Host to tail when kind is "live".
        project: Project name, if any.
        report_dir: Absolute report folder when kind is "report".
        files: Report files to show, in order.
        note: Extra line under the title (status, reason for fallback).
    """

    kind: str
    title: str
    host: str = ""
    project: str = ""
    report_dir: str = ""
    files: list = field(default_factory=list)
    note: str = ""

    def key(self):
        """Identity used to tell whether the view changed."""
        return (self.kind, self.host, self.project, self.report_dir, tuple(self.files))


def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def parse_target(text):
    """Turn the target file's text into (mode, name, report).

    Returns:
        ("auto", "", ""), ("host", host, ""), ("project", project, "") or
        ("report", project, "latest" | folder).
    """
    line = ""
    for raw in text.splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#"):
            line = raw
            break
    if not line or line.lower() == "auto":
        return ("auto", "", "")
    if line.lower().startswith("host:"):
        return ("host", line.split(":", 1)[1].strip().lower(), "")
    if "@" in line:
        project, report = line.split("@", 1)
        return ("report", project.strip(), report.strip() or "latest")
    return ("project", line, "")


def project_host(repo, project):
    """Host that runs a project, from prompts/<project>/project.conf (default blackbox)."""
    conf = read_text(os.path.join(repo, "prompts", project, "project.conf"), None)
    if conf is None:
        return None
    m = re.search(r"^\s*host\s*=\s*(\S+)", conf, re.M)
    return m.group(1).lower() if m else "blackbox"


def host_status(repo, host):
    """Return (is_running, first status line) for one host's STATUS file."""
    text = read_text(os.path.join(repo, STATUS_FILES.get(host, "")))
    first = next((l.strip("# ").strip() for l in text.splitlines() if l.strip()), "")
    head = "\n".join(text.splitlines()[:15])
    running = bool(RUNNING_RE.search(head)) and not FINISHED_RE.search(first)
    return running, first


def report_folders(repo, host=None):
    """Report folders, newest first: list of (timestamp, host, abs path)."""
    root = os.path.join(repo, "reports")
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        path = os.path.join(root, name)
        m = TS_RE.search(name)
        if not m or not os.path.isdir(path):
            continue
        prefix = name[: m.start()]
        h = next((k for k, v in REPORT_PREFIX.items() if v == prefix), None)
        if h is None or (host and h != host):
            continue
        out.append((m.group(1), h, path))
    out.sort(reverse=True)
    return out


def report_files(folder, project=None):
    """Readable files of a report folder, BLOCKED first. Filters to one project if given."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    files = [n for n in names if n == "BLOCKED"]
    for n in names:
        if not n.endswith(".md"):
            continue
        if project and not n.startswith(project + "__"):
            continue
        files.append(n)
    return files


def latest_report(repo, project=None, host=None):
    """Newest report folder that has something for the project (or anything)."""
    for _, h, path in report_folders(repo, host):
        files = report_files(path, project)
        if any(f != "BLOCKED" for f in files) or (not project and files):
            return h, path, files
    return None


def report_view(repo, project, folder_name, note=""):
    if folder_name == "latest":
        host = project_host(repo, project) if project else None
        found = latest_report(repo, project or None, host)
        if not found:
            return View("empty", f"{project}: no finished reports yet", project=project, note=note)
        host, path, files = found
    else:
        path = os.path.join(repo, "reports", folder_name)
        files = report_files(path, project or None) or report_files(path)
        host = next((k for k, v in REPORT_PREFIX.items() if v and folder_name.startswith(v)), "blackbox")
        if not files:
            return View("empty", f"Report {folder_name} not found", project=project, note=note)
    name = os.path.basename(path)
    title = f"{project or host} - finished run {name}"
    return View("report", title, host=host, project=project, report_dir=path, files=files, note=note)


def resolve(repo, text):
    """Decide the View for the current repo state and target text."""
    mode, name, report = parse_target(text)

    if mode == "report":
        return report_view(repo, name, report)

    if mode == "auto":
        for host in STATUS_FILES:
            running, first = host_status(repo, host)
            if running:
                return View("live", f"{host} - live", host=host, note=first)
        found = latest_report(repo)
        if found:
            return report_view(repo, "", os.path.basename(found[1]), note="Nothing running. Last report:")
        return View("empty", "Nothing running and no reports yet")

    if mode == "host":
        host = name
        project = ""
    else:
        project = name
        host = project_host(repo, project)
        if host is None:
            return View("empty", f"Unknown project '{project}'", note="No prompts/<project>/project.conf in overnight-runs")

    running, first = host_status(repo, host)
    if running or mode == "host":
        title = f"{project} on {host} - live" if project else f"{host} - live"
        return View("live", title, host=host, project=project, note=first)
    # The host is not running: show the finished run instead, as agreed.
    v = report_view(repo, project, "latest", note=f"{host} is not running ({first or 'no status'}). Last report:")
    if v.kind == "empty":
        return View("live", f"{project} on {host} - live", host=host, project=project, note=first)
    return v


class TargetWatcher:
    """Keeps the overnight-runs clone fresh and reports View changes."""

    def __init__(self, cfg, on_view):
        self.cfg = cfg
        self.on_view = on_view
        self.repo = cfg.checkout_path
        self.remote_head = None
        self.view = None
        self.error = ""

    async def git(self, *args):
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=self.repo if os.path.isdir(self.repo) else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {err.decode(errors='replace').strip()}")
        return out.decode().strip()

    async def ensure_clone(self):
        if os.path.isdir(os.path.join(self.repo, ".git")):
            return
        log.info("Cloning %s into %s", self.cfg.repo_url, self.repo)
        await self.git("clone", "--depth", "50", "-b", self.cfg.branch, self.cfg.repo_url, self.repo)

    async def refresh(self, force=False):
        """Pull if the remote moved, then recompute the view."""
        await self.ensure_clone()
        out = await self.git("ls-remote", "origin", f"refs/heads/{self.cfg.branch}")
        head = out.split()[0] if out else None
        if force or head != self.remote_head:
            await self.git("fetch", "--depth", "50", "origin", self.cfg.branch)
            await self.git("reset", "--hard", f"origin/{self.cfg.branch}")
            self.remote_head = head
        self.recompute()

    def recompute(self):
        text = read_text(os.path.join(self.repo, TARGET_FILE), "auto")
        view = resolve(self.repo, text)
        if self.view is None or view.key() != self.view.key() or view.note != self.view.note:
            self.view = view
            log.info("View: %s (%s)", view.title, view.kind)
            self.on_view(view)

    async def run(self):
        first = True
        while True:
            try:
                await self.refresh(force=first)
                first = False
                self.error = ""
            except Exception as e:  # network blips must not kill the display
                if str(e) != self.error:
                    log.warning("Repo check failed: %s", e)
                self.error = str(e)
                if self.view is None:
                    self.view = View("empty", "Waiting for the overnight-runs repo", note=str(e)[:200])
                    self.on_view(self.view)
            await asyncio.sleep(self.cfg.poll_seconds)
