"""One Harbor agent loop; JEV optionally dispatches a shared known recipe."""
import asyncio
import base64
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from harbor.agents.base import BaseAgent
from harbor.models.trajectories.trajectory import Trajectory
from langchain_typesafe import Choice, TypeSafeClassifier
from openai import AsyncOpenAI

LUNA = "gpt-5.6-luna"
JEV = "jev-1.13.0"
MAX_CALLS = 40
TOOLS = [
    {"type": "function", "name": "run_command", "description": "Run a shell command inside the isolated image-editing container.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}, "strict": True},
    {"type": "function", "name": "inspect_image", "description": "Look at the original or output image.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "enum": ["/workspace/source.png", "/workspace/output.png"]}}, "required": ["path"], "additionalProperties": False}, "strict": True},
]
SYSTEM = """You are an image editing agent. Complete the user's task with the provided
container tools. Work only inside /workspace. You have no reference answers.
Inspect images when a visual decision is required. Do not generate new content.
Use the shared recipe when it fits the request. Check the output before finishing.
Do not install dependencies or access the network. Finish with a short result.
"""


def complete_sum(values):
    return None if any(v is None for v in values) else sum(values)


class Budget:
    """Durable reservations: an uncertain request keeps its worst-case allowance."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = FileLock(str(self.path) + ".lock")

    def _read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {"limit_usd": 5.0, "calls": {}}

    def _write(self, data):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2))
        temporary.replace(self.path)

    def reserve(self, provider):
        # Luna's full context at long-context/cache-write rates + 4096 output < $0.50.
        # Jev's 64K context at $0.042/M < $0.003. No SDK retries are enabled.
        amount = {"openai": 0.5, "typesafe": 0.003}[provider]
        with self.lock:
            data = self._read()
            used = sum(c["charged_or_reserved_usd"] for c in data["calls"].values())
            if used + amount > data["limit_usd"]:
                raise RuntimeError("API budget exhausted; request not sent")
            token = str(uuid.uuid4())
            data["calls"][token] = {"provider": provider, "charged_or_reserved_usd": amount, "status": "reserved"}
            self._write(data)
            return token

    def settle(self, token, cost):
        if cost is None:
            return
        if not math.isfinite(cost) or cost < 0:
            raise ValueError("Invalid cost")
        with self.lock:
            data = self._read()
            call = data["calls"][token]
            if cost > call["charged_or_reserved_usd"]:
                raise RuntimeError("Reported cost exceeds reserved bound")
            call.update(charged_or_reserved_usd=cost, status="settled")
            self._write(data)


def luna_usage(usage):
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "cached_tokens": None,
                "cost_usd": None, "cost_lower_usd": None}
    raw = usage.model_dump() if hasattr(usage, "model_dump") else usage
    inp, out = raw.get("input_tokens"), raw.get("output_tokens")
    details = raw.get("input_tokens_details") or {}
    cached = details.get("cached_tokens")
    if inp is None or out is None or cached is None:
        return {"input_tokens": inp, "output_tokens": out, "cached_tokens": cached,
                "cost_usd": None, "cost_lower_usd": None, "raw_usage": raw}
    write = details.get("cache_write_tokens", details.get("cache_creation_tokens"))
    long = inp > 272_000
    rate_in, rate_out = (0.4, 1.8) if long else (0.2, 1.2)
    minimum = ((inp - cached) * rate_in + cached * (0.04 if long else 0.02) + out * rate_out) / 1_000_000
    # When cache-write counts are not disclosed, report a range, not a fake exact bill.
    maximum = minimum + (inp - cached if write is None else write) * rate_in * 0.25 / 1_000_000
    return {"input_tokens": inp, "output_tokens": out, "cached_tokens": cached,
            "cost_usd": maximum, "cost_lower_usd": minimum, "raw_usage": raw}


async def select_route(request, classifier):
    """The only provider-specific decision function. Returns route plus raw telemetry."""
    response = await classifier.ainvoke({
        "state": {"user_request": request, "source_width": 1024, "source_height": 673},
        "questions": {"route": Choice(
            instructions="Select the procedure that completely meets the user's request. Prefer luna whenever a visual decision is needed or the request is ambiguous.",
            criteria={
                "proportional_width": "User explicitly requests a new width while preserving aspect ratio, without cropping, borders, or rearrangement. This is a fully specified mechanical resize.",
                "luna": "Content-aware retargeting, selecting a crop, preserving a subject while changing aspect ratio, any visual judgment, missing information, or anything else.",
            },
        )},
    })
    answer = response.choices["route"]
    widths = re.findall(r"\bwidth\s+(?:to\s+)?(\d+)\b", request, re.I)
    known = (answer.choice == "proportional_width" and answer.confidence >= 0.90
             and len(widths) == 1 and 1 <= int(widths[0]) <= 4096)
    return {"route": "proportional_width" if known else "luna",
            "width": int(widths[0]) if known else None,
            "classification": answer.model_dump(), "response": response.model_dump()}


class ImageAgent(BaseAgent):
    SUPPORTS_ATIF = True

    @staticmethod
    def name():
        return "image-agent-bench"

    def version(self):
        return "0.1.0"

    def __init__(self, *args, arm="luna", budget_path="budget.json", **kwargs):
        super().__init__(*args, **kwargs)
        if arm not in {"luna", "jev_luna"}:
            raise ValueError("Unknown arm")
        if self.model_name not in {None, LUNA, "openai/" + LUNA}:
            raise ValueError("This pilot is pinned to GPT-5.6 Luna")
        self.arm = arm
        self.budget = Budget(budget_path)
        self.steps = []
        self.calls = []
        self.tool_count = 0
        self.route = "luna"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    async def setup(self, environment):
        pass

    def step(self, source, message, **kwargs):
        self.steps.append({"step_id": len(self.steps) + 1, "timestamp": datetime.now(timezone.utc).isoformat(),
                           "source": source, "message": message, **kwargs})

    def record_call(self, model, usage, elapsed, **extra):
        row = {"model": model, "seconds": elapsed, **usage, **extra}
        self.calls.append(row)
        with (self.logs_dir / "calls.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    async def execute(self, environment, name, arguments, call_id):
        self.tool_count += 1
        image = None
        if name == "run_command":
            command = arguments.get("command")
            if not isinstance(command, str) or not 1 <= len(command) <= 10000:
                raise ValueError("Invalid command")
            result = await environment.exec(command=command, timeout_sec=60, user="agent")
            text = json.dumps({"exit_code": result.return_code, "stdout": (result.stdout or "")[:12000],
                               "stderr": (result.stderr or "")[:4000]})
        elif name == "inspect_image":
            path = arguments.get("path")
            if path not in {"/workspace/source.png", "/workspace/output.png"}:
                raise ValueError("Image path not allowed")
            checked = await environment.exec(
                command="python3 -c 'import os,sys; p=sys.argv[1]; assert not os.path.islink(p); assert os.path.isfile(p); assert os.path.getsize(p)<=10000000' " + path,
                timeout_sec=10, user="agent")
            if checked.return_code != 0:
                text = "Image missing, too large, or not a regular file."
            else:
                local = self.logs_dir / ("view-" + str(self.tool_count) + ".png")
                await environment.download_file(path, local)
                from PIL import Image
                with Image.open(local) as im:
                    if im.width * im.height > 4_000_000 or im.format != "PNG":
                        raise ValueError("Expected PNG under 4 million pixels")
                image = "data:image/png;base64," + base64.b64encode(local.read_bytes()).decode()
                text = "Image attached."
        else:
            raise ValueError("Unknown tool")
        self.step("agent", "Tool result", llm_call_count=0,
                  observation={"results": [{"source_call_id": call_id, "content": text}]})
        return text, image

    async def luna(self, instruction, environment):
        history = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": instruction}]
        async with AsyncOpenAI(max_retries=0, timeout=120) as client:
            while len(self.calls) < MAX_CALLS:
                reservation = self.budget.reserve("openai")
                started = time.perf_counter()
                try:
                    response = await client.responses.create(
                        model=LUNA, reasoning={"effort": "medium"}, input=history,
                        tools=TOOLS, parallel_tool_calls=False, max_output_tokens=4096,
                        store=False, include=["reasoning.encrypted_content"],
                    )
                except BaseException as exc:
                    self.record_call(LUNA, luna_usage(None), time.perf_counter() - started, error=type(exc).__name__)
                    self.step("agent", "Luna request failed: " + type(exc).__name__, model_name=LUNA, llm_call_count=1)
                    raise
                usage = luna_usage(response.usage)
                self.budget.settle(reservation, usage["cost_usd"])
                self.record_call(response.model, usage, time.perf_counter() - started, response_id=response.id,
                                 status=response.status)
                functions = [item for item in response.output if item.type == "function_call"]
                calls = [{"tool_call_id": f.call_id, "function_name": f.name, "arguments": json.loads(f.arguments)} for f in functions]
                self.step("agent", response.output_text or "Tool call", model_name=response.model,
                          reasoning_effort="medium", llm_call_count=1, tool_calls=calls or None,
                          metrics={"prompt_tokens": usage["input_tokens"], "completion_tokens": usage["output_tokens"],
                                   "cached_tokens": usage["cached_tokens"], "cost_usd": usage["cost_usd"]})
                history.extend(response.output)
                if not functions:
                    if response.status != "completed":
                        raise RuntimeError("Luna did not complete its response")
                    return
                for f, call in zip(functions, calls, strict=True):
                    try:
                        result, image = await self.execute(environment, f.name, call["arguments"], f.call_id)
                    except Exception as exc:
                        result, image = "Tool failed: " + type(exc).__name__, None
                        self.step("agent", "Tool result", llm_call_count=0,
                                  observation={"results": [{"source_call_id": f.call_id, "content": result}]})
                    history.append({"type": "function_call_output", "call_id": f.call_id, "output": result})
                    if image:
                        history.append({"role": "user", "content": [{"type": "input_text", "text": "Requested tool image:"},
                                                                    {"type": "input_image", "image_url": image, "detail": "high"}]})
        raise RuntimeError("Model call limit reached")

    async def run(self, instruction, environment, context):
        started = time.perf_counter()
        self.step("system", SYSTEM)
        self.step("user", instruction)
        error = None
        try:
            if self.arm == "jev_luna":
                classifier = TypeSafeClassifier(model=JEV, timeout=30)
                reservation = self.budget.reserve("typesafe")
                before = time.perf_counter()
                try:
                    decision = await select_route(instruction.split("\nInput:")[0], classifier)
                    raw = decision["response"]
                    usage = raw.get("usage") or {}
                    n_in = usage.get("input_tokens")
                    cost = None if n_in is None else n_in * 0.042 / 1_000_000
                    self.budget.settle(reservation, cost)
                    self.record_call(raw["model"], {"input_tokens": n_in, "output_tokens": usage.get("output_tokens"),
                                                   "cached_tokens": None, "cost_usd": cost, "cost_lower_usd": cost},
                                     time.perf_counter() - before, response_id=raw.get("request_id"),
                                     classification=decision["classification"])
                    self.route = decision["route"]
                    self.step("agent", json.dumps({k:v for k,v in decision.items() if k != "response"}),
                              model_name=raw["model"], llm_call_count=1,
                              metrics={"prompt_tokens": n_in, "completion_tokens": usage.get("output_tokens"), "cost_usd": cost})
                except BaseException as exc:
                    # Provider failures are counted, keep their reservation, and use the same fallback.
                    self.record_call(JEV, {"input_tokens": None, "output_tokens": None, "cached_tokens": None,
                                           "cost_usd": None, "cost_lower_usd": None}, time.perf_counter() - before,
                                     error=type(exc).__name__)
                    self.step("agent", "JEV failed; fallback to Luna: " + type(exc).__name__, model_name=JEV, llm_call_count=1)
                    self.route = "luna"
                    if not isinstance(exc, Exception):
                        raise
                finally:
                    classifier.client.close()
                    await classifier.async_client.aclose()
                if self.route == "proportional_width":
                    command = ("python3 /app/patterns.py proportional-width --input /workspace/source.png "
                               f"--output /workspace/output.png --width {decision['width']}")
                    call_id = "known-procedure"
                    self.step("agent", "Execute recognized procedure", llm_call_count=0,
                              tool_calls=[{"tool_call_id": call_id, "function_name": "run_command", "arguments": {"command": command}}])
                    text, _ = await self.execute(environment, "run_command", {"command": command}, call_id)
                    if json.loads(text)["exit_code"] != 0:
                        self.route = "luna_after_procedure_failure"
                        await self.luna(instruction, environment)
                else:
                    await self.luna(instruction, environment)
            else:
                await self.luna(instruction, environment)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            context.n_input_tokens = complete_sum([c["input_tokens"] for c in self.calls])
            context.n_output_tokens = complete_sum([c["output_tokens"] for c in self.calls])
            context.n_cache_tokens = complete_sum([c["cached_tokens"] for c in self.calls])
            context.cost_usd = complete_sum([c["cost_usd"] for c in self.calls])
            context.metadata = {"arm": self.arm, "route": self.route, "model_calls": len(self.calls),
                                "tool_calls": self.tool_count, "agent_seconds": time.perf_counter() - started,
                                "cost_lower_usd": complete_sum([c["cost_lower_usd"] for c in self.calls]),
                                "cost_note": "Published token-rate estimate; upper bound if cache-write counts absent.", "error": error}
            (self.logs_dir / "accounting.json").write_text(context.model_dump_json(indent=2))
            trajectory = Trajectory.model_validate({"schema_version": "ATIF-v1.7", "session_id": self.session_id,
                "agent": {"name": self.name(), "version": self.version(), "model_name": LUNA, "extra": {"arm": self.arm}},
                "steps": self.steps,
                "final_metrics": {"total_prompt_tokens": context.n_input_tokens, "total_completion_tokens": context.n_output_tokens,
                                  "total_cached_tokens": context.n_cache_tokens, "total_cost_usd": context.cost_usd,
                                  "total_steps": len(self.steps)}, "extra": context.metadata})
            (self.logs_dir / "trajectory.json").write_text(trajectory.model_dump_json(indent=2, exclude_none=True))
            try:
                await environment.download_file("/workspace/output.png", self.logs_dir / "output.png")
            except Exception:
                pass  # A missing output is independently rejected by the verifier.
