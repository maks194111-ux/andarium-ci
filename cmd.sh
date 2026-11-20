# 0009
guest shell 'pm uninstall com.supercell.brawlstars' ; rm -rf "$WORK/live-package" "$WORK/live-package.zip"
curl -fsSL --retry 3 -o "$WORK/stk.apk" https://github.com/supertuxkart/stk-code/releases/download/1.5/SuperTuxKart-1.5.apk && ls -la "$WORK/stk.apk"
adb -s "$SERIAL" install "$WORK/stk.apk" 2>&1 | tail -2
guest shell 'pm list packages | grep -i tux; cat /proc/loadavg'
rec on; mark "SuperTuxKart starts"
guest shell 'monkey -p org.supertuxkart.stk -c android.intent.category.LAUNCHER 1' 2>&1 | tail -1
sleep 45
guest shell 'dumpsys activity activities | grep -m1 topResumed; pidof org.supertuxkart.stk'
