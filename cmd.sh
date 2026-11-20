# 0013
guest shell 'wm size; dumpsys activity activities | grep -m1 topResumed; top -b -n 1 -m 6 -o %CPU,NAME -s 1 | tail -7; cat /proc/loadavg; dumpsys window | grep -E "mCurrentFocus|ANR" | head -3; dumpsys SurfaceFlinger --latency-clear >/dev/null; logcat -d -t 300 | grep -iE "ANR in|supertux|SDL|Input.*drop" | tail -12' 2>&1 | cut -c1-200
guest shell 'input keyevent KEYCODE_DPAD_RIGHT; sleep 1; input keyevent KEYCODE_DPAD_RIGHT'; sleep 3
