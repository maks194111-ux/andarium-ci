# 0301
#noshot
cd "$WORK/live-package" && adb -s "$SERIAL" install-multiple -i com.android.vending com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk 2>&1 | tail -1
guest logcat -c
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 30
guest logcat -d > "$WORK/lc.txt" 2>&1
a=$(grep -a -n "nativeloader: Load .*libsupercell" "$WORK/lc.txt" | head -1 | cut -d: -f1); b=$(grep -a -n "Report  : Exiting" "$WORK/lc.txt" | head -1 | cut -d: -f1)
echo "lines $a..$b"
sed -n "${a},${b}p" "$WORK/lc.txt" | sed 's/^[0-9-]* //' | cut -c1-330 | head -120
