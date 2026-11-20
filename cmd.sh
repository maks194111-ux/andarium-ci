# 0008
#noshot
grep -a -E " 4709 " "$WORK/lc.txt" | grep -a -v "AndroidRuntime: at \|Report  : at " | cut -c1-330 | head -60
guest shell 'getprop ro.build.tags; getprop ro.build.type; getprop ro.debuggable; getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getenforce; uname -a; getprop ro.build.fingerprint; getprop ro.product.model; getprop ro.hardware'
