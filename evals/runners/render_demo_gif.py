from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "docs" / "images"
FRAME_PATHS = (
    IMAGE_DIR / "ui-inbox.png",
    IMAGE_DIR / "ui-risk.png",
    IMAGE_DIR / "ui-proposal.png",
)
OUTPUT_PATH = IMAGE_DIR / "gigbid-demo.gif"
FRAME_WIDTH = 900
FRAME_DURATION_MS = 10_000


def main() -> None:
    frames = []
    for frame_path in FRAME_PATHS:
        with Image.open(frame_path) as image:
            frame = image.convert("RGB")
            height = round(frame.height * FRAME_WIDTH / frame.width)
            frame = frame.resize((FRAME_WIDTH, height), Image.Resampling.LANCZOS)
            frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE))

    frames[0].save(
        OUTPUT_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=True,
    )
    print(f"Rendered 30-second demo GIF: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
