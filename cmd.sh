# 0005
#noshot
for i in $(seq 1 50); do grep -q 20 "$WORK/install.log" && break; sleep 5; done; cat "$WORK/install.log"; guest shell 'df -h /data | tail -1; pm list packages | grep supercell; cat /proc/loadavg'
