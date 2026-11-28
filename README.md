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

**How fresh is it?** Live lines arrive the moment they are written (ssh `tail -F`, no
polling), and the newest line is always at the bottom of the HDMI screen. Every line has
a time column:

- ` 11:31:41` when the line was written: its own time for progress.py lines, else when it reached the Pi.
- `~01:02:10` an estimate, for lines written before MonPitor connected (or while ssh was
  down) that carry no time of their own: it is the last time seen above them.
- A `──── live from 11:31:38` line marks where replayed history ends and live lines begin.

Under the title, `last line 11:31:41, 3m ago` says when the log last got a line. It turns
yellow after 10 minutes of silence. If ssh drops, MonPitor resumes where it stopped, so
lines are neither repeated nor lost. The Pi's time zone should match the build
machine's, since progress.py times are the build machine's local time
(`sudo timedatectl set-timezone America/Los_Angeles`).

In the web view, scrolling up to read pauses following; **Jump to latest** (or a minute
without scrolling) goes back to the newest line.

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
