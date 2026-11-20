# 0107
guest shell 'input keyevent KEYCODE_ENTER; sleep 5; input keyevent KEYCODE_DPAD_RIGHT; sleep 2'
rec on; mark "SuperTuxKart: race loads"
guest shell 'input keyevent KEYCODE_ENTER'; sleep 35
mark "SuperTuxKart: driving"
guest shell 'for n in 1 2 3 4; do input swipe 395 1024 395 1024 5000; input swipe 395 1024 250 1150 2500; input swipe 395 1024 395 1024 3000; input swipe 395 1024 540 1150 2500; done'
mark "SuperTuxKart: driving ends"; rec off
ls -la "$WORK"/live.frames
guest shell 'cat /proc/loadavg'
