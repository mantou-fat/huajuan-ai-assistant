import cv2
from ultralytics import YOLO

model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture(0) 
count = 0      # 0 = 默认摄像头
drawn = None
while True:
    ok, frame = cap.read()
    if not ok:
        break
    count += 1
    if count % 3 == 0:  
        results = model.predict(frame, verbose=False, imgsz=320)
        drawn = results[0].plot()  # plot()：把框直接画在这一帧上
    if drawn is not None:                   # 没检测的那 2 帧，接着显示上一张画好的
        cv2.imshow("huajuan eyes", drawn)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break       