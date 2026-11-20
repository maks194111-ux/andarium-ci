# 0302
#noshot
a=$(grep -a -n "nativeloader: Load .*libsupercell" "$WORK/lc.txt" | head -1 | cut -d: -f1); b=$(grep -a -n "Report  : Exiting" "$WORK/lc.txt" | head -1 | cut -d: -f1)
sed -n "${a},${b}p" "$WORK/lc.txt" | grep -a -E "avc|denied|seccomp|ptrace|brawl|Zygote|ActivityManager: (Start|Process|Kill)|libc  |DEBUG|tombstone|untrusted_app" | grep -av "WindowManager\|Shell" | sed 's/^[0-9-]* //' | cut -c1-360 | head -70
echo "--- dmesg"; guest shell 'dmesg 2>&1 | tail -25' | cut -c1-240
echo "--- what an app sees"; guest shell 'run-as com.supercell.brawlstars id 2>&1; getprop ro.boot.vbmeta.device_state; getprop ro.bootloader; getprop ro.product.property_source_order; getprop ro.product.board; getprop ro.board.platform; getprop ro.product.device; getprop ro.product.name; getprop ro.product.brand; getprop gsm.version.baseband; ls -la /dev/ | grep -iE "qemu|goldfish|vport|hvc|ubd|virtio" | head; ls /sys/class/power_supply 2>&1 | head; ls /system/bin/su /system/xbin/su /sbin/su 2>&1 | head -3; cat /proc/version'
