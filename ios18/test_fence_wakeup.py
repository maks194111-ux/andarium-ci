"""Exercise the generated C++ arming method with an instrumented timer backend."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

rel = Path('darwin/device/gpu/gpu_vhost_user_server.cpp')
for compare in (False, True):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        dest = root / rel
        dest.parent.mkdir(parents=True)
        shutil.copy(Path(sys.argv[1]) / rel, dest)
        subprocess.run([sys.executable, str(Path(__file__).with_name('fence_wakeup_patch.py')), folder] + (['--compare'] if compare else []), check=True)
        s = dest.read_text()
        method = s[s.index('    bool fenceWakeArmed_'):s.index('    bool idleTrimTimerArmed_')]
        deliver = s.split('event.ident == fenceTimerIdentifier) {')[1].split('fenceTimerReady = true;')[0]
        reset = s.split('cancelFenceTimer(eventQueue_.get());')[1].split('fences_.clear();')[0]
        src = '''#include <cassert>
#include <chrono>
#include <cstdlib>
#include <cstdio>
struct Device { struct Q {int get(){return 1;}}eventQueue_; int arms=0; bool fail=false;
void armFenceTimer(int){ if(fail) throw 1; ++arms; }
''' + method + '\nvoid delivered(){' + deliver + '} void reset(){' + reset + '''} };
int main(){ Device d; d.fail=true; try{d.requestFenceWake();return 2;}catch(int){} d.fail=false;
for(int i=0;i<10000;i++) d.requestFenceWake(); assert(d.arms==EXPECTED);
d.delivered(); d.requestFenceWake(); assert(d.arms==EXPECTED+1);
d.reset(); d.requestFenceWake(); assert(d.arms==EXPECTED+2); }
'''
        (root/'test.cpp').write_text(src)
        for mode in ((0,1) if compare else (1,)):
            (root/'mode').write_text(str(mode))
            subprocess.run(['c++','-std=c++17',f'-DEXPECTED={1 if mode else 10000}',str(root/'test.cpp'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],env={**os.environ,'UML_FENCE_WAKE_CONTROL':str(root/'mode')},check=True)
print('PASS: burst, delivery/rearm, reset and registration failure under both policies')
