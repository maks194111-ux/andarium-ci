#!/usr/bin/env python3
"""Compile the patched reservation function against deterministic mmap replies.

Usage: python3 test_window_patch.py <pristine upstream checkout>
This checks fallback control flow, not whether a physical iOS device admits it.
"""
import pathlib
import subprocess
import sys
import tempfile

here = pathlib.Path(__file__).resolve().parent
source = pathlib.Path(sys.argv[1]) / "darwin/runtime/native_kernel_layout.cpp"
with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    target = root / "darwin/runtime/native_kernel_layout.cpp"
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text())
    subprocess.run([sys.executable, str(here / "window_patch.py"), str(root)], check=True)
    patched = target.read_text()
    start = patched.index("NativeKernelLayout reserve_native_kernel_window(")
    end = patched.index("NativeKernelLayoutScope::", start)
    function = patched[start:end]
    prefix = r"""
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cerrno>
#include <cassert>
#include <vector>
#define MAP_FAILED reinterpret_cast<void*>(~std::uintptr_t{0})
#define PROT_NONE 0
#define MAP_PRIVATE 1
#define MAP_ANON 2
#define MAP_NORESERVE 4
#define DARWIN_UML_GUEST_PAGE_SIZE 4096
#define DARWIN_UML_NATIVE_LINK_ADDRESS (48ULL << 30)
struct NativeKernelLayout {
    std::uintptr_t load_bias{}, window_start{}, window_end{};
    bool valid{}, reserved{};
};
enum class WindowPlacement { exact, anywhere };
std::vector<std::uintptr_t> replies;
std::size_t calls, unmaps;
void* mmap(void*, std::size_t, int, int, int, int) {
    const auto address = calls < replies.size() ? replies[calls] : ~std::uintptr_t{0};
    ++calls;
    errno = address == ~std::uintptr_t{0} ? ENOMEM : 0;
    return reinterpret_cast<void*>(address);
}
int munmap(void* address, std::size_t) {
    assert(address != MAP_FAILED);
    ++unmaps;
    return 0;
}
std::size_t host_reservation_length(std::size_t n) { return (n + 16383) & ~16383ULL; }
NativeKernelLayout reserved_layout(std::uintptr_t b, std::size_t n) {
    return {b - DARWIN_UML_NATIVE_LINK_ADDRESS, b, b+n, true, true};
}
"""
    tests = r"""
int main() {
    constexpr auto bad = ~std::uintptr_t{0};
    constexpr std::uintptr_t base = 60ULL << 30;
    const NativeKernelLayout geometry{0, base, base + (4ULL << 30), true, false};
    auto reset = [](std::initializer_list<std::uintptr_t> values) {
        replies = values; calls = unmaps = 0;
    };
    reset({base});
    assert(reserve_native_kernel_window(geometry, WindowPlacement::anywhere).valid);
    assert(calls == 1 && unmaps == 0);
    reset({bad, base + (2ULL << 30)});
    auto recovered = reserve_native_kernel_window(geometry, WindowPlacement::anywhere);
    assert(recovered.valid && recovered.window_start == base + (2ULL << 30));
    assert(calls == 2 && unmaps == 0);
    reset({bad});
    assert(!reserve_native_kernel_window(geometry, WindowPlacement::exact).valid);
    assert(calls == 1 && unmaps == 0);
    reset({base + 16384});
    assert(!reserve_native_kernel_window(geometry, WindowPlacement::exact).valid);
    assert(calls == 1 && unmaps == 1);
    reset({base + 4096});
    assert(reserve_native_kernel_window(geometry, WindowPlacement::anywhere).valid);
    assert(calls == 1 && unmaps == 0);
    reset({1ULL << 30, 2ULL << 30, base + (4ULL << 30)});
    assert(reserve_native_kernel_window(geometry, WindowPlacement::anywhere).valid);
    assert(calls == 3 && unmaps == 2);
    reset({bad});
    assert(!reserve_native_kernel_window(geometry, WindowPlacement::anywhere).valid);
    assert(calls == 8 && unmaps == 0);
    reset({});
    assert(!reserve_native_kernel_window({}, WindowPlacement::anywhere).valid);
    assert(calls == 0);
    puts("PASS: eight deterministic reservation cases");
}
"""
    cpp = root / "test.cpp"
    cpp.write_text(prefix + function + tests)
    exe = root / "test"
    subprocess.run(["g++", "-std=c++20", "-Wall", "-Wextra", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
