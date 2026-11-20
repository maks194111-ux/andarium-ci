# 0401
#noshot
#reboot
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple -i com.android.vending com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1
guest shell 'ls /vendor/etc/init/hw/ /vendor/ueventd.rc /odm/etc/init 2>&1; ls /vendor/etc/fstab* /vendor/etc/*.rc 2>&1 | head; grep -rl "ro.hardware}" /system/etc/init /vendor/etc/init 2>/dev/null | head; grep -n "ro.hardware" /system/etc/init/hw/init.rc | head'
