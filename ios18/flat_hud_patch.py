"""Stop backdrop sampling behind the live statistics without hiding readings."""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / "Andarium/Andarium/Shared/Stats.swift"
text = path.read_text()
old = ".andariumGlassEffect(.regular, in: .capsule)"
if text.count(old) != 1:
    raise SystemExit("Expected the single stats capsule after compatibility patch")
path.write_text(text.replace(old, ".background(Color(uiColor: .secondarySystemBackground), in: Capsule())"))
