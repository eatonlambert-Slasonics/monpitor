import asyncio
import os
import tempfile
import time
import unittest

from monpitor.console import ConsoleRenderer
from monpitor.logsource import Line, LineBuffer, LiveTail, own_time, tail_command
from monpitor.style import age_text, stamped


class Host:
    name = "blackbox"
    ssh = "x"
    log = ""


class OwnTimeTest(unittest.TestCase):
    def test_progress_and_runner_lines(self):
        self.assertEqual(own_time("[14:05:25]   proj/run | Bash: ls"), "14:05:25")
        self.assertEqual(own_time("[Thu Nov 26 02:05:40 PM PST 2026] proj/run finished, exit 0"), "14:05:40")
        self.assertEqual(own_time("[Thu Nov 26 12:01:02 AM PST 2026] x"), "00:01:02")
        self.assertEqual(own_time("[Thu Nov 26 22:01:02 PST 2026] x"), "22:01:02")
        self.assertIsNone(own_time("plain text"))


class StampTest(unittest.TestCase):
    def test_time_column(self):
        self.assertEqual(stamped(Line("hello", "11:00:00"))[0], (" 11:00:00 ", "time"))
        self.assertEqual(stamped(Line("hello", "11:00:00", True))[0], ("~11:00:00 ", "time"))
        self.assertEqual(stamped(Line("hello", None, True))[0], ("~--:--:-- ", "time"))
        self.assertEqual(stamped(Line("# report heading")), [("# report heading", "heading")])

    def test_progress_time_not_shown_twice(self):
        text = "".join(p for p, _ in stamped(Line("[14:05:25]   proj/run | Bash: ls", "14:05:25")))
        self.assertEqual(text.count("14:05:25"), 1)
        self.assertTrue(text.startswith(" 14:05:25 "))

    def test_age_text(self):
        self.assertEqual(age_text(8), "8s")
        self.assertEqual(age_text(240), "4m")
        self.assertEqual(age_text(2 * 3600 + 5 * 60), "2h 05m")
        self.assertEqual(age_text(3 * 86400 + 4 * 3600), "3d 4h")


class BufferTest(unittest.TestCase):
    def test_backlog_carries_last_time_and_live_uses_arrival(self):
        b = LineBuffer(100)
        b.add("before any time", backlog=True)
        b.add("[09:00:00]   p/r | says: hi", backlog=True)
        b.add("plain backlog", backlog=True)
        self.assertIsNone(b.activity)
        now = time.time()
        b.add("live line", when=now)
        got = [(l.clock, l.approx) for l in b.lines]
        self.assertEqual(got[:3], [(None, True), ("09:00:00", False), ("09:00:00", True)])
        self.assertEqual(got[3], (time.strftime("%H:%M:%S", time.localtime(now)), False))
        self.assertEqual(b.activity, now)


class FeedTest(unittest.TestCase):
    def test_header_backlog_live_and_resume(self):
        b = LineBuffer(100)
        t = LiveTail(Host(), b, lambda s: None)
        rnow = 1_000_000
        phase = t.feed(f"@@monpitor 20 {rnow - 3600} {rnow}\n".encode(), "start")
        self.assertAlmostEqual(b.activity, time.time() - 3600, delta=2)  # an hour ago, by the remote clock
        phase = t.feed(b"old line\n", phase)
        phase = t.feed(b"@@monpitor-live 20\n", phase)
        self.assertEqual(phase, "live")
        t.feed(b"new\n", phase)
        self.assertEqual(t.offset, 24)
        self.assertFalse(b.lines[-1].approx)
        self.assertAlmostEqual(b.activity, time.time(), delta=2)
        # Reconnect: 6 bytes were written while away, then a live line.
        phase = t.feed(f"@@monpitor 30 {rnow} {rnow}\n".encode(), "start")
        phase = t.feed(b"@@monpitor-live 24\n", phase)
        t.feed(b"away\n", phase)
        self.assertTrue(b.lines[-1].approx)
        t.feed(b"x\n", phase)  # offset is now 30
        t.feed(b"back\n", phase)
        self.assertFalse(b.lines[-1].approx)
        self.assertEqual([l.text for l in b.lines if not l.text.startswith("────")],
                         ["old line", "new", "away", "x", "back"])


class TailScriptTest(unittest.TestCase):
    """Runs the real script with sh (no ssh) against a temp log."""

    def run_script(self, path, offset, append=b""):
        async def go():
            proc = await asyncio.create_subprocess_exec(
                "sh", "-c", tail_command(path, offset, backlog=2), stdout=asyncio.subprocess.PIPE)
            out = []
            async def read():
                async for raw in proc.stdout:
                    out.append(raw.decode())
            reader = asyncio.create_task(read())
            await asyncio.sleep(0.5)
            if append:
                with open(path, "ab") as f:
                    f.write(append)
                await asyncio.sleep(1.5)
            proc.kill()
            await proc.wait()
            await asyncio.wait_for(reader, 2)
            return out
        return asyncio.run(go())

    def test_backlog_then_live(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "run.log")
            with open(path, "wb") as f:
                f.write(b"a\nb\nc\n")
            out = self.run_script(path, 0, append=b"d\n")
            self.assertTrue(out[0].startswith("@@monpitor 6 "))
            self.assertEqual(out[1:], ["b\n", "c\n", "@@monpitor-live 6\n", "d\n"])
            out = self.run_script(path, 4)  # resume after "a\nb\n"
            self.assertEqual(out[1:], ["@@monpitor-live 4\n", "c\n", "d\n"])

    def test_missing_log(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.run_script(os.path.join(d, "none.log"), 0)
            self.assertEqual(out, ["@@monpitor 0 0 " + out[0].split()[3] + "\n", "@@monpitor-live 0\n"])


class ConsoleTest(unittest.TestCase):
    def test_freshness_line_and_newest_at_bottom(self):
        b = LineBuffer(100)
        for i in range(50):
            b.add(f"line {i}", when=time.time() - 900)
        c = ConsoleRenderer("/nonexistent", b)
        c.set_view("bundledessentials", "", live=True)
        text, quiet = c.freshness()
        self.assertIn("15m ago", text)
        self.assertTrue(quiet)
        r, w = os.pipe()
        c.fd = w
        c.size = lambda: (80, 10)
        c.draw()
        os.close(w)
        screen = os.read(r, 100000).decode()
        os.close(r)
        self.assertIn("line 49", screen)
        self.assertNotIn("line 40", screen)
        self.assertIn("15m ago", screen)


if __name__ == "__main__":
    unittest.main()
