# 0601
#limit 900
#noshot
guest shell 'for p in ro.product.model ro.product.vendor.model ro.product.system.model ro.product.system_ext.model ro.product.bootimage.model ro.product.vendor_dlkm.model ro.product.odm.model ro.product.odm_dlkm.model ro.product.brand ro.product.device ro.board.platform ro.hardware ro.boot.verifiedbootstate ro.boot.flash.locked ro.boot.vbmeta.device_state; do echo "$p=$(getprop $p)"; done'
guest shell 'getprop | grep -iE "virtual device|generic system|cutf_cvm|vsoc_arm64|qemu|goldfish|ranchu|emulat" | cut -c1-180'
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple -i com.android.vending com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1; cd "$WORK"
#noshot
guest shell 'getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getprop ro.hardware; getprop sys.boot_completed; pm list packages | grep -c supercell'
guest logcat -c
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 40
guest logcat -d > "$WORK/lc.txt" 2>&1
grep -a -E "Report  : (Exiting|rmy)|brawlstars.*has died|Fatal signal|libc    : Access denied" "$WORK/lc.txt" | sed 's/^[0-9-]* //' | cut -c1-200 | head -14
guest shell 'pidof com.supercell.brawlstars; dumpsys activity activities | grep -m1 topResumed'
shot "$n"
