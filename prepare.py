"""Fetch the official data and build two small, isolated Harbor tasks."""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parent
BASE = "https://people.csail.mit.edu/mrub/retargetme/"
ARCHIVE = BASE + "download/dataset-20110512.zip"
OPS = ["cr", "sv", "multiop", "sc", "scl", "sm", "sns", "warp"]
COMMON = """Input: /workspace/source.png (1024 x 673). Save a single PNG at
/workspace/output.png. Use existing pixels, no image generation. Available:
ImageMagick convert/identify, Python 3 and Pillow. You may inspect the image.
Shared recipe: python3 /app/patterns.py proportional-width --input
/workspace/source.png --output /workspace/output.png --width WIDTH.
This recipe preserves the full image and aspect ratio. Use it only if suitable.
"""
INSTRUCTIONS = {
    "technical": "Resize the image to width 512 pixels while preserving its original aspect ratio. Do not crop or add borders.\n" + COMMON,
    "visual": "Reduce ONLY the width to 512 pixels; keep height 673 pixels. Preserve the main person and her natural proportions. Use the entire output canvas: no borders or letterboxing. Choose the crop or image operation by inspecting the image. Do not simply squash it horizontally.\n" + COMMON,
}
DOCKERFILE = """FROM debian:bookworm-slim
RUN printf 'Acquire::http::Pipeline-Depth "0";\\nAcquire::http::No-Cache "true";\\n' > /etc/apt/apt.conf.d/99-no-cache
RUN apt-get update && apt-get install -y --no-install-recommends imagemagick python3 python3-pil && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home agent && mkdir /workspace /app && chown agent:agent /workspace
COPY source.png /workspace/source.png
COPY patterns.py /app/patterns.py
WORKDIR /workspace
"""


def fetch(url, target):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        print(f"Downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=240) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out)
        temporary.replace(target)


def main():
    archive = ROOT / ".cache/retargetme-20110512.zip"
    fetch(ARCHIVE, archive)
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    names = ["DKNYgirl.png"] + [f"DKNYgirl_0.50_{op}.png" for op in OPS]
    entries = []
    with zipfile.ZipFile(archive) as z:
        for name in names:
            content = z.read("DKNYgirl/" + name)  # exact allowlist; no archive paths extracted
            dest = data / name
            dest.write_bytes(content)
            with Image.open(dest) as im:
                im.verify()
                dimensions = list(im.size)
            expected = [1024, 673] if name == "DKNYgirl.png" else [512, 673]
            if dimensions != expected:
                raise ValueError(f"Official dimensions changed: {name}: {dimensions}")
            entries.append({"file": name, "archive_member": "DKNYgirl/" + name,
                            "sha256": hashlib.sha256(content).hexdigest(), "dimensions": dimensions})
    votes = {}
    for mode in ["ref", "blind"]:
        target = data / f"subjData-{mode}_37.mat"
        fetch(BASE + "download/" + target.name, target)
        values = loadmat(target, simplify_cells=True)["subjData"]
        matching = [i for i, name in enumerate(values["datasetNames"]) if name == "DKNYgirl_0.50"]
        if len(matching) != 1:
            raise ValueError("Missing or ambiguous DKNYgirl votes")
        votes[mode] = dict(zip(OPS, map(int, values["data"][matching[0]]), strict=True))
    manifest = {"dataset": "RetargetMe", "case": "DKNYgirl_0.50", "archive_url": ARCHIVE,
                "files": entries, "votes": votes, "operators_in_study": OPS,
                "reference_note": "Historical preferences among eight existing results; not a score for new outputs."}
    manifest_path = ROOT / "dataset.lock.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("Dataset differs from frozen manifest; review before updating")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for kind, instruction in INSTRUCTIONS.items():
        task = ROOT / "tasks" / ("dkny-" + kind)
        for sub in ["environment", "tests", "solution"]:
            (task / sub).mkdir(parents=True, exist_ok=True)
        (task / "instruction.md").write_text(instruction)
        (task / "task.toml").write_text('schema_version = "1.3"\n[metadata]\ncategory = "image-retargeting"\n[agent]\ntimeout_sec = 600\nuser = "agent"\n[environment]\ncpus = 2\nmemory_mb = 2048\n[verifier]\ntimeout_sec = 60\nuser = "root"\n')
        # Native Docker isolation works on macOS without Harbor's Linux egress controller.
        (task / "environment/docker-compose.yaml").write_text("services:\n  main:\n    network_mode: none\n")
        (task / "environment/Dockerfile").write_text(DOCKERFILE)
        shutil.copyfile(data / "DKNYgirl.png", task / "environment/source.png")
        shutil.copyfile(ROOT / "patterns.py", task / "environment/patterns.py")
        shutil.copyfile(ROOT / "verify.py", task / "tests/verify.py")
        shutil.copyfile(data / "DKNYgirl.png", task / "tests/source.png")
        (task / "tests/test.sh").write_text(f"#!/bin/sh\nset -eu\npython3 /tests/verify.py {kind}\n")
        if kind == "technical":
            solution = "python3 /app/patterns.py proportional-width --input /workspace/source.png --output /workspace/output.png --width 512"
        else:
            # Oracle checks plumbing only, not whether future visual outputs are good.
            shutil.copyfile(data / "DKNYgirl_0.50_cr.png", task / "solution/reference.png")
            solution = "cp /solution/reference.png /workspace/output.png"
        (task / "solution/solve.sh").write_text("#!/bin/sh\nset -eu\n" + solution + "\n")
    print(json.dumps({"originals": 1, "reference_images": 8, "tasks": 2, "votes": votes}, indent=2))


if __name__ == "__main__":
    main()
