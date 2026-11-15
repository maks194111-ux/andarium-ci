#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the guest's processors and device services at user-initiated priority.

Upstream starts the guest from a thread with no stated quality of service, so
the threads that execute Android's code and the GPU service run at the
default class.  A frame is a short burst of work on those threads; the system
brings a core up to speed sooner, and prefers performance cores, for threads
that say a person is waiting.  User-initiated is one step below the app's own
interface thread, so touch handling and presentation are not starved.

Not measured on a phone.  On the hosted Mac (a virtual machine with equal
cores) it is expected to change nothing.

Usage: qos_patch.py <upstream root> engine|app
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
part = sys.argv[2]


def edit(relative: str, changes) -> None:
    path = root / relative
    text = path.read_text()
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: expected one match for {old[:60]!r}, found {text.count(old)}")
        text = text.replace(old, new)
    path.write_text(text)


if part == "engine":
    edit("darwin/runtime/kernel_threads.cpp", [
        ("#include <array>\n", "#include <array>\n#include <pthread.h>\n#include <pthread/qos.h>\n"),
        ("""void *const routine_argument = slot->argument;
slot->word.store(""",
         """void *const routine_argument = slot->argument;
/* A person is waiting for what the guest's processors compute. */
(void)pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0);
slot->word.store("""),
    ])
    edit("darwin/device/vhost_user/vhost_user_server.cpp", [
        ("#include <pthread.h>\n", "#include <pthread.h>\n#include <pthread/qos.h>\n"),
        ("""    (void)::pthread_setname_np(threadName_.c_str());
    try {
        const auto server = makeServer_();""",
         """    (void)::pthread_setname_np(threadName_.c_str());
    /* Device services, the GPU among them, finish the guest's frames. */
    (void)::pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0);
    try {
        const auto server = makeServer_();"""),
    ])
elif part == "app":
    edit("Andarium/Andarium/Live/LiveRuntime.swift", [
        ("""        worker.name = "andarium-runtime"
""",
         """        worker.name = "andarium-runtime"
        worker.qualityOfService = .userInitiated
"""),
    ])
else:
    raise SystemExit("part must be engine or app")
print(f"guest threads run at user-initiated priority ({part})")
