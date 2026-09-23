"""Technical checks only. Visual acceptance must be recorded separately."""
import argparse
import errno
import json
import socket
from pathlib import Path
from PIL import Image, ImageChops, ImageStat


def verify(source: Path, output: Path, kind: str):
    result = {"technical_success": False, "visual_status": "pending" if kind == "visual" else "not_applicable"}
    try:
        if output.is_symlink() or output.stat().st_size > 10_000_000:
            raise ValueError("Output must be a regular PNG under 10 MB")
        with Image.open(output) as im:
            im.load()
            expected = (512, 337) if kind == "technical" else (512, 673)
            if im.format != "PNG" or im.size != expected or getattr(im, "n_frames", 1) != 1:
                raise ValueError(f"Expected one PNG frame, {expected}")
            out = im.convert("RGB")
        if kind == "technical":
            with Image.open(source) as im:
                reference = im.convert("RGB").resize(expected, Image.Resampling.LANCZOS)
            mae = sum(ImageStat.Stat(ImageChops.difference(out, reference)).mean) / 3
            result["resize_mae"] = mae
            if mae > 3:
                raise ValueError("Pixels are inconsistent with proportional resizing")
        result.update(technical_success=True, width=expected[0], height=expected[1], bytes=output.stat().st_size)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        result["error"] = str(exc)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["technical", "visual"])
    p.add_argument("--source", type=Path, default=Path("/tests/source.png"))
    p.add_argument("--output", type=Path, default=Path("/workspace/output.png"))
    p.add_argument("--logs", type=Path, default=Path("/logs/verifier"))
    a = p.parse_args()
    result = verify(a.source, a.output, a.kind)
    with socket.socket() as probe:
        probe.settimeout(1)
        result["network_isolated"] = (probe.connect_ex(("1.1.1.1", 443)) == errno.ENETUNREACH
                                      and len(Path("/proc/net/route").read_text().splitlines()) == 1)
    result["technical_success"] &= result["network_isolated"]
    a.logs.mkdir(parents=True, exist_ok=True)
    (a.logs / "checks.json").write_text(json.dumps(result, indent=2))
    # Harbor reward is explicitly technical, never an inferred aesthetic score.
    (a.logs / "reward.json").write_text(json.dumps({"technical_success": int(result["technical_success"])}))
    print(json.dumps(result))
