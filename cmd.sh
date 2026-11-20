# 0006
rec on; mark "Brawl Stars starts"
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' 2>&1 | tail -2
sleep 40
guest shell 'dumpsys activity activities | grep -m2 -E "ResumedActivity|topResumed"; cat /proc/loadavg; pidof com.supercell.brawlstars'
