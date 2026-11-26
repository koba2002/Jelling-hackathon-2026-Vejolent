# Become the picture  (MediaPipe Pose, no training)  - the Tokyo challenge
# The Tokyo copy only reproduced the PICTURE sides of the stone. The main picture is a
# figure with its arms spread wide inside the knotwork. So: become the picture.
# Spread your arms straight out to the sides, at shoulder height, and hold still.
# Needs pose_landmarker_lite.task (same model as the rowing puzzle)
#   python puzzle_become_picture.py            (press q to quit)
#   CAMERA=2 python puzzle_become_picture.py   (use camera 2)
#
# Tells game.py when it is solved, then closes by itself.

import os
import time
import urllib.request

import cv2
import mediapipe as mp

CAMERA = int(os.environ.get("CAMERA", "0"))
GAME_URL = "http://localhost:8000"
HOLD_SECONDS = 3.0
WIDE = 2.4        # wrists at least this many shoulder widths apart (arms spread)
LEVEL = 0.7       # wrists at most this far above/below the shoulders, in shoulder widths
STILL = 0.25      # how much the wrists may move while holding (shoulder widths)


def tell_game(event):
    try:
        urllib.request.urlopen(f"{GAME_URL}/{event}", timeout=1)
    except Exception:
        pass


vision = mp.tasks.vision
options = vision.PoseLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path="pose_landmarker_lite.task"),
    num_poses=4)
landmarker = vision.PoseLandmarker.create_from_options(options)

cap = cv2.VideoCapture(CAMERA)
held_since = None
anchor = None             # wrist positions when the hold started
unlocked_at = None

while True:
    ok, frame = cap.read()
    if not ok:
        print(f"Camera {CAMERA} gives no picture. Try CAMERA=1 or CAMERA=2")
        break
    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

    person = None
    for p in result.pose_landmarks:                      # the person closest to the camera
        width = abs(p[11].x - p[12].x)
        if person is None or width > person[0]:
            person = (width, p)

    hint = "Step in front of the camera"
    pose_ok = False
    if person:
        width, p = person
        ls, rs, lw, rw = p[11], p[12], p[15], p[16]
        if lw.visibility > 0.5 and rw.visibility > 0.5 and width > 0.03:
            sh_y = (ls.y + rs.y) / 2
            spread = abs(lw.x - rw.x) / width
            level = max(abs(lw.y - sh_y), abs(rw.y - sh_y)) / width
            # draw the figure: shoulders to wrists
            for a, b in ((lw, ls), (ls, rs), (rs, rw)):
                cv2.line(frame, (int(a.x * w), int(a.y * h)), (int(b.x * w), int(b.y * h)), (40, 42, 142), 6)
            if spread < WIDE:
                hint = "Spread your arms wide, like the figure"
            elif level > LEVEL:
                hint = "Arms at shoulder height"
            else:
                pose_ok = True
                now = (lw.x, lw.y, rw.x, rw.y)
                if anchor and max(abs(a - b) for a, b in zip(now, anchor)) / width > STILL:
                    held_since, anchor = None, None     # moved too much: start again
                    hint = "Hold still..."
                else:
                    anchor = anchor or now
                    held_since = held_since or time.time()
                    hint = "Hold still. You are the picture."
        else:
            hint = "Show both hands to the camera"
    if not pose_ok:
        held_since, anchor = None, None

    progress = min(1.0, (time.time() - held_since) / HOLD_SECONDS) if held_since else 0.0
    if progress >= 1.0 and not unlocked_at:
        unlocked_at = time.time()
        print("UNLOCKED: the picture is complete")
        tell_game("solved")

    cv2.rectangle(frame, (30, h - 50), (w - 30, h - 25), (90, 90, 90), -1)
    cv2.rectangle(frame, (30, h - 50), (30 + int((w - 60) * progress), h - 25), (40, 42, 142), -1)
    cv2.putText(frame, hint, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    if unlocked_at:
        cv2.putText(frame, "THE STONE REMEMBERS YOU", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 220, 0), 4)

    cv2.imshow("Become the picture", frame)
    if cv2.waitKey(1) == ord("q"):
        break
    if unlocked_at and time.time() - unlocked_at > 1.5:
        break

cap.release()
cv2.destroyAllWindows()
