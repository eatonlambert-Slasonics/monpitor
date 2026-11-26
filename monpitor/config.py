"""Loads monpitor.toml and fills in defaults."""

import os
import tomllib
from dataclasses import dataclass, field


@dataclass
class HostConfig:
    """How to reach one overnight-runs machine.

    Attributes:
        name: Host name as used in overnight-runs (blackbox, tbot, whitebox).
        ssh: ssh destination, e.g. "eaton-lambert@blackbox.local". Empty disables live tail.
        log: Path of the runner log on that machine.
    """

    name: str
    ssh: str = ""
    log: str = "~/overnight-runs/run.log"


@dataclass
class Config:
    """All MonPitor settings."""

    repo_url: str = "git@github.com:eatonlambert-Slasonics/overnight-runs.git"
    checkout: str = "~/overnight-runs"
    branch: str = "main"
    poll_seconds: float = 5.0
    hosts: dict = field(default_factory=dict)
    console: bool = True
    tty: str = "/dev/tty1"
    cast_enabled: bool = True
    cast_player: str = "mpv"
    cast_max_width: int = 1280
    buffer_lines: int = 2000

    @property
    def checkout_path(self):
        return os.path.expanduser(self.checkout)


DEFAULT_HOSTS = ("blackbox", "tbot", "whitebox")


def load(path):
    """Read a TOML config file; a missing file gives defaults.

    Args:
        path: Path to monpitor.toml.

    Returns:
        Config with every host in DEFAULT_HOSTS present.
    """
    data = {}
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            data = tomllib.load(f)

    ov = data.get("overnight", {})
    disp = data.get("display", {})
    cast = data.get("cast", {})
    cfg = Config(
        repo_url=ov.get("repo_url", Config.repo_url),
        checkout=ov.get("checkout", Config.checkout),
        branch=ov.get("branch", Config.branch),
        poll_seconds=float(ov.get("poll_seconds", Config.poll_seconds)),
        console=bool(disp.get("console", True)),
        tty=disp.get("tty", Config.tty),
        buffer_lines=int(disp.get("buffer_lines", Config.buffer_lines)),
        cast_enabled=bool(cast.get("enabled", True)),
        cast_player=cast.get("player", Config.cast_player),
        cast_max_width=int(cast.get("max_width", Config.cast_max_width)),
    )
    hosts = data.get("hosts", {})
    for name in set(DEFAULT_HOSTS) | set(hosts):
        h = hosts.get(name, {})
        cfg.hosts[name] = HostConfig(name=name, ssh=h.get("ssh", ""), log=h.get("log", HostConfig.log))
    return cfg
