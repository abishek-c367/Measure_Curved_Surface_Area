"""Extract one random frame from each of 200 equal video intervals."""

import argparse
import random
from pathlib import Path

import cv2


DEFAULT_VIDEO = Path("data/videos/3D reconstruction .mp4")
DEFAULT_OUTPUT = Path("data/images")
DEFAULT_FRAME_COUNT = 200


def extract_frames(
    video_path: Path,
    output_dir: Path,
    frame_count: int = DEFAULT_FRAME_COUNT,
    seed: int | None = None,
) -> list[Path]:
    """Extract randomly selected frames distributed across equal time intervals."""
    if frame_count < 1:
        raise ValueError("frame_count must be at least 1")
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames < frame_count:
            raise RuntimeError(
                f"Video contains {total_frames} frames, but {frame_count} are required."
            )

        rng = random.Random(seed)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_paths: list[Path] = []

        for interval in range(frame_count):
            start = (interval * total_frames) // frame_count
            end = ((interval + 1) * total_frames) // frame_count - 1
            frame_number = rng.randint(start, end)

            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            success, frame = capture.read()
            if not success:
                raise RuntimeError(
                    f"Could not read frame {frame_number} from {video_path}."
                )

            output_path = output_dir / f"frame_{interval + 1:04d}.jpg"
            if not cv2.imwrite(str(output_path), frame):
                raise RuntimeError(f"Could not write extracted frame: {output_path}")
            output_paths.append(output_path)

        return output_paths
    finally:
        capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract one random frame from each of 200 equal time intervals "
            "into data/images."
        )
    )
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for reproducible frame selection.",
    )
    args = parser.parse_args()

    output_paths = extract_frames(args.video, args.output, seed=args.seed)
    print(f"Extracted {len(output_paths)} frames to {args.output}")


if __name__ == "__main__":
    main()
