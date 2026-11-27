#!/bin/sh
# Sets the HDMI console (tty1) font from `font = "..."` under [display] in monpitor.toml.
# Run as root by the service before MonPitor starts. Fonts: ls /usr/share/consolefonts
CONF="${1:-monpitor.toml}"
FONT="$(sed -n '/^\[display\]/,/^\[/{s/^[[:space:]]*font[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p}' "$CONF" 2>/dev/null | head -n 1)"
FONT="${FONT:-Uni2-TerminusBold32x16}"
[ "$FONT" = "default" ] && exit 0
setfont -C /dev/tty1 "$FONT" || echo "monpitor: could not load console font $FONT" >&2
exit 0
