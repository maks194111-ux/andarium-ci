#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Experiment: tiered execution of arm64 address spaces.

Upstream's JIT translates every process's code from its first instruction, so
an Android guest spends its time translating code that runs once.  Upstream
has a tier for x86-64 guests (`--jit-tier=N`): an address space starts on the
gadget engine and moves to the JIT after N retired instructions.  This applies
the same state machine (runtime/x86_tier.hpp, unchanged) to arm64 address
spaces, so only long-lived, busy processes are translated.

With `--jit-tier` absent or zero nothing changes.  Every replacement must
match exactly once, or the script fails.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])


def edit(relative, pairs):
    """Replace each `old` with `new`; lines match whatever their indentation."""
    path = root / relative
    text = path.read_text()
    for old, new in pairs:
        pattern = "".join(r"[ \t]*" + re.escape(line.strip()) + r"\n"
                          for line in old.splitlines())
        found = re.findall(pattern, text)
        if len(found) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:70]!r}, found {len(found)}")
        text = re.sub(pattern, lambda _: new, text)
    path.write_text(text)


# The per-thread tier state, for every product.
edit("darwin/runtime/execution_state.hpp", [
    ('#include "memory/static_guest_memory.hpp"\n',
     '#include "memory/static_guest_memory.hpp"\n#include "runtime/x86_tier.hpp"\n'),
    ("#if DARWIN_UML_X86_64_JIT\n"
     "/* The tier state of the address space this vCPU last ran in. */\n",
     "/* The tier state of the arm64 address space this vCPU last ran in. */\n"
     "std::shared_ptr<X86TierState> arm64_tier;\n"
     "unsigned long arm64_tier_generation{};\n"
     "#if DARWIN_UML_X86_64_JIT\n"
     "/* The tier state of the address space this vCPU last ran in. */\n"),
])

# In a tiered run both engines and the guest's HWCAPs use what both implement.
edit("darwin/runtime/context.cpp", [
    ("const auto *context = current_context();\n"
     "return guest_host_capabilities(context != nullptr ?\n"
     "context->execution_engine() : ExecutionEngine::automatic);\n",
     "const auto *context = current_context();\n"
     "return guest_host_capabilities(context != nullptr &&\n"
     "context->x86_jit_tier() == 0 ?\n"
     "context->execution_engine() : ExecutionEngine::automatic);\n"),
])

HELPER = r'''
/* Tiered arm64 execution (experiment): the tier state of `generation` for
 * this vCPU, or null when the run names no threshold. */
[[nodiscard]] ::uml::runtime::X86TierState *arm64_tier_state(
::uml::runtime::Context &context,
::uml::runtime::ThreadExecutionState &runtime,
unsigned long generation) noexcept
{
auto *table = context.x86_tier_table(nullptr);
if (table == nullptr)
return nullptr;
if (runtime.arm64_tier == nullptr ||
    runtime.arm64_tier_generation != generation) {
runtime.arm64_tier = table->acquire(generation);
runtime.arm64_tier_generation = generation;
}
return runtime.arm64_tier.get();
}

/* The engine of each kind in a tiered run implements what both do. */
[[gnu::cold, gnu::noinline]] void create_tiered_engine(
std::unique_ptr<uml::cpu::CpuEngine> &slot, uml::cpu::EngineKind kind)
{
slot = uml::cpu::make_cpu_engine(kind,
uml::cpu::EngineConfiguration{
.host_capabilities =
::uml::runtime::guest_host_capabilities(
::uml::runtime::ExecutionEngine::automatic),
});
}

'''

edit("darwin/runtime/static_guest.cpp", [
    ("bool signal_return_boundary(arm64::CpuState &cpu, void *) noexcept\n",
     HELPER.lstrip("\n") + "\nbool signal_return_boundary(arm64::CpuState &cpu, void *) noexcept\n"),
    # The 64-bit entry.
    ("auto &cpu = runtime->cpu;\n"
     "auto &memory = runtime->memory;\n"
     "load_cpu(cpu, mutable_registers, fp, *tls, context->top_byte_ignore());\n",
     "::uml::runtime::X86TierState::Entry tier;\n"
     "bool on_gadgets = Kind == uml::cpu::EngineKind::gadgets;\n"
     "if constexpr (Kind == uml::cpu::EngineKind::jit) {\n"
     "if (auto *state = arm64_tier_state(*context, *runtime, generation)) {\n"
     "tier = state->enter([&]() noexcept {\n"
     "return context->stop_requested();\n"
     "});\n"
     "if (tier.abandoned())\n"
     "return DARWIN_UML_EVENT_STOP;\n"
     "on_gadgets = tier.engine() ==\n"
     "::uml::runtime::X86TierState::Engine::gadgets;\n"
     "}\n"
     "}\n"
     "auto &cpu = runtime->cpu;\n"
     "auto &memory = runtime->memory;\n"
     "load_cpu(cpu, mutable_registers, fp, *tls, context->top_byte_ignore());\n"),
    ("if constexpr (Kind != uml::cpu::EngineKind::gadgets)\n"
     "cpu.access_fp_state();\n"
     "auto *engine = common_engine<Kind>(*runtime);\n"
     "if (engine == nullptr)\n"
     "return DARWIN_UML_EVENT_FATAL;\n",
     "if (!on_gadgets)\n"
     "cpu.access_fp_state();\n"
     "uml::cpu::CpuEngine *engine = nullptr;\n"
     "if (context->x86_jit_tier() != 0 &&\n"
     "    Kind == uml::cpu::EngineKind::jit) {\n"
     "auto &slot = on_gadgets ?\n"
     "runtime->engines.template slot<uml::cpu::EngineKind::gadgets>() :\n"
     "runtime->engines.template slot<uml::cpu::EngineKind::jit>();\n"
     "if (!slot) [[unlikely]]\n"
     "create_tiered_engine(slot, on_gadgets ?\n"
     "uml::cpu::EngineKind::gadgets : uml::cpu::EngineKind::jit);\n"
     "engine = slot.get();\n"
     "} else {\n"
     "engine = common_engine<Kind>(*runtime);\n"
     "}\n"
     "if (engine == nullptr)\n"
     "return DARWIN_UML_EVENT_FATAL;\n"),
    ("const auto result = engine->run(request);\n"
     "debug_check_host_streaming_state();\n"
     "save_cpu(cpu, mutable_registers, fp, sme, *tls);\n",
     "const auto result = engine->run(request);\n"
     "debug_check_host_streaming_state();\n"
     "tier.leave(result.retired_instructions);\n"
     "save_cpu(cpu, mutable_registers, fp, sme, *tls);\n"),
])
print("arm64 tier: address spaces start on the gadget engine when --jit-tier names a threshold")
