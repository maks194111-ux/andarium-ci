#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fit the guest's memory to the address range the device grants.

A device report (iPad Pro M2, iPadOS 27.1): a 3 GiB guest needs one 7 GiB
address window, and every reservation of it failed with ENOMEM, so the start
ended with -4 before the guest kernel ran; a smaller memory setting started.
The window's length follows the guest's memory, so before the boot the runtime
now asks for the window of the configured size and, when the device refuses,
of each smaller size in 128 MiB steps down to 1 GiB, and boots with the first
size whose window the device grants.  A device that grants the configured
size is unaffected.  Run after window_patch.py.
"""
import sys
from pathlib import Path

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
    ("""NativeKernelLayout prepare_native_kernel_layout(
""",
     """#if defined(__APPLE__)
/* The free address ranges of at least 512 MiB and where the address space
 * ends: what a refused window is measured against. */
static void report_free_address_ranges() noexcept
{
vm_address_t cursor = 0;
unsigned lines = 0;
for (;;) {
vm_address_t region = cursor;
vm_size_t size = 0;
vm_region_basic_info_data_64_t information {};
mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
mach_port_t object = MACH_PORT_NULL;
const kern_return_t result = vm_region_64(mach_task_self(), &region,
&size, VM_REGION_BASIC_INFO_64,
reinterpret_cast<vm_region_info_t>(&information), &count, &object);
if (object != MACH_PORT_NULL)
(void)mach_port_deallocate(mach_task_self(), object);
if (result != KERN_SUCCESS || size == 0) {
std::fprintf(stderr, "UML: address space: last region ends at %p\\n",
reinterpret_cast<void *>(cursor));
break;
}
if (region > cursor && region - cursor >= (vm_address_t{512} << 20) &&
    lines < 24) {
std::fprintf(stderr, "UML: address space: free %p-%p (%llu MiB)\\n",
reinterpret_cast<void *>(cursor),
reinterpret_cast<void *>(region),
static_cast<unsigned long long>((region - cursor) >> 20));
++lines;
}
cursor = region + size;
}
}
#else
static void report_free_address_ranges() noexcept {}
#endif

/* The most guest memory, at most `wanted_mib`, whose window this process can
 * reserve now; `wanted_mib` itself when even the smallest cannot be, so the
 * boot reports the refusal as before. The trial reservation is handed back:
 * the boot makes its own. */
unsigned admitted_guest_memory_mib(unsigned wanted_mib) noexcept
{
constexpr unsigned step = 128, floor = 1024;
for (unsigned mib = wanted_mib; mib >= floor; mib -= step) {
const auto product = native_kernel_placement(
static_cast<std::size_t>(mib) << 20);
if (!product.geometry.valid)
continue;
if (product.placement == WindowPlacement::exact)
return wanted_mib;
/* A window this process already holds serves a guest of this size. */
const auto held = process_native_window();
if (held.end - held.begin >=
    product.geometry.window_end - product.geometry.window_start)
return mib;
const auto trial = reserve_native_kernel_window(
product.geometry, product.placement);
if (!trial.valid)
continue;
munmap(reinterpret_cast<void *>(trial.window_start),
host_reservation_length(trial.window_end - trial.window_start));
if (mib != wanted_mib) {
report_free_address_ranges();
std::fprintf(stderr,
"UML: no address window for %u MiB of guest memory; "
"the device grants one for %u MiB at %p\\n",
wanted_mib, mib,
reinterpret_cast<void *>(trial.window_start));
}
return mib;
}
report_free_address_ranges();
return wanted_mib;
}

NativeKernelLayout prepare_native_kernel_layout(
"""),
])
edit("darwin/runtime/native_kernel_layout.cpp", [
    ("#include <cerrno>\n",
     "#include <cerrno>\n#if defined(__APPLE__)\n#include <mach/mach.h>\n#endif\n"),
])
edit("darwin/runtime/native_kernel_layout.hpp", [
    ("""[[nodiscard]] NativeKernelPlacement native_kernel_placement(
	std::size_t guest_memory) noexcept;
""",
     """[[nodiscard]] NativeKernelPlacement native_kernel_placement(
	std::size_t guest_memory) noexcept;
[[nodiscard]] unsigned admitted_guest_memory_mib(unsigned wanted_mib) noexcept;
"""),
])
edit("Kernarium/Runtime/KernariumRuntime.mm", [
    ("""        const uint32_t guestMemoryMiB = boot->guest_memory_mib;
""",
     """        uint32_t guestMemoryMiB = boot->guest_memory_mib;
"""),
    ("""        GuestRequest request;
        request.adbPublicKey = std::move(adbPublicKey);
""",
     """        if (const uint32_t admitted =
                uml::runtime::admitted_guest_memory_mib(guestMemoryMiB);
            admitted != guestMemoryMiB) {
            std::printf(
                "Kernarium: guest memory %u MiB instead of %u MiB: the "
                "device has no address range for more\\n",
                admitted, guestMemoryMiB);
            guestMemoryMiB = admitted;
        }
        GuestRequest request;
        request.adbPublicKey = std::move(adbPublicKey);
"""),
])
path = root / "Kernarium/Runtime/KernariumRuntime.mm"
text = path.read_text()
marker = '#include "uml/emulator.h"\n'
if text.count(marker) != 1:
    raise SystemExit("KernariumRuntime.mm: emulator include not found")
path.write_text(text.replace(marker, marker +
    "namespace uml::runtime {\n"
    "unsigned admitted_guest_memory_mib(unsigned wanted_mib) noexcept;\n"
    "}\n"))
print("guest memory is fitted to the address window the device grants")
