# 0415
#noshot
#reboot reset
#limit 900
git -C "$WORK/live" show FETCH_HEAD:odm.img > "$WORK/odm-phone.img"; ls -la "$WORK/odm-phone.img"
R="$WORK/release-aotnew"; rm -rf "$WORK/release-phone"
python3 "$HERE/sf_pipeline/splice_odm.py" "$R" "$WORK/release-phone" "$WORK/odm-phone.img" 2>&1 | tail -2
kill -INT "$launcher" 2>/dev/null; sleep 15; pkill -9 -f uml-darwin-android17
cp "$R/boot/kernel-command-line.txt" "$WORK/cmdline.phone"
mv "$WORK/release-phone/guest/system.img" "$R/guest/system.img" && cp "$WORK/release-phone/guest/partition-layout.json" "$R/guest/" && cp "$WORK/release-phone/release-manifest.json" "$R/" && echo replaced
rm -rf "$WORK/release-phone"; df -h "$WORK" | tail -1
