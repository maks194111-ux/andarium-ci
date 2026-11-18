"""Keep the first outstanding fence timer deadline. Never change fence retirement."""
from pathlib import Path
import sys

p = Path(sys.argv[1]) / 'darwin/device/gpu/gpu_vhost_user_server.cpp'
s = p.read_text()
def change(old, new, n=1):
    global s
    if s.count(old) != n:
        raise RuntimeError('unexpected transport layout: ' + old[:80])
    s = s.replace(old, new)

change('armFenceTimer(eventQueue_.get());', 'requestFenceWake();', 5)
change('cancelFenceTimer(eventQueue_.get());', 'cancelFenceTimer(eventQueue_.get());\n        fenceWakeArmed_ = false;')
change('fenceTimerReady = true;', 'fenceWakeArmed_ = false; // EV_DISPATCH delivered and disabled the timer\n                fenceTimerReady = true;')
extra = ''
if '--compare' in sys.argv:
    change('#include <chrono>', '#include <chrono>\n#include <cstdlib>\n#include <cstdio>')
    extra = '''
        // Test harness only: same process, guest and GPU; change policy between scenarios.
        static const char* path = std::getenv("UML_FENCE_WAKE_CONTROL");
        static thread_local auto next = std::chrono::steady_clock::time_point{};
        static thread_local int mode = -1;
        const auto now = std::chrono::steady_clock::now();
        if (now >= next) {
            next = now + std::chrono::seconds(1);
            int selected = 0;
            if (path) {
                if (auto* f = std::fopen(path, "r")) {
                    selected = std::fgetc(f) == '1'; std::fclose(f);
                }
            }
            if (mode != selected) std::fprintf(stderr, "fence wake coalescing=%d\\n", selected);
            mode = selected;
        }
        if (!mode) { armFenceTimer(eventQueue_.get()); fenceWakeArmed_ = true; return; }
'''
change('    bool idleTrimTimerArmed_ {};', '''    // Owned only by the transport event loop, like its deferred-fence queue.
    bool fenceWakeArmed_ {};
    void requestFenceWake()
    {''' + extra + '''
        if (fenceWakeArmed_) return;
        armFenceTimer(eventQueue_.get());
        fenceWakeArmed_ = true; // only after successful kevent registration
    }
    bool idleTrimTimerArmed_ {};''')
p.write_text(s)
