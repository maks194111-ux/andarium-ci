# 0018
mark "SuperTuxKart: driving"
guest shell 'for n in 1 2 3 4 5 6 7 8 9 10 11 12; do input swipe 395 1024 395 1024 5000; input swipe 395 1024 250 1150 2500; input swipe 395 1024 395 1024 3000; input swipe 395 1024 540 1150 2500; done'
mark "SuperTuxKart: driving ends"
guest shell 'cat /proc/loadavg; top -b -n 1 -m 5 -o %CPU,NAME -s 1 | tail -5'
