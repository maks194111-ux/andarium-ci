# 0305
#noshot
guest shell 'getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getprop ro.hardware; getprop sys.boot_completed; pm list packages | grep -c supercell'
guest logcat -c
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 40
guest logcat -d > "$WORK/lc.txt" 2>&1
grep -a -E "Report  : (Exiting|rmy)|brawlstars.*has died|Fatal signal|libc    : Access denied" "$WORK/lc.txt" | sed 's/^[0-9-]* //' | cut -c1-200 | head -14
guest shell 'pidof com.supercell.brawlstars; dumpsys activity activities | grep -m1 topResumed'
shot "$n"
