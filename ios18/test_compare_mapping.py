import tempfile
import unittest
from pathlib import Path

from compare_mapping import frames


class FrameSummaryTests(unittest.TestCase):
    def test_rejects_flagged_incomplete_and_sentinel_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frames.txt"
            path.write_text(
                "---PROFILEDATA---\n"
                "Flags,IntendedVsync,IssueDrawCommandsStart,SwapBuffers,FrameCompleted,\n"
                "0,1000000,2000000,4000000,11000000,\n"
                "0,20000000,21000000,25000000,40000000,\n"
                "1,1,2,3,900000000,\n"
                "0,5000000,0,0,0,\n"
                "0,1,2,3,9223372036854775807,\n"
                "---PROFILEDATA---\n"
            )
            report = frames(path)
            self.assertEqual(report["count"], 2)
            self.assertEqual(report["median_ms"], 15)
            self.assertEqual(report["p90_ms"], 20)
            self.assertEqual(report["draw_median_ms"], 3)

    def test_missing_file_is_not_a_pass(self):
        self.assertEqual(frames(Path("/nonexistent/frames.txt")), {"count": 0})


if __name__ == "__main__":
    unittest.main()
