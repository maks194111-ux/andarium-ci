# 0101
#noshot
guest shell 'for p in ro.build.tags ro.build.type ro.debuggable ro.secure ro.boot.verifiedbootstate ro.boot.flash.locked ro.build.fingerprint ro.product.model ro.product.manufacturer ro.hardware ro.kernel.qemu ro.boot.qemu ro.product.cpu.abilist ro.build.version.release ro.build.version.sdk; do echo "$p=[$(getprop $p)]"; done; getenforce; uname -a; head -12 /proc/cpuinfo; settings get global adb_enabled; settings get global development_settings_enabled' 2>&1 | cut -c1-200
ls "$WORK"/live-package.ready; cat "$WORK/live-package.log"
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1
rm -rf "$WORK/live-package" "$WORK/live-package.zip"; df -h "$WORK" | tail -1
