"""Read-only audit and Harbor replay of saved outputs. No model/API calls."""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
AD_SIZES = {(970, 250), (728, 90), (300, 250), (300, 600),
            (160, 600), (320, 50), (320, 100), (320, 250)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError("Expected a regular image under 10 MB")
    with Image.open(path) as im:
        if im.width * im.height > 4_000_000 or getattr(im, "n_frames", 1) != 1:
            raise ValueError("Expected one image under 4 million pixels")
        im.load()
        return im.convert("RGBA")


def compare(output, reference):
    """Unaligned pixel distances, not aesthetic scores or acceptance thresholds."""
    if output.size != reference.size:
        return {"same_dimensions": False, "exact_pixels": False}
    diff = ImageChops.difference(output.convert("RGB"), reference.convert("RGB"))
    stats = ImageStat.Stat(diff)
    mse = sum(x * x for x in stats.rms) / 3
    maximum = ImageChops.lighter(diff.getchannel("R"), ImageChops.lighter(diff.getchannel("G"), diff.getchannel("B")))
    maximum = ImageChops.lighter(maximum, ImageChops.difference(output.getchannel("A"), reference.getchannel("A")))
    equal_pixels = maximum.histogram()[0]
    return {"same_dimensions": True, "exact_pixels": output.tobytes() == reference.tobytes(),
            "matching_pixel_fraction": equal_pixels / (output.width * output.height),
            "mae_0_255": sum(stats.mean) / 3, "rmse_0_255": math.sqrt(mse),
            "psnr_db": 10 * math.log10(255 ** 2 / mse) if mse else None}


def crop_box(source, output):
    """Find an exact full-height crop; prove all pixels, not only a matching row."""
    if output.height != source.height or output.width > source.width:
        return None
    first = source.crop((0, 0, source.width, 1)).tobytes()
    needle = output.crop((0, 0, output.width, 1)).tobytes()
    start = 0
    while (position := first.find(needle, start)) >= 0:
        start = position + 1
        if position % 4 == 0:
            box = (position // 4, 0, position // 4 + output.width, output.height)
            if source.crop(box).tobytes() == output.tobytes():
                return list(box)
    return None


def frozen_references(data, manifest):
    refs = {}
    for entry in manifest["files"]:
        path = data / entry["file"]
        if sha(path) != entry["sha256"]:
            raise ValueError("Reference hash mismatch: " + entry["file"])
        if "_0.50_" in entry["file"]:
            refs[path.stem.rsplit("_", 1)[1]] = pixels(path)
    if set(refs) != set(manifest["operators_in_study"]) or len(refs) != 8:
        raise ValueError("Expected all eight frozen study references")
    return refs


def evaluate(candidates, data, manifest, entries):
    from verify import verify
    refs = frozen_references(data, manifest)
    source = pixels(data / "DKNYgirl.png")
    anchor_box = crop_box(source, refs["cr"])
    controls = {"same_reference_matches": compare(refs["cr"], refs["cr"])["exact_pixels"],
                "different_reference_rejected_as_anchor": not compare(refs["scl"], refs["cr"])["exact_pixels"],
                "wrong_dimensions_rejected": not compare(source, refs["cr"])["same_dimensions"]}
    if not all(controls.values()):
        raise AssertionError("Golden comparator control failed")
    rows = []
    for entry in entries:
        path = candidates / entry["file"]
        if sha(path) != entry["sha256"]:
            raise ValueError("Recorded output hash mismatch")
        image = pixels(path)
        row = {**entry, "technical_checks": verify(data / "DKNYgirl.png", path, entry["task"]),
               "bytes": path.stat().st_size, "under_150000_bytes": path.stat().st_size <= 150_000,
               "requested_ad_dimensions": image.size in AD_SIZES}
        if entry["task"] == "visual":
            pairs = {name: compare(image, ref) for name, ref in refs.items()}
            box = crop_box(source, image)
            delta = box[0] - anchor_box[0] if box and anchor_box else None
            row.update(comparisons=pairs, source_crop_box=box, golden_crop_box=anchor_box,
                       horizontal_difference_px=delta,
                       golden_crop_coverage_fraction=max(0, 1 - abs(delta) / image.width) if delta is not None else None,
                       exact_reference_matches=[name for name, values in pairs.items() if values["exact_pixels"]],
                       visual_acceptance="pending_human_review")
        rows.append(row)
    visual = [r for r in rows if r["task"] == "visual"]
    rewards = {"technical_pass_rate": sum(r["technical_checks"]["technical_success"] for r in rows) / len(rows),
               "golden_any_exact_match_rate": sum(bool(r["exact_reference_matches"]) for r in visual) / len(visual),
               "golden_cr_exact_match_rate": sum("cr" in r["exact_reference_matches"] for r in visual) / len(visual),
               "source_exact_crop_rate": sum(r["source_crop_box"] is not None for r in visual) / len(visual),
               "existing_file_under_150kb_rate": sum(r["under_150000_bytes"] for r in rows) / len(rows),
               "existing_file_ad_dimensions_rate": sum(r["requested_ad_dimensions"] for r in rows) / len(rows)}
    return {"mode": "posthoc_saved_output_replay", "controls": controls, "rewards": rewards,
            "pairs_compared": sum(len(r["comparisons"]) for r in visual), "rows": rows}


def run():
    pilot = json.loads((ROOT / "reports/pilot.json").read_text())
    published = [json.loads(x) for x in (ROOT / "reports/traces.jsonl").read_text().splitlines()]
    published = {(r["task"], r["arm"], r["repetition"]): r for r in published if r.get("trajectory")}
    task = ROOT / "local-results/golden-audit/task"
    if task.exists():
        shutil.rmtree(task)  # Generated audit inputs only; source trials are never changed.
    shutil.copytree(ROOT / "tasks/dkny-visual/environment", task / "environment")
    (task / "environment/candidates").mkdir()
    (task / "tests").mkdir()
    entries, receipts = [], []
    for row in pilot["runs"]:
        trial = ROOT / row["harbor_trial"]
        raw = json.loads((trial / "result.json").read_text())
        trace = published[row["task"], row["arm"], row["repetition"]]
        path = trial / "agent/output.png"
        assert sha(path) == trace["output_sha256"], "Output differs from published evidence"
        assert raw["exception_info"] is None and raw["verifier_result"]["rewards"]["technical_success"] == 1
        calls = trace["calls"]
        assert len(calls) == row["model_calls"]
        for field, raw_field in [("input_tokens", "n_input_tokens"), ("output_tokens", "n_output_tokens")]:
            assert sum(c[field] for c in calls) == row[field] == raw["agent_result"][raw_field]
        assert abs(sum(c["cost_usd"] for c in calls) - row["cost_upper_usd"]) < 1e-10
        filename = f"{row['task']}-{row['arm']}-{row['repetition']}.png"
        entries.append({"file": filename, "task": row["task"], "arm": row["arm"],
                        "repetition": row["repetition"], "sha256": sha(path), "original_trial": row["harbor_trial"]})
        shutil.copyfile(path, task / "environment/candidates" / filename)
        receipts.append({"original_trial": row["harbor_trial"], "trial_id": raw["id"],
                         "started_at": raw["started_at"], "finished_at": raw["finished_at"],
                         "agent_info": raw["agent_info"], "verifier_result": raw["verifier_result"],
                         "source_result_sha256": sha(trial / "result.json"), "output_sha256": sha(path),
                         "tokens_and_cost_reconciled": True})
    assert len(entries) == 12 and len({e["file"] for e in entries}) == 12
    (task / "instruction.md").write_text("Do nothing. This job only verifies previously recorded outputs; it is not a new agent attempt.\n")
    shutil.copyfile(ROOT / "tasks/dkny-visual/task.toml", task / "task.toml")
    with (task / "environment/Dockerfile").open("a") as f:
        f.write("COPY candidates/ /workspace/candidates/\n")
    shutil.copyfile(Path(__file__), task / "tests/golden.py")
    shutil.copyfile(ROOT / "verify.py", task / "tests/verify.py")
    shutil.copyfile(ROOT / "dataset.lock.json", task / "tests/dataset.lock.json")
    (task / "tests/entries.json").write_text(json.dumps(entries))
    (task / "tests/data").mkdir()
    manifest = json.loads((ROOT / "dataset.lock.json").read_text())
    for entry in manifest["files"]:
        shutil.copyfile(ROOT / "data" / entry["file"], task / "tests/data" / entry["file"])
    (task / "tests/test.sh").write_text("#!/bin/sh\nset -eu\npython3 /tests/golden.py verify\n")
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET"))}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    jobs = ROOT / "local-results/golden-audit/jobs"
    jobs.mkdir(exist_ok=True)
    budget = ROOT / "budget.json"
    before = sha(budget) if budget.exists() else None
    command = [str(ROOT / ".venv/bin/harbor"), "run", "--path", str(task), "--agent", "nop",
               "--jobs-dir", str(jobs), "--job-name", stamp, "--n-concurrent", "1", "--max-retries", "0"]
    print("Harbor: verifying 12 saved outputs, 48 golden pairs; agent=nop, no inference.", flush=True)
    with (jobs / (stamp + ".log")).open("w") as log:
        subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    paths = list((jobs / stamp).glob("*/result.json"))
    assert len(paths) == 1, "Expected one replay trial"
    native = json.loads(paths[0].read_text())
    assert native["exception_info"] is None, native["exception_info"]
    report = json.loads((paths[0].parent / "verifier/golden-checks.json").read_text())
    assert report["pairs_compared"] == 48 and report["rewards"] == native["verifier_result"]["rewards"]
    assert before == (sha(budget) if budget.exists() else None), "API budget changed during offline audit"
    report.update(source_pilot_fingerprint=pilot["fingerprint"], new_model_calls=0, new_api_cost_usd=0,
                  original_harbor_receipts=receipts, replay_command=command,
                  harbor_replay_result=str(paths[0].relative_to(ROOT)),
                  harbor_replay_id=native["id"], verifier_code_sha256=sha(Path(__file__)))
    # Relative paths keep the published evidence independent of a user's home directory.
    report["replay_command"] = [value.replace(str(ROOT) + "/", "") for value in command]
    (ROOT / "reports/golden-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pairs_compared": report["pairs_compared"], **report["rewards"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "verify"])
    if parser.parse_args().action == "run":
        run()
    else:
        data = Path("/tests/data")
        result = evaluate(Path("/workspace/candidates"), data,
                          json.loads(Path("/tests/dataset.lock.json").read_text()),
                          json.loads(Path("/tests/entries.json").read_text()))
        logs = Path("/logs/verifier")
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "golden-checks.json").write_text(json.dumps(result, indent=2))
        (logs / "reward.json").write_text(json.dumps(result["rewards"]))
        print(json.dumps(result["rewards"]))
