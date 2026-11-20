# 0403
#noshot
#limit 900
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple -i com.android.vending com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1
guest shell 'ls /vendor/etc/init/hw/ /odm/etc/init 2>&1; ls /vendor/ueventd.rc /vendor/etc/fstab* 2>&1 | head; grep -n "ro.hardware" /system/etc/init/hw/init.rc | head'
