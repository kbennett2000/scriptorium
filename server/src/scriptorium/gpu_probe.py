"""Best-effort GPU/CPU status for the admin UI's live indicator.

This is a **diagnostic convenience**, not part of the bake contract: it shells out to the local
``nvidia-smi`` and ``ollama`` binaries to report whether the text model is running on the GPU or has
spilled onto the CPU, plus the card's utilisation. It never raises and never blocks the app — on a
box without those tools (e.g. the deployed i5 with no GPU) every field simply reads ``None`` and the
UI shows "unknown". The two shell calls go through :func:`_run`, which tests monkeypatch.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

_TIMEOUT_S = 3.0

# The GPU pulses between bursts during LLM generation, so a single instantaneous sample can catch an
# idle trough and make busy work look stalled. Sample a short burst and report the PEAK utilisation.
_SAMPLES = 5
_SAMPLE_GAP_S = 0.08


def _run(argv: list[str]) -> str | None:
    """Run a short command and return its stdout, or ``None`` on any failure (missing binary,
    non-zero exit, timeout). Never raises."""
    try:
        proc = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _parse_processor(cell: str) -> str:
    """Map an ``ollama ps`` PROCESSOR cell to ``gpu`` / ``cpu`` / ``mixed``.

    Examples: ``100% GPU`` → gpu; ``100% CPU`` → cpu; ``98%/2% CPU/GPU`` → cpu (98% on CPU);
    ``5%/95% CPU/GPU`` → mixed. The first percentage in a split cell is the CPU share.
    """
    text = cell.strip().upper()
    if "CPU/GPU" in text:
        head = text.split("CPU/GPU")[0]  # e.g. "98%/2% "
        nums = [int(n) for n in head.replace("%", " ").split() if n.isdigit()]
        cpu_pct = nums[0] if nums else 0
        if cpu_pct >= 50:
            return "cpu"
        if cpu_pct > 0:
            return "mixed"
        return "gpu"
    if "GPU" in text:
        return "gpu"
    if "CPU" in text:
        return "cpu"
    return "mixed"


def _text_model(ollama_ps: str | None) -> dict[str, Any]:
    """Parse ``ollama ps`` output into ``{loaded, name, processor}``.

    Output shape (tab/space separated), header + one row per loaded model:
        NAME          ID  SIZE  PROCESSOR      CONTEXT  UNTIL
        qwen3.5:9b    ..  6.2GB 100% GPU       3324     4 minutes from now
    """
    if not ollama_ps:
        return {"loaded": None, "name": None, "processor": None}
    lines = [ln for ln in ollama_ps.splitlines() if ln.strip()]
    if len(lines) < 2:  # header only → nothing loaded
        return {"loaded": False, "name": None, "processor": None}
    row = lines[1]
    name = row.split()[0]
    # PROCESSOR is the cell containing GPU/CPU; grab the run of tokens that mention them.
    proc_tokens = [t for t in row.split() if "GPU" in t.upper() or "CPU" in t.upper() or "%" in t]
    processor = _parse_processor(" ".join(proc_tokens)) if proc_tokens else None
    return {"loaded": True, "name": name, "processor": processor}


def _gpu(nvidia: str | None) -> dict[str, Any]:
    """Parse the first line of ``nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total
    --format=csv,noheader,nounits`` → ``{present, util_percent, mem_used_mib, mem_total_mib}``."""
    if not nvidia:
        return {"present": False, "util_percent": None, "mem_used_mib": None,
                "mem_total_mib": None}
    line = next((ln for ln in nvidia.splitlines() if ln.strip()), "")
    parts = [p.strip() for p in line.split(",")]
    try:
        util, used, total = int(parts[0]), int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return {"present": True, "util_percent": None, "mem_used_mib": None,
                "mem_total_mib": None}
    return {"present": True, "util_percent": util, "mem_used_mib": used, "mem_total_mib": total}


def _summary(gpu: dict[str, Any], text_model: dict[str, Any]) -> str:
    """One-word verdict for the badge: ``gpu`` (good) / ``cpu`` (the spill we warn about) /
    ``idle`` / ``unknown``."""
    proc = text_model.get("processor")
    if proc in ("cpu", "mixed"):
        return "cpu"
    if proc == "gpu":
        return "gpu"
    # No text model loaded: if the card is busy it's a render; if quiet, idle.
    util = gpu.get("util_percent")
    if text_model.get("loaded") is False:
        if util is not None and util >= 25:
            return "gpu"
        if util is not None:
            return "idle"
    return "unknown"


def _sample_gpu() -> dict[str, Any]:
    """Sample ``nvidia-smi`` a few times over a fraction of a second and report the reading with the
    **peak** ``util_percent`` (memory from that same sample). This stops the live badge flashing a
    scary near-zero number while the card is actually flat-out between bursts. If the card is
    absent/unreadable it degrades exactly as a single read would."""
    argv = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits"]
    samples: list[dict[str, Any]] = []
    for i in range(_SAMPLES):
        sample = _gpu(_run(argv))
        samples.append(sample)
        if not sample["present"]:
            break  # no GPU / unreadable — no point sampling further
        if i < _SAMPLES - 1:
            time.sleep(_SAMPLE_GAP_S)
    readable = [s for s in samples if s["present"] and s["util_percent"] is not None]
    if not readable:
        return samples[0]  # present-but-unparsed, or absent — same degradation as before
    return max(readable, key=lambda s: s["util_percent"])


def probe_gpu() -> dict[str, Any]:
    """The admin ``/gpu`` payload. Best-effort; every field degrades to ``None``/``unknown``."""
    gpu = _sample_gpu()
    text_model = _text_model(_run(["ollama", "ps"]))
    return {"gpu": gpu, "text_model": text_model, "summary": _summary(gpu, text_model)}
