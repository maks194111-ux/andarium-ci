# 0410
#noshot
guest logcat -d > "$WORK/lc.txt" 2>&1
grep -a -E "FATAL EXCEPTION|Fatal signal|System zygote died|Abort message|E AndroidRuntime|\*\*\* |Exit zygote|System server|SystemServer: |Shutting down VM|Watchdog" "$WORK/lc.txt" | sed 's/^[0-9-]* //' | cut -c1-300 | tail -30
