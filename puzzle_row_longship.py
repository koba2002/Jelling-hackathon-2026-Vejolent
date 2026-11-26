# Row the longship  (MediaPipe Pose, no training)
# Grab an invisible oar with both hands and row: hands down by your knees,
# then pull them up to your chest. Three strokes and the ship arrives.
# Needs pose_landmarker_lite.task (same model as the shield wall)
#   python puzzle_row_longship.py            (press q to quit)
#   CAMERA=2 python puzzle_row_longship.py   (use camera 2)
#   STROKES=5 python puzzle_row_longship.py  (make it harder)
#
# Tells game.py when it is solved, then closes by itself.
# Works on its own too, without game.py running.

import os
import time
import urllib.request

import cv2
import mediapipe as mp

STROKES_NEEDED = int(os.environ.get("STROKES", "3"))
CAMERA = int(os.environ.get("CAMERA", "0"))
GAME_URL = "http://localhost:8000"

# Hand height is measured below the shoulders, in shoulder widths.
DOWN = 1.6        # hands lower than this = "reach" (arms down, by the knees)
UP = 0.6          # hands higher than this = "pull" (hands at the chest)
TOGETHER = 0.8    # both hands must be at about the same height (oar held with two hands)


def tell_game(event):
    """Send 'solved' or 'failed' to game.py. Does nothing if the game is not running."""
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
strokes = 0
stage = "reach"           # what we wait for next: "reach" (hands down) then "pull" (hands up)
unlocked_at = None

while True:
    ok, frame = cap.read()
    if not ok:
        print(f"Camera {CAMERA} gives no picture. Try CAMERA=1 or CAMERA=2")
        break
    frame = cv2.flip(frame, 1)                    # mirror, so it feels natural
    h, w = frame.shape[:2]

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

    # Follow the rower closest to the camera (widest shoulders)
    rower = None
    for person in result.pose_landmarks:
        width = abs(person[11].x - person[12].x)
        if rower is None or width > rower[0]:
            rower = (width, person)

    hint = "Step in front of the camera"
    level = None
    if rower:
        width, p = rower
        sh_y = (p[11].y + p[12].y) / 2                 # shoulders
        wl, wr = p[15], p[16]                          # wrists
        if wl.visibility > 0.5 and wr.visibility > 0.5 and width > 0.03:
            level = ((wl.y + wr.y) / 2 - sh_y) / width   # how far below the shoulders
            together = abs(wl.y - wr.y) / width < TOGETHER
            for pt in (p[11], p[12], wl, wr):
                cv2.circle(frame, (int(pt.x * w), int(pt.y * h)), 8, (40, 42, 142), -1)
            cv2.line(frame, (int(wl.x * w), int(wl.y * h)), (int(wr.x * w), int(wr.y * h)),
                     (60, 120, 180), 6)                # the oar

            if not together:
                hint = "Hold the oar with BOTH hands"
            elif stage == "reach":
                hint = "Reach: hands down by your knees"
                if level > DOWN:
                    stage = "pull"
            else:
                hint = "Pull: hands up to your chest!"
                if level < UP:
                    stage = "reach"
                    strokes += 1
                    print(f"Stroke {strokes}/{STROKES_NEEDED}")
                    if strokes >= STROKES_NEEDED and not unlocked_at:
                        unlocked_at = time.time()
                        print("UNLOCKED: the longship reaches London!")
                        tell_game("solved")
        else:
            hint = "Show both hands to the camera"

    # Progress: oars along the bottom
    for i in range(STROKES_NEEDED):
        x = 30 + i * 70
        colour = (40, 42, 142) if i < strokes else (170, 170, 170)
        cv2.rectangle(frame, (x, h - 60), (x + 50, h - 20), colour, -1)
    cv2.putText(frame, f"Strokes {strokes}/{STROKES_NEEDED}", (30, h - 75),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(frame, hint, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    if unlocked_at:
        cv2.putText(frame, "LAND HO!", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 220, 0), 5)

    cv2.imshow("Row the longship", frame)
    if cv2.waitKey(1) == ord("q"):
        break
    if unlocked_at and time.time() - unlocked_at > 1.5:
        break

cap.release()
cv2.destroyAllWindows()
