import argparse
import os
import sys
import numpy as np
from pathlib import Path

import torch
import torch.backends.cudnn as cudnn

FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]  # YOLOv5 root directory
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # add ROOT to PATH
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))  # relative

from models.common import DetectMultiBackend
from utils.datasets import IMG_FORMATS, VID_FORMATS, LoadImages, LoadStreams
from utils.general import (LOGGER, check_file, check_img_size, check_imshow, check_requirements, colorstr, cv2,
                           increment_path, non_max_suppression, print_args, scale_coords, strip_optimizer, xyxy2xywh, apply_classifier)
from utils.plots import Annotator, colors, save_one_box
from utils.torch_utils import select_device, time_sync


@torch.no_grad()
def run(
        weights=ROOT / 'best-solar.pt',  # model.pt path(s)
        source=ROOT / 'data/images',  # file/dir/URL/glob, 0 for webcam
        data=ROOT / 'data/coco128.yaml',  # dataset.yaml path
        imgsz=(640, 640),  # inference size (height, width)
        conf_thres=0.25,  # confidence threshold
        iou_thres=0.45,  # NMS IOU threshold
        max_det=1000,  # maximum detections per image
        device='',  # cuda device, i.e. 0 or 0,1,2,3 or cpu
        view_img=True,  # show results
        save_txt=False,  # save results to *.txt
        save_conf=False,  # save confidences in --save-txt labels
        save_crop=False,  # save cropped prediction boxes
        nosave=False,  # do not save images/videos
        classes=None,  # filter by class: --class 0, or --class 0 2 3
        agnostic_nms=False,  # class-agnostic NMS
        augment=False,  # augmented inference
        visualize=False,  # visualize features
        update=False,  # update all models
        project=ROOT / 'runs/detect',  # save results to project/name
        name='exp',  # save results to project/name
        exist_ok=False,  # existing project/name ok, do not increment
        line_thickness=3,  # bounding box thickness (pixels)
        hide_labels=False,  # hide labels
        hide_conf=False,  # hide confidences
        half=False,  # use FP16 half-precision inference
        dnn=False,  # use OpenCV DNN for ONNX inference
):
    if isinstance(weights, str):
        weights = weights.split()
    if isinstance(classes, str):
        classes = None if classes == '' else list(map(int, classes.split()))
    #print(f"weights: {weights}, source: {source}, data: {data}, imgsz: {imgsz}, conf_thres: {conf_thres}, iou_thres: {iou_thres}, max_det: {max_det}, device: {device}, view_img: {view_img}, save_txt: {save_txt}, save_conf: {save_conf}, save_crop: {save_crop}, nosave: {nosave}, classes: {classes}, agnostic_nms: {agnostic_nms}, augment: {augment}, visualize: {visualize}, update: {update}, project: {project}, name: {name}, exist_ok: {exist_ok}, line_thickness: {line_thickness}, hide_labels: {hide_labels}, hide_conf: {hide_conf}, half: {half}, dnn: {dnn}")

    source = str(source)
    save_img = not nosave and not source.endswith('.txt')  # save inference images
    is_file = Path(source).suffix[1:] in (IMG_FORMATS + VID_FORMATS)
    is_url = source.lower().startswith(('rtsp://', 'rtmp://', 'http://', 'https://'))
    webcam = source.isnumeric() or source.endswith('.txt') or (is_url and not is_file)
    if is_url and is_file:
        source = check_file(source)  # download

    # Directories
    save_dir = increment_path(Path(project) / name, exist_ok=exist_ok)  # increment run
    (save_dir / 'labels' if save_txt else save_dir).mkdir(parents=True, exist_ok=True)  # make dir

    # Load model
    device = select_device(device)
    model = DetectMultiBackend(weights, device=device, dnn=dnn, data=data, fp16=half)
    stride, names, pt = model.stride, model.names, model.pt
    imgsz = check_img_size(imgsz, s=stride)  # check image size

    weights_fault = "best.pt"
    model_fault = DetectMultiBackend(weights_fault, device=device, dnn=dnn, data=data, fp16=half)
    stride_fault, names_fault, pt_fault = model_fault.stride, model_fault.names, model_fault.pt

    weights_single = "best-singlemodule.pt"
    model_single = DetectMultiBackend(weights_single, device=device, dnn=dnn, data=data, fp16=half)
    stride_single, names_single, pt_single = model_single.stride, model_single.names, model_single.pt

    # Dataloader
    if webcam:
        view_img = check_imshow()
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz, stride=stride, auto=pt)
        bs = len(dataset)  # batch_size
    else:
        dataset = LoadImages(source, img_size=imgsz, stride=stride, auto=pt)
        bs = 1  # batch_size
    vid_path, vid_writer = [None] * bs, [None] * bs

    # Run inference
    model.warmup(imgsz=(1 if pt else bs, 3, *imgsz))  # warmup
    dt, seen = [0.0, 0.0, 0.0], 0
    for path, im, im0s, vid_cap, s in dataset:
        t1 = time_sync()
        im = torch.from_numpy(im).to(device)
        im = im.half() if model.fp16 else im.float()  # uint8 to fp16/32
        im /= 255  # 0 - 255 to 0.0 - 1.0
        if len(im.shape) == 3:
            im = im[None]  # expand for batch dim
        t2 = time_sync()
        dt[0] += t2 - t1

        # Inference
        visualize = increment_path(save_dir / Path(path).stem, mkdir=True) if visualize else False
        pred = model(im, augment=augment, visualize=visualize)
        t3 = time_sync()
        dt[1] += t3 - t2

        # NMS
        pred = non_max_suppression(pred, conf_thres, iou_thres, classes, agnostic_nms, max_det=max_det)
        dt[2] += time_sync() - t3

        # Second-stage classifier (optional)
        # pred = utils.general.apply_classifier(pred, classifier_model, im, im0s)

        pred_full_solar_modules = []
        prob_full_solar_modules = []

        # Process predictions
        for i, det in enumerate(pred):  # per image
            seen += 1
            if webcam:  # batch_size >= 1
                p, im0, frame = path[i], im0s[i].copy(), dataset.count
                s += f'{i}: '
            else:
                p, im0, frame = path, im0s.copy(), getattr(dataset, 'frame', 0)

            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # im.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # im.txt
            s += '%gx%g ' % im.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            imc = im0.copy() if save_crop else im0  # for save_crop
            annotator = Annotator(im0, line_width=line_thickness, example=str(names))
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                # Write results
                for *xyxy, conf, cls in reversed(det):
                    x1 = xyxy[0].detach().cpu().clone().numpy()
                    y1 = xyxy[1].detach().cpu().clone().numpy()
                    x2 = xyxy[2].detach().cpu().clone().numpy()
                    y2 = xyxy[3].detach().cpu().clone().numpy()
                    prob= conf.detach().cpu().clone().numpy().item()
                    # print(x1.ndim)
                    pred_full_solar_modules.append([float(x1), float(y1), float(x2), float(y2)])
                    prob_full_solar_modules.append(prob)

                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')

                    if save_img or save_crop or view_img:  # Add bbox to image
                        c = int(cls)  # integer class
                        label = f' {conf:.2f}'
                        annotator.box_label(xyxy, label, color=colors(c, True))
                        if save_crop:
                            save_one_box(xyxy, imc, file=save_dir / 'crops' / names[c] / f'{p.stem}.jpg', BGR=True)

            # Stream results
            im1 = annotator.result()
            if view_img:
                cv2.imshow(str(p), im1)
                cv2.waitKey(0)  # Wait until a key is pressed or the window is closed
                cv2.destroyAllWindows()

        pred = model_fault(im, augment=augment, visualize=visualize)
        t3 = time_sync()
        dt[1] += t3 - t2

        # NMS
        pred = non_max_suppression(pred, 0.01, 0.01, None, False, max_det=max_det)
        dt[2] += time_sync() - t3

        # Second-stage classifier (optional)
        # pred = utils.general.apply_classifier(pred, classifier_model, im, im0s)

        pred_fault_solar_modules = []
        prob_fault_solar_modules = []

        # Process predictions
        for i, det in enumerate(pred):  # per image
            seen += 1
            if webcam:  # batch_size >= 1
                p, im0, frame = path[i], im0s[i].copy(), dataset.count
                s += f'{i}: '
            else:
                p, im0, frame = path, im0s.copy(), getattr(dataset, 'frame', 0)

            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # im.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # im.txt
            s += '%gx%g ' % im.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            imc = im0.copy() if save_crop else im0  # for save_crop
            annotator = Annotator(im0, line_width=line_thickness, example=str(names))
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                # Write results
                for *xyxy, conf, cls in reversed(det):
                    x1 = xyxy[0].detach().cpu().clone().numpy()
                    y1 = xyxy[1].detach().cpu().clone().numpy()
                    x2 = xyxy[2].detach().cpu().clone().numpy()
                    y2 = xyxy[3].detach().cpu().clone().numpy()
                    prob= conf.detach().cpu().clone().numpy().item()
                    pred_fault_solar_modules.append([float(x1), float(y1), float(x2), float(y2)])
                    prob_fault_solar_modules.append(prob)
                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')

                    if save_img or save_crop or view_img:  # Add bbox to image
                        c = int(cls)  # integer class
                        label = f' {conf:.2f}'
                        annotator.box_label(xyxy, label, color=colors(c, True))
                        if save_crop:
                            save_one_box(xyxy, imc, file=save_dir / 'crops' / names[c] / f'{p.stem}.jpg', BGR=True)

        pred = model_single(im, augment=augment, visualize=visualize)
        t3 = time_sync()
        dt[1] += t3 - t2

        pred = model_single(im, augment=augment, visualize=visualize)
        t3 = time_sync()
        dt[1] += t3 - t2

        # NMS
        pred = non_max_suppression(pred, 0.01, 0.01, None, False, max_det=max_det)
        dt[2] += time_sync() - t3

        # Second-stage classifier (optional)
        # pred = utils.general.apply_classifier(pred, classifier_model, im, im0s)

        pred_single_solar_modules = []
        prob_single_solar_modules = []
        # Process predictions
        for i, det in enumerate(pred):  # per image
            seen += 1
            if webcam:  # batch_size >= 1
                p, im0, frame = path[i], im0s[i].copy(), dataset.count
                s += f'{i}: '
            else:
                p, im0, frame = path, im0s.copy(), getattr(dataset, 'frame', 0)

            p = Path(p)  # to Path
            save_path = str(save_dir / p.name)  # im.jpg
            txt_path = str(save_dir / 'labels' / p.stem) + ('' if dataset.mode == 'image' else f'_{frame}')  # im.txt
            s += '%gx%g ' % im.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            imc = im0.copy() if save_crop else im0  # for save_crop
            annotator = Annotator(im0, line_width=line_thickness, example=str(names))
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += f"{n} {names[int(c)]}{'s' * (n > 1)}, "  # add to string

                # Write results
                for *xyxy, conf, cls in reversed(det):
                    x1 = xyxy[0].detach().cpu().clone().numpy()
                    y1 = xyxy[1].detach().cpu().clone().numpy()
                    x2 = xyxy[2].detach().cpu().clone().numpy()
                    y2 = xyxy[3].detach().cpu().clone().numpy()
                    prob= conf.detach().cpu().clone().numpy().item()
                    pred_single_solar_modules.append([float(x1), float(y1), float(x2), float(y2)])
                    prob_single_solar_modules.append(prob)
                    
                    if save_txt:  # Write to file
                        xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                        line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                        with open(txt_path + '.txt', 'a') as f:
                            f.write(('%g ' * len(line)).rstrip() % line + '\n')

                    if save_img or save_crop or view_img:  # Add bbox to image
                        c = int(cls)  # integer class
                        label = f' {conf:.2f}'
                        annotator.box_label(xyxy, label, color=colors(c, True))
                        if save_crop:
                            save_one_box(xyxy, imc, file=save_dir / 'crops' / names[c] / f'{p.stem}.jpg', BGR=True)

            pred_single_solar_modules.sort()
            pred_full_solar_modules.sort()
            im0 = annotator.result()

            img_detection = cv2.imread(path).copy()

            for im in range(len(pred_full_solar_modules)):
                img = cv2.imread(path)
                temp, temp2 = img, img
                cv2.imshow("output", np.array(temp, dtype=np.uint8))
                cv2.waitKey(1000)  # Wait for 1 second
                # adding filled rectangle on each frame
                print(path, (int(pred_full_solar_modules[im][0]), int(pred_full_solar_modules[im][1])), (int(pred_full_solar_modules[im][2]), int(pred_full_solar_modules[im][3])))
                cv2.rectangle(temp, (int(pred_full_solar_modules[im][0]), int(pred_full_solar_modules[im][1])), (int(pred_full_solar_modules[im][2]), int(pred_full_solar_modules[im][3])), (0, 255, 0), 5)
                cv2.imshow("output", temp)
                cv2.waitKey(1000)  # Wait for 1 second

                for m in range(len(pred_single_solar_modules)):
                    mid_point_x, mid_point_y = (pred_single_solar_modules[m][0] + pred_single_solar_modules[m][2]) / 2 , (pred_single_solar_modules[m][1] + pred_single_solar_modules[m][3]) / 2
                    if ((mid_point_x > pred_full_solar_modules[im][0]) and (mid_point_x < pred_full_solar_modules[im][2]) and mid_point_y > pred_full_solar_modules[im][1] and mid_point_y < pred_full_solar_modules[im][3]):
                        cv2.rectangle(temp, (int(pred_single_solar_modules[m][0]), int(pred_single_solar_modules[m][1])), (int(pred_single_solar_modules[m][2]), int(pred_single_solar_modules[m][3])), (255, 0, 0), 2)
                        cv2.imshow("output", temp)
                        cv2.waitKey(1000)  # Wait for 1 second

                        if cv2.waitKey(1) & 0xFF == ord('s'):
                            break
                
                for ml in range(len(pred_fault_solar_modules)):
                    mid_point_fault_x, mid_point_fault_y = (pred_fault_solar_modules[ml][0] + pred_fault_solar_modules[ml][2]) / 2 , (pred_fault_solar_modules[ml][1] + pred_fault_solar_modules[ml][3]) / 2
                    if ((mid_point_fault_x > pred_full_solar_modules[im][0]) and (mid_point_fault_x < pred_full_solar_modules[im][2]) and mid_point_fault_y > pred_full_solar_modules[im][1] and mid_point_fault_y < pred_full_solar_modules[im][3]):
                        cv2.rectangle(temp2, (int(pred_full_solar_modules[im][0]), int(pred_full_solar_modules[im][1])), (int(pred_full_solar_modules[im][2]), int(pred_full_solar_modules[im][3])), (0, 0, 255), -1)
                        cv2.rectangle(temp2, (int(pred_fault_solar_modules[ml][0]), int(pred_fault_solar_modules[ml][1])), (int(pred_fault_solar_modules[ml][2]), int(pred_fault_solar_modules[ml][3])), (255, 255, 0), 5)
                        #cv2.putText(temp, str(prob_fault_solar_modules[ml]), (pred_fault_solar_modules[ml][0] - 1, pred_fault_solar_modules[ml][1] - 1), cv2.FONT_HERSHEY_COMPLEX, 1 , color=(255, 0, 0), thickness=1)
                        cv2.rectangle(img_detection, (int(pred_full_solar_modules[im][0]), int(pred_full_solar_modules[im][1])), (int(pred_full_solar_modules[im][2]), int(pred_full_solar_modules[im][3])), (0, 0, 255), -1)
                        cv2.rectangle(img_detection, (int(pred_fault_solar_modules[ml][0]), int(pred_fault_solar_modules[ml][1])), (int(pred_fault_solar_modules[ml][2]), int(pred_fault_solar_modules[ml][3])), (255, 255, 0), 5)
                        #cv2.putText(img_detection, str(prob_fault_solar_modules[ml]), (pred_fault_solar_modules[ml][0] - 1, pred_fault_solar_modules[ml][1] - 1), cv2.FONT_HERSHEY_COMPLEX, 1 , color=(255, 0, 0), thickness=1)
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        org = (int(pred_fault_solar_modules[ml][0]) - 30, int(pred_fault_solar_modules[ml][1]) - 1)
                        fontScale = 1
                        color = (255, 0, 0)
                        thickness = 2
                        cv2.putText(temp2, str((int(prob_fault_solar_modules[ml] * 10000)) / 100) + "%", org, font, fontScale, color, thickness, cv2.LINE_AA)
                        cv2.putText(img_detection, str((int(prob_fault_solar_modules[ml] * 10000)) / 100) + "%", org, font, fontScale, color, thickness, cv2.LINE_AA)
                        cv2.imshow("output", temp2)
                        cv2.waitKey(1000)  # Wait for 1 second

                if cv2.waitKey(1) & 0xFF == ord('s'):
                    break

            # Save results (image with detections)
            if save_img:
                if dataset.mode == 'image':
                    # Extract the original image name
                    base_name, ext = os.path.splitext(os.path.basename(path))
                    # Save the image with panels detections
                    cv2.imwrite(str(save_dir / f'{base_name}_panel_detection{ext}'), im1)
                    # Save the image with panel blocks detections
                    cv2.imwrite(str(save_dir / f'{base_name}_panel_block_detection{ext}'), im0)
                    # Save the image with only anomaly detections
                    cv2.imwrite(str(save_dir / f'{base_name}_anomaly_detection{ext}'), img_detection)
                else:  # 'video' or 'stream'
                    if vid_path[i] != save_path:  # new video
                        vid_path[i] = save_path
                        if isinstance(vid_writer[i], cv2.VideoWriter):
                            vid_writer[i].release()  # release previous video writer
                        if vid_cap:  # video
                            fps = vid_cap.get(cv2.CAP_PROP_FPS)
                            w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        else:  # stream
                            fps, w, h = 30, im0.shape[1], im0.shape[0]
                        save_path = str(Path(save_path).with_suffix('.mp4'))  # force *.mp4 suffix on results videos
                        vid_writer[i] = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
                    vid_writer[i].write(im0)

        # Print time (inference-only)
        LOGGER.info(f'{s}Done. ({t3 - t2:.3f}s)')

    cv2.destroyAllWindows()

    # Print results
    t = tuple(x / seen * 1E3 for x in dt)  # speeds per image
    LOGGER.info(f'Speed: %.1fms pre-process, %.1fms inference, %.1fms NMS per image at shape {(1, 3, *imgsz)}' % t)
    if save_txt or save_img:
        s = f"\n{len(list(save_dir.glob('labels/*.txt')))} labels saved to {save_dir / 'labels'}" if save_txt else ''
        LOGGER.info(f"Results saved to {colorstr('bold', save_dir)}{s}")
    if update:
        strip_optimizer(weights)  # update model (to fix SourceChangeWarning)

    saved_images = None
    saved_txts = None

    if save_img:
        image_files = list(save_dir.glob('*.jpg')) + list(save_dir.glob('*.png'))
        if image_files:
            saved_images = image_files

    if save_txt:
        txt_files = list(save_dir.glob('labels/*.txt'))
        if txt_files:
            saved_txts = txt_files

    return saved_images, saved_txts

def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', nargs='+', type=str, default=ROOT / 'best-solar.pt', help='model path(s)')
    parser.add_argument('--source', type=str, default=ROOT / 'test_folder/', help='file/dir/URL/glob, 0 for webcam')
    parser.add_argument('--data', type=str, default=ROOT / 'data.yaml', help='(optional) dataset.yaml path')
    parser.add_argument('--imgsz', '--img', '--img-size', nargs='+', type=int, default=[640], help='inference size h,w')
    parser.add_argument('--conf-thres', type=float, default=0.25, help='confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.45, help='NMS IoU threshold')
    parser.add_argument('--max-det', type=int, default=1000, help='maximum detections per image')
    parser.add_argument('--device', default='', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--view-img', action='store_true', help='show results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-conf', action='store_true', help='save confidences in --save-txt labels')
    parser.add_argument('--save-crop', action='store_true', help='save cropped prediction boxes')
    parser.add_argument('--nosave', action='store_true', help='do not save images/videos')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --classes 0, or --classes 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--visualize', action='store_true', help='visualize features')
    parser.add_argument('--update', action='store_true', help='update all models')
    parser.add_argument('--project', default=ROOT / 'detect_results', help='save results to project/name')
    parser.add_argument('--name', default='exp', help='save results to project/name')
    parser.add_argument('--exist-ok', action='store_true', help='existing project/name ok, do not increment')
    parser.add_argument('--line-thickness', default=3, type=int, help='bounding box thickness (pixels)')
    parser.add_argument('--hide-labels', default=False, action='store_true', help='hide labels')
    parser.add_argument('--hide-conf', default=False, action='store_true', help='hide confidences')
    parser.add_argument('--half', action='store_true', help='use FP16 half-precision inference')
    parser.add_argument('--dnn', action='store_true', help='use OpenCV DNN for ONNX inference')
    opt = parser.parse_args()
    opt.imgsz *= 2 if len(opt.imgsz) == 1 else 1  # expand
    print_args(vars(opt))
    return opt


def main(opt):
    check_requirements(exclude=('tensorboard', 'thop'))
    run(**vars(opt))


def run_detection(*args):
    """
    Run the detection process using the provided arguments.

    Args:
        *args: Variable number of arguments representing the detection parameters.

    Returns:
        The result of the detection process.

    Raises:
        Any exceptions that occur during the detection process.

    """
    keys = [
        "weights", "source", "data", "img_height", "img_width", "conf_thres", "iou_thres", 
        "max_det", "device", "view_img", "save_txt", "save_conf", "save_crop", 
        "nosave", "classes", "agnostic_nms", "augment", "visualize", "update", 
        "project", "name", "exist_ok", "line_thickness", "hide_labels", "hide_conf", 
        "half", "dnn", "enable_second_stage_classifier"
    ]
    kwargs = dict(zip(keys, args))

    # Combine height and width into a tuple as imgsz
    imgsz = (int(kwargs['img_height']), int(kwargs['img_width']))

    # Update the imgsz in kwargs
    kwargs['imgsz'] = imgsz

    # Remove the height and width from kwargs
    del kwargs['img_height']
    del kwargs['img_width']

    # Call the actual detection function
    return run(**kwargs)


if __name__ == "__main__":
    opt = parse_opt()
    main(opt)
