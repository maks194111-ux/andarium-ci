# 0404
#noshot
#reboot
f=$(ls -d "$WORK"/release-aotnew)/boot/kernel-command-line.txt
cp "$f" "$WORK/cmdline.orig"
sed -i '' 's/androidboot.verifiedbootstate=orange/androidboot.verifiedbootstate=green/; s/androidboot.vbmeta.device_state=unlocked/androidboot.vbmeta.device_state=locked/; s/androidboot.flash.locked=0/androidboot.flash.locked=1/; s/androidboot.hardware=cutf_cvm/androidboot.hardware=andarium/' "$f"
grep -o "androidboot.verifiedbootstate=[a-z]*\|device_state=[a-z]*\|flash.locked=[0-9]\|androidboot.hardware=[a-z_]*" "$f"
