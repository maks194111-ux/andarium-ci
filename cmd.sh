# 0201
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1
rm -rf "$WORK/live-package" "$WORK/live-package.zip"
grep -a -iE "aot" "$dir/launcher.log" | head -5 | cut -c1-200
guest logcat -c
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 35
guest logcat -d > "$WORK/lc.txt" 2>&1
grep -a -E "Report  : (Exiting|rmy)|brawlstars.*has died|Fatal signal" "$WORK/lc.txt" | cut -c1-200 | head
guest shell 'pidof com.supercell.brawlstars; dumpsys activity activities | grep -m1 topResumed'
