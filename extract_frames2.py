import cv2
import os

VIDEO = r"C:\Users\馒头\Documents\Tencent Files\3318500896\nt_qq\nt_data\Video\2026-08\Ori\2aded9ccda6e18bc8f84ec53920a2400.mp4"
OUT = r"D:\python\video_frames2"
os.makedirs(OUT, exist_ok=True)

# Target timestamps (seconds): desktop segments + missing subtitle gap
times = [5, 6, 7, 8, 9, 16, 17, 18, 19, 20, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39]

cap = cv2.VideoCapture(VIDEO)
if not cap.isOpened():
    print("ERROR: cannot open video")
    raise SystemExit(1)

fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"fps={fps}, total_frames={total}, duration={total/fps:.1f}s")

for t in times:
    frame_idx = int(t * fps)
    if frame_idx >= total:
        print(f"skip {t}s: beyond end")
        continue
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    if not ok:
        print(f"skip {t}s: read failed")
        continue
    # Downscale if huge to keep file small
    h, w = frame.shape[:2]
    if w > 1280:
        scale = 1280 / w
        frame = cv2.resize(frame, (1280, int(h * scale)))
    path = os.path.join(OUT, f"t{t:02d}s.jpg")
    cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"saved {path}")

cap.release()
print("done")
