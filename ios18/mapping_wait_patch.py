#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Experiment: park contended mapping-lock waiters after a short spin.

FIX9 yields up to 4032 times, then sleeps 100 us per retry. A descheduled
holder can turn this into a convoy. C++20 atomic wait lets Darwin wake
waiters when the last reader or writer actually releases the word.
The admission/ordering rules are unchanged. UML_MAPPING_WAIT=0 selects
the original algorithm for same-binary comparisons. Not shipped by default.
"""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / "darwin/memory/mmu/word_shared_mutex.hpp"
text = path.read_text()


def replace(old, new, count=1):
    global text
    if text.count(old) != count:
        raise SystemExit(f"mapping wait: expected {count} matches: {old[:70]!r}")
    text = text.replace(old, new)


replace("#include <cstdint>\n", "#include <cstdint>\n#include <cstdlib>\n")
replace("wait(attempt);", "wait(attempt, state);", 2)
replace("state_.fetch_and(~writer, std::memory_order_release);",
        """state_.fetch_and(~writer, std::memory_order_release);
if (parking_enabled())
state_.notify_all();""")
replace("state_.fetch_sub(reader, std::memory_order_release);",
        """const auto previous = state_.fetch_sub(reader, std::memory_order_release);
if (parking_enabled() && (previous & pending) != 0 &&
    (previous & ~(writer | pending)) == reader)
state_.notify_all();""")
replace("static void wait(unsigned attempt) noexcept",
        """static bool parking_enabled() noexcept
{
static const bool enabled = [] {
const char *setting = std::getenv("UML_MAPPING_WAIT");
return setting != nullptr && setting[0] == '1';
}();
return enabled;
}

void wait(unsigned attempt, std::uint64_t observed) noexcept""")
replace("if (attempt < 4096) {",
        """if (parking_enabled()) {
state_.wait(observed, std::memory_order_relaxed);
return;
}
if (attempt < 4096) {""")
path.write_text(text)
print("mapping wait experiment installed (opt in: UML_MAPPING_WAIT=1)")
