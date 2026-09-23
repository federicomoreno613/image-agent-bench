"""Sequential Harbor controls, bounded pilot, and an honest result summary."""
import argparse
import base64
import hashlib
import html
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from harbor.models.trajectories.trajectory import Trajectory

ROOT = Path(__file__).resolve().parent
KINDS = ["technical", "visual"]
ARMS = ["luna", "jev_luna"]


def fingerprint():
    files = [*ROOT.glob("*.py"), ROOT / "uv.lock", ROOT / "dataset.lock.json"]
    files += [p for p in (ROOT / "tasks").rglob("*") if p.is_file()]
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def env_from_file(path):
    env = os.environ.copy()
    values = dotenv_values(path) if path else {}
    for target, alias in [("OPENAI_API_KEY", "open_ai_api_key"), ("TYPESAFE_API_KEY", "jev_api_key")]:
        value = values.get(target) or values.get(alias) or env.get(target)
        if not value:
            raise ValueError(f"Missing {target}; no API request made")
        env[target] = value
    env.update(LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", PYTHONPATH=str(ROOT))
    return env


def attempt(kind, arm, repetition, phase, env):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    name = f"{phase}-{kind}-{arm}-{repetition}-{stamp}"
    output = ROOT / "local-results/jobs"
    output.mkdir(parents=True, exist_ok=True)
    cmd = [str(ROOT / ".venv/bin/harbor"), "run", "--path", str(ROOT / "tasks" / ("dkny-" + kind)),
           "--jobs-dir", str(output), "--job-name", name, "--n-concurrent", "1", "--max-retries", "0"]
    if arm in {"oracle", "nop"}:
        cmd += ["--agent", arm]
    else:
        cmd += ["--agent", "agent:ImageAgent", "--model", "gpt-5.6-luna", "--ak", "arm=" + arm,
                "--ak", "budget_path=" + str(ROOT / "budget.json")]
    log = output / (name + ".log")
    started = time.perf_counter()
    print(f"Running {phase}: {kind} / {arm} / repetition {repetition}", flush=True)
    with log.open("w") as f:
        process = subprocess.run(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=1000)
    candidates = list((output / name).glob("*/result.json"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one Harbor trial; inspect {log}")
    trial_path = candidates[0]
    trial = json.loads(trial_path.read_text())
    checked = trial_path.parent / "verifier/checks.json"
    checks = json.loads(checked.read_text()) if checked.exists() else {}
    accounting = trial_path.parent / "agent/accounting.json"
    account = json.loads(accounting.read_text()) if accounting.exists() else {}
    trace = trial_path.parent / "agent/trajectory.json"
    if arm in ARMS and trace.exists():
        Trajectory.model_validate_json(trace.read_text())
    metadata = account.get("metadata") or {}
    row = {"phase": phase, "fingerprint": fingerprint(), "task": kind, "arm": arm, "repetition": repetition,
           "harbor_trial": str(trial_path.parent.relative_to(ROOT)), "total_wall_seconds": time.perf_counter() - started,
           "process_exit_code": process.returncode, "technical_success": checks.get("technical_success", False),
           "visual_status": checks.get("visual_status", "pending"),
           "input_tokens": account.get("n_input_tokens"), "output_tokens": account.get("n_output_tokens"),
           "cached_tokens": account.get("n_cache_tokens"), "cost_upper_usd": account.get("cost_usd"),
           **metadata,
           "harbor_exception": (trial.get("exception_info") or {}).get("exception_type")}
    with (ROOT / "local-results/observations.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps({k: row.get(k) for k in ["task", "arm", "technical_success", "route", "model_calls", "agent_seconds", "cost_upper_usd", "harbor_exception"]}), flush=True)
    return row


def controls():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    rows = [attempt(kind, arm, 0, "control", env) for kind in KINDS for arm in ["oracle", "nop"]]
    passed = all(r["technical_success"] == (r["arm"] == "oracle") and not r["harbor_exception"] for r in rows)
    receipt = {"fingerprint": fingerprint(), "passed": passed, "rows": rows}
    (ROOT / "local-results/controls.json").write_text(json.dumps(receipt, indent=2))
    if not passed:
        raise RuntimeError("Control failure: no paid calls allowed")


def pilot(path, repetitions):
    receipt = json.loads((ROOT / "local-results/controls.json").read_text())
    if receipt["passed"] is not True or receipt["fingerprint"] != fingerprint():
        raise RuntimeError("Run controls again after code/data changes")
    env = env_from_file(path)
    # A single sequential process; no automatic reruns or hidden provider retries.
    for rep in range(1, repetitions + 1):
        for kind in KINDS:
            order = ARMS if (rep + KINDS.index(kind)) % 2 else list(reversed(ARMS))
            for arm in order:
                row = attempt(kind, arm, rep, "pilot", env)
                if row["harbor_exception"] or row.get("error"):
                    raise RuntimeError("Pilot exception recorded; stop before repeating a broken configuration")
    report()


def report():
    observations = ROOT / "local-results/observations.jsonl"
    rows = [json.loads(line) for line in observations.read_text().splitlines()]
    excluded = [r for r in rows if r["phase"] == "pilot" and r.get("fingerprint") != fingerprint()]
    rows = [r for r in rows if r["phase"] == "pilot" and r.get("fingerprint") == fingerprint()]
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    groups = []
    for kind in KINDS:
        for arm in ARMS:
            selected = [r for r in rows if r["task"] == kind and r["arm"] == arm]
            if not selected:
                continue
            group = {"task": kind, "arm": arm, "runs": len(selected),
                     "technical_passes": sum(r["technical_success"] for r in selected),
                     "visual_status": "pending" if kind == "visual" else "not_applicable"}
            for field in ["input_tokens", "output_tokens", "model_calls", "tool_calls", "agent_seconds", "cost_lower_usd", "cost_upper_usd"]:
                values = [r.get(field) for r in selected]
                group["mean_" + field] = statistics.mean(values) if all(v is not None for v in values) else None
            costs = [r.get("cost_upper_usd") for r in selected]
            group["cost_per_technical_success_usd"] = (sum(costs) / group["technical_passes"]
                if group["technical_passes"] and all(c is not None for c in costs) else None)
            group["cost_per_visual_success_usd"] = None
            groups.append(group)
    result = {"status": "PARTIAL_VISUAL_REVIEW_PENDING", "dataset": "DKNYgirl_0.50", "fingerprint": fingerprint(),
              "cost_note": "Token-rate estimates, not invoices. Upper bound includes possible undisclosed cache writes. Failed attempts included.",
              "groups": groups, "runs": rows, "earlier_configuration_attempts": excluded}
    (reports / "pilot.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Piloto: Luna vs JEV + Luna", "", "Estado: mediciones reales; calidad visual pendiente de revisión humana.", "",
             "| Tarea | Sistema | OK técnico | Tiempo medio (s) | Llamadas al modelo | Herramientas | Costo estimado medio (USD) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    def num(value, digits=3):
        return "desconocido" if value is None else f"{value:.{digits}f}"
    for g in groups:
        lines.append(f"| {g['task']} | {g['arm']} | {g['technical_passes']}/{g['runs']} | {num(g['mean_agent_seconds'])} | {num(g['mean_model_calls'],1)} | {num(g['mean_tool_calls'],1)} | {num(g['mean_cost_lower_usd'],6)}–{num(g['mean_cost_upper_usd'],6)} |")
    lines += ["", "La tarea técnica es un control de exportación proporcional. La visual usa las dimensiones originales de RetargetMe.",
              "Los votos del estudio valoran sus ocho resultados, no las salidas nuevas. No se afirma superioridad visual ni generalización.",
              "Las llamadas y herramientas se cuentan por separado. El tiempo mostrado cubre el agente completo, incluida la clasificación; el JSON también conserva el tiempo total de Harbor.",
              "La calidad visual pendiente impide calcular costo por éxito visual. Las estimaciones de costo incluyen llamadas fallidas cuando su consumo es conocido; si no, quedan desconocidas.",
              "", "[Datos y estudio original](https://people.csail.mit.edu/mrub/retargetme/download.html)"]
    (reports / "pilot.md").write_text("\n".join(lines) + "\n")
    cards = []
    def card(label, path, extra=""):
        if not path.exists():
            return
        encoded = base64.b64encode(path.read_bytes()).decode()
        cards.append(f'<figure><h3>{html.escape(label)}</h3><img src="data:image/png;base64,{encoded}"><figcaption>{html.escape(extra)}</figcaption></figure>')
    card("Original — 1024×673", ROOT / "data/DKNYgirl.png")
    card("Referencia RetargetMe: recorte manual", ROOT / "data/DKNYgirl_0.50_cr.png", "57/63 preferencias con original visible. Referencia, no respuesta única.")
    visual = [r for r in rows if r["task"] == "visual"]
    # Fixed blind ordering; arm identities remain in a separate JSON, never in the gallery.
    ordered = sorted(visual, key=lambda r: hashlib.sha256(r["harbor_trial"].encode()).hexdigest())
    mapping = {}
    for i, r in enumerate(ordered, 1):
        label = f"Candidato {i} — revisión pendiente"
        card(label, ROOT / r["harbor_trial"] / "agent/output.png", "Evaluar: persona conservada, proporciones naturales, encuadre útil, sin bordes.")
        mapping[str(i)] = {"arm": r["arm"], "trial": r["harbor_trial"]}
    page = '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DKNYgirl: revisión visual ciega</title><style>body{font-family:system-ui;background:#f4f1ea;color:#172b2a;margin:32px}main{display:flex;flex-wrap:wrap;gap:24px}figure{margin:0;padding:20px;background:white;border-radius:12px;max-width:512px}img{max-width:100%;height:auto}figcaption{max-width:480px;font-size:14px}h1{font-size:32px}</style><h1>Una imagen, dos caminos</h1><p>Resultados reales. Las etiquetas de sistema están ocultas para revisar calidad sin sesgo. No es un resultado del estudio original.</p><main>' + ''.join(cards) + '</main></html>'
    (ROOT / "local-results/comparison.html").write_text(page)
    (ROOT / "local-results/blind-key.json").write_text(json.dumps(mapping, indent=2))
    print(json.dumps(groups, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["controls", "pilot", "report"])
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=3)
    args = parser.parse_args()
    if args.action == "controls":
        controls()
    elif args.action == "pilot":
        pilot(args.env_file, args.repetitions)
    else:
        report()
