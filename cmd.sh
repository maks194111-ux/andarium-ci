# 0001
cat "$WORK/live-package.log"
UA="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
curl -sIL -m 40 -A "$UA" "https://d.apkpure.com/b/XAPK/com.supercell.brawlstars?version=latest" | grep -i -E "^HTTP|content-length|location" | cut -c1-160
df -h "$WORK" | tail -1
