"""TRAFFICINTEL AI - Computer Vision Pipeline

Ingests camera frames, applies object detection and tracking, maps to approaches/lanes,
and aggregates traffic state parameters.
Never fabricates bounding boxes or tracks.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import math


class DetectedObject:
    def __init__(self, class_name: str, confidence: float, bbox: List[float], track_id: Optional[int] = None):
        self.class_name = class_name
        self.confidence = confidence
        self.bbox = bbox  # [x, y, w, h] normalized
        self.track_id = track_id


class ComputerVisionPipeline:
    """Production vision pipeline interface."""

    def __init__(self, camera_id: str, model_name: str = "torchvision_fasterrcnn_resnet50"):
        self.camera_id = camera_id
        self.model_name = model_name
        self.active_tracks: Dict[int, Dict[str, Any]] = {}
        self.next_track_id = 1

    def process_frame(self, frame_timestamp: datetime, detections: List[DetectedObject]) -> Dict[str, Any]:
        """Processes real detections from an ingested video frame.

        Updates tracking trajectories and estimates queue and speed from actual observation deltas.
        """
        now = frame_timestamp or datetime.now(timezone.utc)
        current_tracked_vehicles = []
        stopped_vehicles = 0

        for det in detections:
            track_id = det.track_id or self.next_track_id
            if not det.track_id:
                self.next_track_id += 1

            # Update or register track
            if track_id not in self.active_tracks:
                self.active_tracks[track_id] = {
                    "start_time": now,
                    "last_seen": now,
                    "positions": [det.bbox],
                    "class_name": det.class_name,
                    "stopped_duration_sec": 0.0
                }
            else:
                track = self.active_tracks[track_id]
                prev_bbox = track["positions"][-1]
                dt = (now - track["last_seen"]).total_seconds()
                track["positions"].append(det.bbox)
                track["last_seen"] = now

                # Estimate motion delta (euclidean distance of center)
                dx = (det.bbox[0] + det.bbox[2]/2) - (prev_bbox[0] + prev_bbox[2]/2)
                dy = (det.bbox[1] + det.bbox[3]/2) - (prev_bbox[1] + prev_bbox[3]/2)
                dist = math.sqrt(dx*dx + dy*dy)

                if dist < 0.02 and dt > 0:  # Minimal displacement threshold
                    track["stopped_duration_sec"] += dt
                    if track["stopped_duration_sec"] > 3.0:
                        stopped_vehicles += 1

            current_tracked_vehicles.append({
                "track_id": track_id,
                "class_name": det.class_name,
                "confidence": det.confidence,
                "bbox": det.bbox
            })

        # Purge stale tracks older than 10 seconds
        cutoff = (now - datetime.fromtimestamp(now.timestamp() - 10, timezone.utc)).total_seconds()
        to_remove = [tid for tid, t in self.active_tracks.items() if (now - t["last_seen"]).total_seconds() > 10.0]
        for tid in to_remove:
            del self.active_tracks[tid]

        return {
            "camera_id": self.camera_id,
            "timestamp": now.isoformat(),
            "detected_count": len(detections),
            "queued_vehicles_count": stopped_vehicles,
            "tracked_objects": current_tracked_vehicles,
            "pipeline_model": self.model_name
        }
