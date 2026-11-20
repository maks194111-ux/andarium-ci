# 0416
#noshot
guest shell 'for p in ro.board.platform ro.hardware.virtual_device ro.product.model ro.product.system.model ro.system.build.fingerprint ro.soc.model ro.hardware ro.boot.verifiedbootstate sys.boot_completed; do echo "$p=$(getprop $p)"; done; dumpsys activity activities | grep -m1 topResumed; cat /proc/loadavg'
