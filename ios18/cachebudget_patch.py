#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measurement aid: state the translated-code cache budget and report its use.

UML_GADGET_CACHE_BUDGET_MIB=<n> replaces the derived budget, so a Mac run can
hold the budget an iPad derives. Once a minute the engine writes the budget,
the bytes held, the peak, and how often the budget made address spaces drop
their translations ("reliefs", "shed").

Usage: cachebudget_patch.py <upstream root>
"""
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "darwin/runtime/context.cpp"
text = path.read_text()
old = """\tbytes = gadget_cache_budget_for(guest_memory_bytes, bytes, executors);
\t::uml::cpu::gadget_cache::set_budget(bytes);
\treturn bytes;
"""
new = """bytes = gadget_cache_budget_for(guest_memory_bytes, bytes, executors);
if (const char *stated = std::getenv("UML_GADGET_CACHE_BUDGET_MIB");
    stated != nullptr && std::atoi(stated) > 0)
bytes = static_cast<std::size_t>(std::atoi(stated)) << 20;
::uml::cpu::gadget_cache::set_budget(bytes);
std::fprintf(stderr, "gadget cache budget: %zu MiB at %u processors\\n",
bytes >> 20, executors);
std::thread([] {
for (;;) {
std::this_thread::sleep_for(std::chrono::seconds(60));
const auto book = ::uml::cpu::gadget_cache::ledger_state();
std::fprintf(stderr,
"gadget cache use: budget %zu MiB, held %zu MiB, shedding %zu MiB, "
"peak %zu MiB, reliefs %llu, shed %llu\\n",
book.budget >> 20, book.total >> 20, book.shedding >> 20,
book.peak_open >> 20,
static_cast<unsigned long long>(book.reliefs),
static_cast<unsigned long long>(book.shed_accounts));
}
}).detach();
return bytes;
"""
if text.count(old) != 1:
    raise SystemExit("context.cpp: budget setter not found")
text = text.replace(old, new)
inc = "#include <algorithm>\n"
if text.count(inc) != 1:
    raise SystemExit("context.cpp: include anchor not found")
text = text.replace(inc, inc + "#include <chrono>\n#include <cstdio>\n#include <cstdlib>\n")
path.write_text(text)
print("cache budget override and report added")
