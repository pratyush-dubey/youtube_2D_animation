"""Conservative, reproducible face-continuity check for reconstruction assets."""
from __future__ import annotations

import json
from pathlib import Path

import cv2


def inspect_identity(reference_path: Path, candidate_path: Path, output_path: Path | None = None) -> dict:
    reference = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
    candidate = cv2.imread(str(candidate_path), cv2.IMREAD_GRAYSCALE)
    if reference is None or candidate is None:
        raise FileNotFoundError(reference_path if reference is None else candidate_path)
    ref_face = _largest_upper_face(reference)
    candidate_face = _largest_upper_face(candidate)
    if ref_face is None or candidate_face is None:
        report = {"passed": False, "reason": "frontal face not detected in both images"}
    else:
        ref_crop = _crop(reference, ref_face)
        candidate_crop = _crop(candidate, candidate_face)
        orb = cv2.ORB_create(1000)
        ref_points, ref_desc = orb.detectAndCompute(ref_crop, None)
        candidate_points, candidate_desc = orb.detectAndCompute(candidate_crop, None)
        good = []
        if ref_desc is not None and candidate_desc is not None:
            pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ref_desc, candidate_desc, k=2)
            good = [near for near, far in pairs if near.distance < 0.78 * far.distance]
        denominator = max(1, min(len(ref_points), len(candidate_points)))
        ratio = len(good) / denominator
        report = {
            "passed": len(good) >= 45 and ratio >= 0.10,
            "reference_face": list(map(int, ref_face)),
            "candidate_face": list(map(int, candidate_face)),
            "reference_keypoints": len(ref_points),
            "candidate_keypoints": len(candidate_points),
            "good_feature_matches": len(good),
            "feature_match_ratio": round(ratio, 4),
            "method": "Haar upper-frame face localization plus ORB ratio-test matches",
            "limitation": "This rejects obvious drift but is not biometric identification or proof of identity.",
        }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _largest_upper_face(gray):
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=4, minSize=(40, 40))
    upper = [tuple(map(int, face)) for face in faces if face[1] < gray.shape[0] * 0.5]
    return max(upper, key=lambda face: face[2] * face[3]) if upper else None


def _crop(gray, face):
    x, y, width, height = face
    crop = gray[y:y + height, x:x + width]
    return cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA)
