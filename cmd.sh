# 0703
#!/bin/sh
#limit 150
echo GAME_BEFORE
pidof com.supercell.brawlstars || true
adb -s "$SERIAL" shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity || true
sleep 60
echo GAME_AFTER_60_SECONDS
pidof com.supercell.brawlstars || true
adb -s "$SERIAL" shell dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity || true
