#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Give the Andarium phone profile a conventional ARM CPU identifier.

Both the guest kernel's /proc/cpuinfo and the value returned to an application's
MIDR_EL1 read must agree. Change only these identification constants; instruction
execution, translation, and CPU feature registers remain upstream's implementations.

Usage: phone_cpu_identity.py <upstream> [--kernel-only]
The upstream checkout is changed in place and must still contain the stock values.
"""
import argparse
from pathlib import Path

KERNEL_PATCH = Path(
    "kernel/common/patches/"
    "uml-describe-the-arm64-virtual-CPU-in-proc-cpuinfo-as-arm64-Linux-do.patch"
)
ENGINE_HEADER = Path("darwin/cpu/arm64/id_registers.hpp")


def replace_once(path, old, new):
    text = path.read_text()
    count = text.count(old)
    assert count == 1, f"expected one stock CPU identity block in {path}, found {count}"
    path.write_text(text.replace(old, new))


def kernel_identity(root):
    replace_once(
        root / KERNEL_PATCH,
        """+ * The emulator answers MRS MIDR_EL1 with emulated_midr_el1 in
+ * darwin/cpu/arm64/id_registers.hpp: no JEP106 implementer, variant, part or
+ * revision, and architecture 0xf, \"described by the identification
+ * registers\".  This kernel runs natively on the host, where it cannot read
+ * the emulated register, so the value is mirrored here, as the x86 slice
+ * mirrors the emulator's CPUID.  The host's engine smoke tests compare these
+ * lines with the register a guest task reads.
""",
        """+ * The emulator answers MRS MIDR_EL1 with emulated_midr_el1 in
+ * darwin/cpu/arm64/id_registers.hpp: an ARM Cortex-A76, variant 0 and
+ * revision 4 (0x410fd0b4), with architecture 0xf. This kernel runs
+ * natively on the host and cannot read the emulated register, so the
+ * value is mirrored here, as the x86 slice mirrors the emulator's CPUID.
+ * The host's engine smoke tests compare these lines with the register
+ * a guest task reads.
""",
    )
    replace_once(
        root / KERNEL_PATCH,
        "+#define UML_ARM64_MIDR 0x000f0000U",
        "+#define UML_ARM64_MIDR 0x410fd0b4U",
    )
    # prepare-source.sh replays every patch and verifies the resulting Linux
    # tree. This is the tree CI computed from the patched series on the pinned
    # upstream base; change the expected value rather than bypass that check.
    replace_once(
        root / "kernel/mainline-6.18/patches/metadata.env",
        "UML_KERNEL_FINAL_TREE='ee913342fecf9f7f9836b616f5c605a036da0098'",
        "UML_KERNEL_FINAL_TREE='7add27eb1264439c1a41c2a10b946c128de3c69e'",
    )
    # Engine configure selects the custom Android bundle by the accepted
    # descriptor's directory and verifies every other field against its manifest.
    descriptor = root / "kernel/mainline-6.18/artifacts/accepted-android-4k.env"
    replace_once(
        descriptor,
        "UML_KERNEL_ARTIFACT_RELEASE_ID='20261119-6.18.60-ca1'",
        "UML_KERNEL_ARTIFACT_RELEASE_ID='20261120-6.18.60-cpu1'",
    )
    replace_once(
        descriptor,
        "UML_KERNEL_ARTIFACT_DIRECTORY_NAME='android-6.18-arm64-4k-20261119-6.18.60-ca1'",
        "UML_KERNEL_ARTIFACT_DIRECTORY_NAME='android-6.18-arm64-4k-20261120-6.18.60-cpu1'",
    )
    replace_once(
        descriptor,
        "UML_KERNEL_ARTIFACT_FINAL_TREE='ee913342fecf9f7f9836b616f5c605a036da0098'",
        "UML_KERNEL_ARTIFACT_FINAL_TREE='7add27eb1264439c1a41c2a10b946c128de3c69e'",
    )


def engine_identity(root):
    replace_once(
        root / ENGINE_HEADER,
        """/* This virtual CPU holds no JEP106 implementer code, part number or revision.
 * Architecture 0b1111 is the architectural encoding for \"the identification
 * registers describe this implementation\", which is exactly what a guest
 * reading MIDR_EL1 here must fall back on. The kernel, which cannot execute
 * this read, prints the same fields in /proc/cpuinfo from a copy of the value
 * (show_arm64_cpuinfo() in the shared kernel series), and the engine smoke
 * tests fail when the two disagree. */
inline constexpr std::uint64_t emulated_midr_el1 = 0x000f'0000ULL;
""",
        """/* Andarium's phone identity reports an ARM Cortex-A76 (0x410fd0b4).
 * Only this identification value changes: instruction interpretation,
 * translation and the implemented feature registers stay as upstream has
 * them. Architecture 0b1111 says the identification fields describe this
 * implementation. The kernel cannot execute the userspace emulation, so it
 * mirrors this constant in /proc/cpuinfo (show_arm64_cpuinfo() in the shared
 * kernel series), and the engine smoke tests require both values to agree. */
inline constexpr std::uint64_t emulated_midr_el1 = 0x410f'd0b4ULL;
""",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--kernel-only", action="store_true")
    arguments = parser.parse_args()
    root = arguments.upstream.resolve()
    kernel_identity(root)
    if not arguments.kernel_only:
        engine_identity(root)
    print("CPU identity installed: ARM Cortex-A76, MIDR_EL1=0x410fd0b4", flush=True)


if __name__ == "__main__":
    main()
