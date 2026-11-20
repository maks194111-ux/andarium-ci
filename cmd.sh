# 0411
#noshot
#reboot reset
f=$(ls -d "$WORK"/release-aotnew)/boot/kernel-command-line.txt
sed -i '' 's/androidboot.vbmeta.device_state=unlocked/androidboot.vbmeta.device_state=locked/' "$f"
grep -o "androidboot.verifiedbootstate=[a-z]*\|device_state=[a-z]*\|flash.locked=[0-9]\|androidboot.hardware=[a-z_]*" "$f"
