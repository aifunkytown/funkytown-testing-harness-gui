"""Small read-only helpers for populating GUI dropdowns from a live ComfyUI
server and from the local ComfyUI installation folder. No playwright here -
these are all plain HTTP GETs against ComfyUI's REST API, safe to call just
to fill in a combo box.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

MODEL_LOADER_TYPES = {
    "UNETLoader": "unet_name",
    "CheckpointLoaderSimple": "ckpt_name",
}


def _get_object_info(server, class_type, timeout=8):
    url = f"{server}/object_info/{class_type}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_available_models(server):
    """Union of unet_name and ckpt_name options ComfyUI currently knows
    about, across whichever loader types are installed - since we don't know
    ahead of time which one the selected workflow uses."""
    models = set()
    for class_type, field in MODEL_LOADER_TYPES.items():
        try:
            info = _get_object_info(server, class_type)
            models.update(info[class_type]["input"]["required"][field][0])
        except (urllib.error.URLError, KeyError, IndexError, TypeError):
            continue
    return sorted(models)


def list_available_loras(server):
    """LoRA filenames ComfyUI currently recognizes, via the standard
    LoraLoader node's own object_info. This is every LoRA ComfyUI knows
    about globally, not just ones already added as a slot in a particular
    workflow's Power Lora Loader node - lora_test.py still validates that
    separately when a run actually goes to use one."""
    try:
        info = _get_object_info(server, "LoraLoader")
        return sorted(info["LoraLoader"]["input"]["required"]["lora_name"][0])
    except (urllib.error.URLError, KeyError, IndexError, TypeError):
        return []


def list_sampler_names(server):
    try:
        info = _get_object_info(server, "KSampler")
        return list(info["KSampler"]["input"]["required"]["sampler_name"][0])
    except (urllib.error.URLError, KeyError, IndexError, TypeError):
        return []


def list_schedulers(server):
    try:
        info = _get_object_info(server, "KSampler")
        return list(info["KSampler"]["input"]["required"]["scheduler"][0])
    except (urllib.error.URLError, KeyError, IndexError, TypeError):
        return []


def check_server_reachable(server, timeout=4):
    try:
        with urllib.request.urlopen(f"{server}/system_stats", timeout=timeout):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


def infer_comfyui_install_dir(server, timeout=5):
    """Best-effort: ask a running ComfyUI server for its own --base-directory
    launch argument via /system_stats (which echoes back sys.argv). Returns
    None if the server's unreachable or wasn't launched with that flag -
    there's no way to guess otherwise, this isn't filesystem guesswork."""
    try:
        with urllib.request.urlopen(f"{server}/system_stats", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        argv = data["system"]["argv"]
        for i, arg in enumerate(argv):
            if arg == "--base-directory" and i + 1 < len(argv):
                return argv[i + 1]
    except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError):
        pass
    return None


def list_local_workflows(comfyui_install_dir):
    """Workflow filenames found in <install_dir>/user/default/workflows -
    read straight off disk, no server round-trip needed."""
    if not comfyui_install_dir:
        return []
    workflows_dir = Path(comfyui_install_dir) / "user" / "default" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        p.name for p in workflows_dir.glob("*.json")
        if not p.name.startswith(".")  # e.g. .index.json - ComfyUI's own metadata, not a workflow
    )
