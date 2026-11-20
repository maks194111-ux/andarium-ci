# 0007
#noshot
rec off
guest logcat -d -t 4000 > "$WORK/lc.txt" 2>&1
grep -a -n -iE "brawl|supercell" "$WORK/lc.txt" | grep -a -iE "fatal|signal|died|kill|exception|crash|abort|error|unsatisf|egl|gles|exit|tombstone|start proc|Force" | cut -c1-260 | tail -40
echo ----; grep -a -B2 -A25 -E "Fatal signal|FATAL EXCEPTION" "$WORK/lc.txt" | cut -c1-220 | tail -70
