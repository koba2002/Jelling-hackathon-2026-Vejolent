# The silent oath  (MediaPipe Gestures, no training)
# Show the guard the secret hand signs in the right order:
# thumbs up, victory, open palm. A wrong sign starts it over.
# Needs gesture_recognizer.task (see INSTALL.txt)
#   python puzzle_silent_oath.py            (press q to quit)
#
# Harald's Messengers version: tells game.py when the puzzle is solved,
# then closes by itself. Works on its own too, without game.py running.
#   CAMERA=1 python puzzle_silent_oath.py   (use camera 1, e.g. a USB webcam)

import os
import time
import urllib.request

import cv2
import mediapipe as mp

SECRET = ["Thumb_Up", "Victory", "Open_Palm"]   # signs MediaPipe already knows
HOLD_SECONDS = 0.8                              # hold each sign this long
CAMERA = int(os.environ.get("CAMERA", "0"))     # 0 = first camera, 1 = second
GAME_URL = "http://localhost:8000"              # where game.py is listening


def tell_game(event):
    """Send 'solved' or 'failed' to game.py. Does nothing if the game is not running."""
    try:
        urllib.request.urlopen(f"{GAME_URL}/{event}", timeout=1)
    except Exception:
        pass


vision = mp.tasks.vision
options = vision.GestureRecognizerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path="gesture_recognizer.task"))
recognizer = vision.GestureRecognizer.create_from_options(options)

cap = cv2.VideoCapture(CAMERA)
step = 0                    # how many signs are done
last_sign, since = "None", time.time()
message = "Show the first sign"
unlocked_at = None          # when the puzzle was solved

while True:
    ok, frame = cap.read()
    if not ok:
        print(f"Camera {CAMERA} gives no picture. Try CAMERA=1")
        break
    h, w = frame.shape[:2]

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

    sign = "None"
    if result.gestures:                                  # the best guess for the first hand
        sign = result.gestures[0][0].category_name
        for point in result.hand_landmarks[0]:
            cv2.circle(frame, (int(point.x * w), int(point.y * h)), 4, (0, 255, 0), -1)

    if sign != last_sign:                                # a new sign: start the hold timer
        last_sign, since = sign, time.time()
    held = time.time() - since > HOLD_SECONDS

    # The rule: each sign in the secret order, held for a moment
    if held and step < len(SECRET):
        if sign == SECRET[step]:
            step += 1
            message = f"Good! {step} of {len(SECRET)}"
            if step == len(SECRET):
                message = "UNLOCKED: the guard lets you pass!"
                print(message)
                tell_game("solved")                      # the badge lights up, the story plays
                unlocked_at = time.time()
        elif sign != "None" and (step == 0 or sign != SECRET[step - 1]):
            if step > 0:                                 # only report real mistakes, once
                tell_game("failed")
            step = 0
            message = "Wrong sign, start over"

    cv2.putText(frame, message, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1,
                (0, 255, 0) if step == len(SECRET) else (0, 255, 255), 2)
    cv2.putText(frame, f"Seeing: {sign}", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    cv2.imshow("The silent oath", frame)
    if cv2.waitKey(1) == ord("q"):
        break
    if unlocked_at and time.time() - unlocked_at > 1.5:  # show UNLOCKED briefly, then close
        break

cap.release()
cv2.destroyAllWindows()
