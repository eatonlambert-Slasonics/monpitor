import os
import tempfile
import unittest

from monpitor.logsource import format_line
from monpitor.target import parse_target, resolve


def write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class FakeRepo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        write(self.root, "prompts/gigbuddy/project.conf", "host=tbot\ndir=~/gigbuddy\n")
        write(self.root, "prompts/bundledessentials/project.conf", "dir=~/workspace/BundledEssentials\n")
        write(self.root, "STATUS.md", "# Finished\nUpdated: x\n")
        write(self.root, "STATUS-tbot.md", "# Running\nRunning: gigbuddy/03-x\n")
        write(self.root, "reports/tbot-20261125-020000/gigbuddy__02-old.md", "old")
        write(self.root, "reports/tbot-20261126-020000/gigbuddy__03-new.md", "new")
        write(self.root, "reports/tbot-20261126-020000/BLOCKED", "why")
        write(self.root, "reports/20261126-010000/bundledessentials__01-a.md", "a")


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()
        self.root = self.repo.root

    def tearDown(self):
        self.repo.tmp.cleanup()

    def test_parse(self):
        self.assertEqual(parse_target(""), ("auto", "", ""))
        self.assertEqual(parse_target("# c\ngigbuddy\n"), ("project", "gigbuddy", ""))
        self.assertEqual(parse_target("host:TBOT"), ("host", "tbot", ""))
        self.assertEqual(parse_target("gigbuddy@latest"), ("report", "gigbuddy", "latest"))
        self.assertEqual(parse_target("gigbuddy@"), ("report", "gigbuddy", "latest"))

    def test_project_live_when_host_running(self):
        v = resolve(self.root, "gigbuddy")
        self.assertEqual((v.kind, v.host), ("live", "tbot"))

    def test_project_falls_back_to_report_when_idle(self):
        v = resolve(self.root, "bundledessentials")
        self.assertEqual(v.kind, "report")
        self.assertEqual(v.files, ["bundledessentials__01-a.md"])

    def test_latest_report(self):
        v = resolve(self.root, "gigbuddy@latest")
        self.assertEqual(os.path.basename(v.report_dir), "tbot-20261126-020000")
        self.assertEqual(v.files, ["BLOCKED", "gigbuddy__03-new.md"])

    def test_named_report(self):
        v = resolve(self.root, "gigbuddy@tbot-20261125-020000")
        self.assertEqual(v.files, ["gigbuddy__02-old.md"])
        self.assertEqual(v.host, "tbot")

    def test_auto_follows_running_host(self):
        self.assertEqual(resolve(self.root, "auto").host, "tbot")
        write(self.root, "STATUS-tbot.md", "# Done\n")
        v = resolve(self.root, "auto")
        self.assertEqual(v.kind, "report")
        self.assertEqual(os.path.basename(v.report_dir), "tbot-20261126-020000")

    def test_unknown_project(self):
        self.assertEqual(resolve(self.root, "nope").kind, "empty")


class FormatTests(unittest.TestCase):
    def test_plain_and_ansi(self):
        self.assertEqual(format_line("\x1b[32mok\x1b[0m\n"), ["ok"])

    def test_stream_json(self):
        line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi\\nthere"},' \
               '{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}'
        self.assertEqual(format_line(line), ["hi", "there", "  > Bash ls"])
        self.assertEqual(format_line('{"type":"rate_limit"}'), [])


class CastTests(unittest.TestCase):
    def test_scaling_and_bytes(self):
        try:
            import av
        except ImportError:
            self.skipTest("av not installed")
        from monpitor.cast import frame_bytes, scaled_size
        self.assertEqual(scaled_size(1920, 1080, 1280), (1280, 720))
        self.assertEqual(scaled_size(1001, 601, 1280), (1000, 600))
        frame = av.VideoFrame(1920, 1080, "yuv420p").reformat(width=1278, height=718)
        self.assertEqual(len(frame_bytes(frame)), 1278 * 718 * 3 // 2)


if __name__ == "__main__":
    unittest.main()
