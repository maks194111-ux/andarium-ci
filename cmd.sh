# 0103
guest shell 'am force-stop com.supercell.brawlstars; input keyevent KEYCODE_HOME'
curl -fsSL --retry 3 -o "$WORK/stk.apk" https://github.com/supertuxkart/stk-code/releases/download/1.5/SuperTuxKart-1.5.apk
adb -s "$SERIAL" install "$WORK/stk.apk" 2>&1 | tail -1; rm -f "$WORK/stk.apk"
guest shell 'monkey -p org.supertuxkart.stk -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 50
guest shell 'input tap 698 1046'; sleep 8
guest shell 'input keyevent KEYCODE_DPAD_RIGHT; sleep 1; input keyevent KEYCODE_DPAD_RIGHT'; sleep 4
