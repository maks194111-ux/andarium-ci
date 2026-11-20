# 0108
#noshot
rec on; mark "SuperTuxKart: driving, second attempt"
guest shell 'input motionevent DOWN 395 990; sleep 8'
shot 0108a
guest shell 'input motionevent MOVE 300 1050; sleep 3; input motionevent MOVE 395 990; sleep 6; input motionevent UP 395 990'
shot 0108b
guest shell 'input keyevent --longpress KEYCODE_DPAD_UP; input keyevent --longpress KEYCODE_DPAD_UP; input keyevent --longpress KEYCODE_DPAD_UP' 2>&1 | tail -2
shot 0108c
rec off; ls -la "$WORK"/live.frames
