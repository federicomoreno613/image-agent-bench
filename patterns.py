"""Small, shared command recipe. Both agents can use this exact procedure."""
import argparse
import subprocess
from pathlib import Path


def proportional_width(source: Path, output: Path, width: int):
    if not 1 <= width <= 4096 or not source.is_file():
        raise ValueError("Expected an existing input and width in [1, 4096]")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["convert", str(source), "-auto-orient", "-resize", str(width), str(output)],
        check=True, timeout=30,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["proportional-width"])
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--width", type=int, required=True)
    a = p.parse_args()
    proportional_width(a.input, a.output, a.width)
