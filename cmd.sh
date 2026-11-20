# 0402
ls -la "$WORK"/live-package.ready "$WORK"/live-package | head -12; cat "$WORK/live-package.log" | tail -3
guest shell 'getprop sys.boot_completed; uptime; pm list packages | grep -c supercell; dumpsys activity activities | grep -m1 topResumed; cat /proc/loadavg'
