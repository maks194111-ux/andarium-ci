# 0109
#quit
#noshot
guest shell 'dumpsys gfxinfo org.supertuxkart.stk | grep -E "Total frames|Janky frames:|50th|90th|95th" | head -8; dumpsys SurfaceFlinger | grep -m3 -iE "org.supertuxkart.*fps|refresh-rate|activeMode"'
echo bye
