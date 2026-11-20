# 0102
guest logcat -c
guest shell 'monkey -p com.supercell.brawlstars -c android.intent.category.LAUNCHER 1' >/dev/null 2>&1
sleep 30
guest logcat -d > "$WORK/lc.txt" 2>&1
P=$(grep -a "Start proc.*brawlstars" "$WORK/lc.txt" | head -1 | sed 's/.*Start proc \([0-9]*\):.*/\1/'); echo "pid $P"
grep -a -E " $P  *[0-9]+ " "$WORK/lc.txt" | grep -a -v "AndroidRuntime: at \|Report  : at \|type=1300" | sed 's/^[0-9-]* //' | cut -c1-230 | head -70
grep -a -c "brawlstars.*has died" "$WORK/lc.txt"
