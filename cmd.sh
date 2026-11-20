# 0409
#noshot
guest logcat -d > "$WORK/lc.txt" 2>&1; wc -l "$WORK/lc.txt"
grep -a -E "FATAL|Fatal signal|System zygote died|Abort message|E AndroidRuntime|init    : .*(crash|exited|restart)|andarium|cutf|hardware" "$WORK/lc.txt" | grep -av "andarium-background" | sed 's/^[0-9-]* //' | cut -c1-260 | sort | uniq -c | sort -rn | head -40
