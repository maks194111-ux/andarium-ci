# 0407
#noshot
#reboot
f=$(ls -d "$WORK"/release-aotnew)/boot/kernel-command-line.txt
grep -a -iE "avb|verity|vbmeta|panic|reboot|init: .*(fatal|failed)" "$OUT/live/launcher.log" | tail -12 | cut -c1-220
sed -i '' 's/androidboot.vbmeta.device_state=locked/androidboot.vbmeta.device_state=unlocked/' "$f"
grep -o "androidboot.verifiedbootstate=[a-z]*\|device_state=[a-z]*\|flash.locked=[0-9]\|androidboot.hardware=[a-z_]*" "$f"
