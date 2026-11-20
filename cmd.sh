# 0406
guest shell 'getprop ro.boot.verifiedbootstate; getprop ro.hardware; getprop sys.boot_completed; pm list packages | grep -c supercell; dumpsys activity activities | grep -m1 topResumed; cat /proc/loadavg'
