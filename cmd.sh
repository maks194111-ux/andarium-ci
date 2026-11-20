# 0602
#noshot
guest shell 'echo CMDLINE; cat /proc/cmdline; echo CPU; cat /proc/cpuinfo; echo MODEL; for f in /proc/device-tree/model /sys/firmware/devicetree/base/model /sys/devices/virtual/dmi/id/product_name /sys/devices/virtual/dmi/id/sys_vendor; do echo "$f: $(cat $f 2>/dev/null)"; done; echo UNIX; cat /proc/net/unix | grep -iE "qemu|goldfish|ranchu|emulat|cuttle|vsoc|virtual"; echo DEV; ls /dev | grep -iE "qemu|goldfish|ranchu|emulat|cuttle|vsoc|virtual"; echo MOUNTS; cat /proc/mounts | grep -iE "qemu|goldfish|ranchu|emulat|cuttle|vsoc|virtual"'
