import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("record_simulator_video.sh")


class RecordingTests(unittest.TestCase):
    def test_invalid_durations_do_not_start_recorder(self):
        for value in ("0", "301", "-1", "no"):
            with self.subTest(value=value):
                result = subprocess.run(
                    ["bash", str(SCRIPT), "device", "/tmp/unused-video.mp4", value],
                    capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 2)

    def test_interrupt_finalizes_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = root / "xcrun"
            mock.write_text(
                f"#!{sys.executable}\n"
                "import signal,sys\n"
                "from pathlib import Path\n"
                "output=Path(sys.argv[-1])\n"
                "def finish(*args):\n"
                " output.write_bytes(b'mocked-finalized-video')\n"
                " sys.exit(0)\n"
                "signal.signal(signal.SIGINT,finish)\n"
                "signal.signal(signal.SIGTERM,finish)\n"
                "while True: signal.pause()\n")
            mock.chmod(0o755)
            output = root / "recording.mp4"
            result = subprocess.run(
                ["bash", str(SCRIPT), "device", str(output), "1"],
                env={"PATH": str(root) + ":" + os.environ["PATH"]},
                capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), b"mocked-finalized-video")


if __name__ == "__main__":
    unittest.main()
