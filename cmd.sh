# 0004
#noshot
cd "$WORK/live-package"
( adb -s "$SERIAL" install-multiple com.supercell.brawlstars.apk config.arm64_v8a.apk config.en.apk config.ru.apk config.xxhdpi.apk install_time_asset_pack.apk > "$WORK/install.log" 2>&1; date >> "$WORK/install.log" ) &
sleep 5; date; cat "$WORK/install.log"
