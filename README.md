# MonPitor

A Raspberry Pi 3 display for [overnight-runs](https://github.com/eatonlambert-Slasonics/overnight-runs).
It shows the live log of whichever overnight run you pick, or a finished run's report, on
the Pi's HDMI screen. It can also take over the screen as a wireless screen-cast receiver.

## What it shows

You pick what to show through the overnight-runs skill, which writes one line to
`monitor/target` in the overnight-runs repo:

| `monitor/target` | Screen |
|---|---|
| `auto` | the live log of whichever machine is running; if none, the newest report |
| `gigbuddy` | the live log of the machine that runs gigbuddy (from `prompts/gigbuddy/project.conf`). If that machine isn't running, gigbuddy's last report |
| `host:tbot` | tbot's live log |
| `gigbuddy@latest` | gigbuddy's newest finished report |
| `gigbuddy@tbot-20261126-020000` | one specific report folder |

The Pi keeps its own clone of overnight-runs and checks it with `git ls-remote` every
5 seconds, so a new pick shows within about 5 to 10 seconds.

- **Live** logs come from `ssh <machine> tail -F ~/overnight-runs/run.log`. Lines from
  Claude Code's `--output-format stream-json` are shown as readable text and tool calls.
- **Finished** runs are read from `reports/` in the clone, so the machine that ran them can be off.

Lines are colour-coded by type (Claude's notes, tool calls, errors, finished runs). The
HDMI console uses a large Terminus font, set by `font` under `[display]` in
`monpitor.toml`. The web view has A−/A+ buttons for text size.

The same view is at `http://monpitor.local:8080/` in any browser.

## Screen casting

Open `https://monpitor.local:8443/cast` on a laptop, accept the self-signed certificate
once, and press **Cast screen**. The Pi shows that screen full screen until you stop,
then goes back to the logs. Browsers only allow screen capture over HTTPS, which is why
the cast page has its own port.

The Pi 3 decodes WebRTC video in software, so expect about 720p at a modest frame rate.
Lower `cast.max_width` in `monpitor.toml` if it stutters.

## Setup on the Pi

Works on Raspberry Pi OS 64-bit, Lite or desktop (tested on Debian 13 trixie).

On the **desktop** image, the HDMI screen shows the desktop, not tty1, and the
desktop holds the display, so cast mode can't draw either. Boot to the text
console instead, so MonPitor owns the screen:

```bash
sudo systemctl set-default multi-user.target && sudo reboot
```

(`sudo systemctl set-default graphical.target` brings the desktop back.)
On Tailscale, use the MagicDNS names in `monpitor.toml`, e.g. `ssh = "eaton-lambert@blackbox"`.

```bash
git clone https://github.com/eatonlambert-Slasonics/monpitor.git
cd monpitor
bash deploy/install.sh
```

The script installs packages, a Python venv, an ssh key, a self-signed certificate
and a systemd service that owns the HDMI console (tty1). Then:

1. Add the printed public key to `~/.ssh/authorized_keys` on each machine you want live
   logs from, and as a read-only deploy key on the overnight-runs repo.
2. Fill in the ssh addresses in `monpitor.toml`.
3. `sudo systemctl start monpitor`. Logs: `journalctl -u monpitor -f`.

## Development

```bash
pip install -r requirements.txt
python server.py --config monpitor.toml --no-console   # web view only
python -m unittest discover -s tests -t .
```

Layout: `server.py` (web server and wiring), `monpitor/target.py` (what to show),
`monpitor/logsource.py` (ssh tail, reports, stream-json formatting),
`monpitor/console.py` (HDMI console), `monpitor/cast.py` (WebRTC receiver to mpv).
