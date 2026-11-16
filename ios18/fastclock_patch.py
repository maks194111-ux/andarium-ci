#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Answer clock_gettime from the engine without a guest system call.

The guest kernel has no vDSO, so every clock_gettime of every Android thread
leaves the interpreter, saves the processor state, enters the kernel's system
call path and comes back: about 750 ns of guest time where a phone spends
about 20 ns.  gettimeofday and the coarse, raw and thread clocks go the same
way.  Android's interface code asks for the time constantly; in a
sampled list scroll it was the largest single item of the app's processor
time.

The kernel is a native image in the same process and the thread that runs a
guest task is that task's kernel thread.  So the engine calls the kernel's own
clock readers (the functions the system call ends in, time namespaces
included) directly, stores the answer in the guest's memory and continues the
guest.  Anything unusual takes the ordinary path: another clock, single-step,
a destination that is not writable yet.

The addresses are those of the pinned kernel artifact; `--check` compares
them with its System.map and the build stops on a difference.
UML_FAST_CLOCK=0 turns the fast path off for a comparison run.

Usage: fastclock_patch.py <upstream root>
       fastclock_patch.py --check <System.map>
"""
import sys
from pathlib import Path

SYMBOLS = {
    "posix_get_realtime_timespec": 0xC002A7624,
    "posix_get_monotonic_timespec": 0xC002A78B4,
    "posix_get_boottime_timespec": 0xC002A7B84,
    "posix_get_monotonic_raw": 0xC002A7A04,
    "posix_get_realtime_coarse": 0xC002A7AD0,
    "posix_get_monotonic_coarse": 0xC002A7AEC,
    "thread_cpu_clock_get": 0xC002A8C50,
}

if sys.argv[1] == "--check":
    found = {}
    for line in Path(sys.argv[2]).read_text().splitlines():
        address, _, name = line.split(" ", 2)
        if name in SYMBOLS:
            found[name] = int(address, 16)
    if found != SYMBOLS:
        raise SystemExit(f"fast clock: kernel symbols differ from the patch: {found}")
    print("fast clock: kernel symbol addresses match")
    sys.exit(0)

root = Path(sys.argv[1])


def edit(relative: str, changes) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


edit("darwin/runtime/native_kernel_layout.cpp", [
    ("namespace uml::runtime {\n",
     """#include <atomic>

namespace uml::runtime {

/* Where the running kernel image is, for the engine's direct clock calls;
 * zero while no kernel runs. */
std::atomic<std::uintptr_t> fast_clock_kernel_bias{0};
"""),
    ("""\tentered_ = ::uml::memory::configure_native_address_window(
\t\tlayout.window_start, layout.window_end);
""",
     """\tentered_ = ::uml::memory::configure_native_address_window(
\t\tlayout.window_start, layout.window_end);
\tif (entered_)
\t\tfast_clock_kernel_bias.store(layout.load_bias,
\t\t\tstd::memory_order_release);
"""),
    ("""\tif (entered_)
\t\t::uml::memory::reset_native_address_window();
""",
     """\tfast_clock_kernel_bias.store(0, std::memory_order_release);
\tif (entered_)
\t\t::uml::memory::reset_native_address_window();
"""),
])

addresses = "\n".join(
    f"constexpr std::uintptr_t fast_{name} = 0x{value:X}ULL;" for name, value in SYMBOLS.items())
edit("darwin/runtime/static_guest.cpp", [
    ("namespace uml::emulator {\n",
     """#include <cstdlib>
#include <span>

namespace uml::runtime {
extern std::atomic<std::uintptr_t> fast_clock_kernel_bias;
}

namespace uml::emulator {

namespace fast_clock {

/* Link addresses in the pinned kernel artifact (fastclock_patch.py checks
 * them against its System.map). */
""" + addresses + """
constexpr std::uint64_t nr_clock_gettime = 113;
constexpr std::uint64_t nr_gettimeofday = 169;

[[nodiscard]] inline bool enabled() noexcept
{
\tstatic const bool value = [] {
\t\tconst char *text = std::getenv("UML_FAST_CLOCK");
\t\treturn text == nullptr || text[0] != '0';
\t}();
\treturn value;
}

/* The kernel's reader for a clock; zero for clocks left to the kernel
 * (process time, alarm clocks, dynamic clocks). */
[[nodiscard]] inline std::uintptr_t reader_of(std::int32_t clock) noexcept
{
\tswitch (clock) {
\tcase 0: return fast_posix_get_realtime_timespec;
\tcase 1: return fast_posix_get_monotonic_timespec;
\tcase 3: return fast_thread_cpu_clock_get;
\tcase 4: return fast_posix_get_monotonic_raw;
\tcase 5: return fast_posix_get_realtime_coarse;
\tcase 6: return fast_posix_get_monotonic_coarse;
\tcase 7: return fast_posix_get_boottime_timespec;
\tdefault: return 0;
\t}
}

/* A time query the guest just asked for, answered by the kernel's own
 * reader on this kernel thread. False leaves the system call to the kernel. */
template<typename Cpu, typename Memory>
[[nodiscard]] inline bool answer(Cpu &cpu, Memory &memory) noexcept
{
\tconst auto number = cpu.registers[8];
\tif ((number != nr_clock_gettime && number != nr_gettimeofday) || !enabled())
\t\treturn false;
\tconst auto bias = ::uml::runtime::fast_clock_kernel_bias.load(
\t\tstd::memory_order_relaxed);
\tif (bias == 0)
\t\treturn false;
\tusing posix_reader = int (*)(int, std::int64_t *);
\tstd::int64_t time[2]{};
\tif (number == nr_gettimeofday) {
\t\t/* Only the plain form: a time value and no time zone. */
\t\tif (cpu.registers[0] == 0 || cpu.registers[1] != 0)
\t\t\treturn false;
\t\tif (reinterpret_cast<posix_reader>(
\t\t\t    bias + fast_posix_get_realtime_timespec)(0, time) != 0)
\t\t\treturn false;
\t\ttime[1] /= 1000;
\t\tif (!memory.write(cpu.registers[0],
\t\t\t    std::as_bytes(std::span<const std::int64_t>{time})))
\t\t\treturn false;
\t\tcpu.registers[0] = 0;
\t\treturn true;
\t}
\tconst auto clock = static_cast<std::int32_t>(cpu.registers[0]);
\tconst auto reader = reader_of(clock);
\tif (reader == 0)
\t\treturn false;
\tif (reinterpret_cast<posix_reader>(bias + reader)(clock, time) != 0)
\t\treturn false;
\tif (!memory.write(cpu.registers[1],
\t\t    std::as_bytes(std::span<const std::int64_t>{time})))
\t\treturn false;
\tcpu.registers[0] = 0;
\treturn true;
}

} // namespace fast_clock
"""),
])

# The tier experiment rewrites these lines without indentation, so match them
# whatever the leading white space is.
import re
path = root / "darwin/runtime/static_guest.cpp"
text = path.read_text()
pattern = re.compile(r"[ \t]*const auto result = engine->run\(request\);\n[ \t]*debug_check_host_streaming_state\(\);\n")
if len(pattern.findall(text)) != 1:
    raise SystemExit("static_guest.cpp: the AArch64 run call was not found exactly once")
text = pattern.sub(lambda _: """\tauto result = engine->run(request);
\t/* A time query is answered here and the guest runs on. */
\twhile (result.reason == uml::cpu::ExitReason::system_call &&
\t       !request.single_step && fast_clock::answer(cpu, memory))
\t\tresult = engine->run(request);
\tdebug_check_host_streaming_state();
""", text)
path.write_text(text)
print("fast clock: patched")
