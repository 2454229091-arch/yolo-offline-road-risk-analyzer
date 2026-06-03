"""Command-line entry point for YOLO offline road-scene risk analysis."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a road video and generate YOLO-based risk reports.")
    parser.add_argument("--video", required=True, help="Path to the input road video.")
    parser.add_argument("--output", "--output-dir", dest="output_dir", default="outputs", help="Output directory.")
    parser.add_argument("--frame-interval", "--interval", dest="interval", type=float, default=1.0)
    parser.add_argument("--confidence", "--conf", dest="confidence", type=float, default=0.35)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--render-video", action="store_true", help="Render an annotated MP4 instead of sampled reports.")
    parser.add_argument("--render-stride", type=int, default=1, help="Run detection every N frames while rendering.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: video file not found: {video_path}")
        print("Place a driving video under data/raw/ and pass it with --video.")
        return 1

    if args.render_video:
        return run_video_render(args, video_path)

    try:
        import cv2

        from src.detector import RoadSceneDetector
        from src.report_generator import build_summary, write_reports
        from src.risk_rules import evaluate_risks
        from src.utils import (
            calculate_brightness,
            draw_detections,
            draw_event_text,
            draw_risk_zone,
            ensure_dir,
            save_annotated_frame,
            summarize_detected_objects,
        )
    except (ImportError, RuntimeError) as exc:
        print(f"Error: {exc}")
        print("Install dependencies with: python -m pip install -r requirements.txt")
        return 1

    output_dir = ensure_dir(args.output_dir)
    annotated_dir = ensure_dir(output_dir / "annotated_frames")
    detector = RoadSceneDetector(model_path=args.model, confidence=args.confidence)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        print(f"Error: unable to open video file: {video_path}")
        return 1

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_step = max(1, int(round(fps * args.interval)))

    events: list[dict[str, object]] = []
    detected_object_counts: Counter[str] = Counter()
    total_frames_analyzed = 0
    frame_number = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_number % frame_step != 0:
            frame_number += 1
            continue

        total_frames_analyzed += 1
        timestamp_sec = round(frame_number / fps, 2)
        brightness = round(calculate_brightness(frame), 2)
        detections = detector.detect(frame)
        detected_object_counts.update(str(detection["class_name"]) for detection in detections)
        frame_events = evaluate_risks(detections, brightness)

        evidence_image = ""
        if frame_events:
            annotated = frame.copy()
            draw_risk_zone(annotated)
            draw_detections(annotated, detections)
            draw_event_text(annotated, frame_events)
            evidence_image = str(save_annotated_frame(annotated, annotated_dir, frame_number)).replace("\\", "/")

        detected_objects = summarize_detected_objects(detections)
        for event in frame_events:
            events.append(
                {
                    "video_name": video_path.name,
                    "frame_number": frame_number,
                    "timestamp_sec": timestamp_sec,
                    "event_type": event["event_type"],
                    "risk_level": event["risk_level"],
                    "detected_objects": detected_objects,
                    "object_count": len(detections),
                    "brightness": brightness,
                    "evidence_image": evidence_image,
                    "tester_note": event["tester_note"],
                }
            )
        frame_number += 1

    capture.release()
    summary = build_summary(
        video_path.name,
        total_frames_analyzed,
        events,
        detected_object_counts=dict(sorted(detected_object_counts.items())),
        analysis_interval_sec=args.interval,
        model=args.model,
        confidence_threshold=args.confidence,
    )
    report_paths = write_reports(events, summary, output_dir)
    print("Analysis complete")
    print(f"Total frames analyzed: {total_frames_analyzed}")
    print(f"Total risk events: {len(events)}")
    print(f"CSV log saved to: {report_paths['csv']}")
    print(f"Excel report saved to: {report_paths['excel']}")
    print(f"Summary JSON saved to: {report_paths['summary']}")
    print(f"HTML report saved to: {report_paths['html']}")
    return 0


def run_video_render(args: argparse.Namespace, video_path: Path) -> int:
    try:
        from src.detector import RoadSceneDetector
        from src.risk_rules import evaluate_risks
        from src.utils import calculate_brightness
        from src.video_renderer import render_video_with_detector
    except (ImportError, RuntimeError) as exc:
        print(f"Error: {exc}")
        print("Install dependencies with: python -m pip install -r requirements.txt")
        return 1

    output_path = Path(args.output_dir) / "annotated_video.mp4"
    detector = RoadSceneDetector(model_path=args.model, confidence=args.confidence)
    try:
        result = render_video_with_detector(
            video_path=video_path,
            output_path=output_path,
            detector=detector,
            evaluate_risks=evaluate_risks,
            calculate_brightness=calculate_brightness,
            frame_stride=args.render_stride,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    print("Annotated video render complete")
    print(f"Processed frames: {result['processed_frames']}")
    print(f"Risk overlay frames: {result['risk_frames']}")
    print(f"Annotated video saved to: {result['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
