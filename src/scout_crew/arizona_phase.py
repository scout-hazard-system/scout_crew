# Copyright 2026 Scout Project Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Alpha development phase: Arizona jurisdiction scope for all pipelines/catalogs/facets.

Phase class: alpha_development (deployment phase 1).
Manager stays in alpha mindset/persona and AZ-only operations until an operator
prompt explicitly notifies the second deployment phase.

All facets remain functional (scanner, hazards, ranking, markers, map shards,
crew) inside Arizona only. Scanner is essential inside AZ.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "arizona_phase.json"
_DESKTOP = Path("/home/gibi/Desktop")

DEFAULT_AZ_MARKERS: List[str] = [
    "mile marker", "exit", "northbound", "southbound", "eastbound", "westbound",
    "on-ramp", "off-ramp", "shoulder", "highway",
    "I-10", "I-17", "I-19", "I-40", "I-8",
    "US-60", "US-93", "SR-51", "SR-101", "SR-202",
    "junction", "mp", "milepost",
]

DEFAULT_SELECTOR = {
    "state": "AZ",
    "city": "Phoenix",
    "county": "Maricopa County",
    "lat": 33.4484,
    "lon": -112.0740,
    "lock_state": True,
    "desired_types": ["law", "dispatch"],
}


def load_phase_config() -> Dict[str, Any]:
    if _CONFIG_PATH.exists():
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "phase": "alpha_arizona_jurisdiction",
        "target_jurisdiction": {"state": "AZ", "state_name": "Arizona", "lock_state": True},
        "location_markers": {"filters": DEFAULT_AZ_MARKERS, "set_all": True, "enabled": True},
        "facets": {
            "scanner_streams": {"enabled": True, "scope": "AZ_only", "essential": True},
            "hazard_feeds": {"enabled": True, "scope": "AZ_only", "essential": True},
        },
        "selector_defaults": DEFAULT_SELECTOR,
    }


def az_shard_paths(cfg: Optional[Dict[str, Any]] = None) -> List[Path]:
    cfg = cfg or load_phase_config()
    roots = (cfg.get("target_shard") or {}).get("shard_roots") or [
        str(_DESKTOP / "vlm_text_map_shards" / "AZ"),
        str(_DESKTOP / "vlm_text_map_shards_chunked" / "AZ"),
    ]
    return [Path(p) for p in roots]


def location_marker_filters(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    cfg = cfg or load_phase_config()
    markers = (cfg.get("location_markers") or {}).get("filters") or DEFAULT_AZ_MARKERS
    seen = set()
    out: List[str] = []
    for m in markers:
        key = str(m).strip()
        lk = key.lower()
        if key and lk not in seen:
            seen.add(lk)
            out.append(key)
    return out


def ensure_az_shard_dirs(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    paths: List[str] = []
    for path in az_shard_paths(cfg):
        path.mkdir(parents=True, exist_ok=True)
        stamp = path / ".scout_az_phase"
        stamp.write_text(
            "scout phase=alpha_arizona_jurisdiction\n"
            "scope=alpha_all_facets_within_arizona_only\n"
            "scanner=essential_within_AZ\n"
            "state=AZ\n",
            encoding="utf-8",
        )
        paths.append(str(path))
    return paths


def apply_location_marker_filters(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    cfg = cfg or load_phase_config()
    filters = location_marker_filters(cfg)
    applied: List[str] = []
    for root in ensure_az_shard_dirs(cfg):
        out = Path(root) / "location_marker_filters.json"
        payload = {
            "state": "AZ",
            "phase": cfg.get("phase"),
        "phase_class": cfg.get("phase_class") or "alpha_development",
        "deployment_phase": cfg.get("deployment_phase") or 1,
        "phase_lock": cfg.get("phase_lock") or {"enabled": True, "persona": "alpha_development_manager"},
            "enabled": True,
            "set_all": True,
            "filters": filters,
            "weight": ((cfg.get("location_markers") or {}).get("weight") or 2),
            "jurisdiction_scope": "AZ_only",
            "scanner_essential_within_scope": True,
        }
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        applied.append(str(out))
    return applied


def apply_catalog_scope(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Point active Broadcastify catalog + jurisdiction scope files at AZ."""
    cfg = cfg or load_phase_config()
    catalogs = cfg.get("catalogs") or {}
    az_catalog = Path(
        catalogs.get("broadcastify_channels_file")
        or (_DESKTOP / "stack/config/broadcastify_national_shards/broadcastify_channels.us.az.json")
    )
    active = Path(
        catalogs.get("active_catalog_symlink")
        or (_DESKTOP / "stack/config/broadcastify_channels.active.json")
    )
    scope_file = Path(
        catalogs.get("scope_file")
        or (_DESKTOP / "stack/config/jurisdiction_scope.active.json")
    )

    result: Dict[str, Any] = {
        "az_catalog_exists": az_catalog.exists(),
        "az_catalog": str(az_catalog),
        "active_catalog": str(active),
        "scope_file": str(scope_file),
    }

    if az_catalog.exists():
        # Copy (not symlink) for tools that don't follow links well
        shutil.copy2(az_catalog, active)
        result["active_catalog_updated"] = True
        try:
            data = json.loads(az_catalog.read_text(encoding="utf-8"))
            chs = data.get("channels", []) if isinstance(data, dict) else data
            result["az_channel_count"] = len(chs) if isinstance(chs, list) else None
        except Exception as exc:  # noqa: BLE001
            result["az_channel_count_error"] = repr(exc)
    else:
        result["active_catalog_updated"] = False

    selector = dict(DEFAULT_SELECTOR)
    selector.update(cfg.get("selector_defaults") or {})
    facets = cfg.get("facets") or {}
    scope_payload = {
        "phase": cfg.get("phase"),
        "phase_class": cfg.get("phase_class") or "alpha_development",
        "deployment_phase": cfg.get("deployment_phase") or 1,
        "phase_lock": cfg.get("phase_lock") or {"enabled": True, "persona": "alpha_development_manager"},
        "jurisdiction": {
            "state": "AZ",
            "state_name": "Arizona",
            "lock_state": True,
        },
        "facets": facets,
        "selector_defaults": selector,
        "catalogs": {
            "broadcastify_channels_file": str(az_catalog),
            "broadcastify_channels_active": str(active),
        },
        "map_shards": [str(p) for p in az_shard_paths(cfg)],
        "location_marker_filters": location_marker_filters(cfg),
        "policy": {
            "all_facets_functional": True,
            "scanner_essential": True,
            "scanner_scope": "AZ_only",
            "hazard_scope": "AZ_only",
            "reject_non_az_locations": True,
            "note": (
                "ALPHA DEVELOPMENT: operate all pipelines/catalogs within Arizona only. "
                "Scanner and hazard facets are essential inside AZ; non-AZ is out of scope. "
                "Hold alpha persona until explicit second deployment phase prompt."
            ),
            "phase_class": "alpha_development",
            "deployment_phase": 1,
        },
    }
    scope_file.parent.mkdir(parents=True, exist_ok=True)
    scope_file.write_text(json.dumps(scope_payload, indent=2) + "\n", encoding="utf-8")
    result["scope_file_written"] = True
    return result


def apply_vehicle_stack_env(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Rewrite stack/config/vehicle_stack.env selector/catalog defaults to AZ."""
    cfg = cfg or load_phase_config()
    env_path = _DESKTOP / "stack/config/vehicle_stack.env"
    if not env_path.exists():
        return {"updated": False, "reason": "vehicle_stack.env missing", "path": str(env_path)}

    selector = dict(DEFAULT_SELECTOR)
    selector.update(cfg.get("selector_defaults") or {})
    az_catalog = (
        (cfg.get("catalogs") or {}).get("broadcastify_channels_file")
        or str(_DESKTOP / "stack/config/broadcastify_national_shards/broadcastify_channels.us.az.json")
    )
    active_catalog = str(_DESKTOP / "stack/config/broadcastify_channels.active.json")

    city = selector.get("city") or "Phoenix"
    county = selector.get("county") or "Maricopa County"
    state = selector.get("state") or "AZ"
    lat = selector.get("lat") or 33.4484
    lon = selector.get("lon") or -112.0740
    types = selector.get("desired_types") or ["law", "dispatch"]
    if isinstance(types, list):
        types_s = ",".join(types)
    else:
        types_s = str(types)

    extra = (
        f"--channels-file {active_catalog} "
        f"--selector-city \"{city}\" "
        f"--selector-county \"{county}\" "
        f"--selector-state \"{state}\" "
        f"--selector-lat {lat} "
        f"--selector-lon {lon} "
        f"--selector-use-ollama-rerank "
        f"--selector-ollama-model scout-rank"
    )

    lines = env_path.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    replacements = {
        "PIPELINE_EXTRA_ARGS": f"PIPELINE_EXTRA_ARGS='{extra}'",
        "BROADCASTIFY_CHANNELS_FILE": f"BROADCASTIFY_CHANNELS_FILE={active_catalog}",
        "BROADCASTIFY_SELECTOR_CITY": f'BROADCASTIFY_SELECTOR_CITY="{city}"',
        "BROADCASTIFY_SELECTOR_COUNTY": f'BROADCASTIFY_SELECTOR_COUNTY="{county}"',
        "BROADCASTIFY_SELECTOR_STATE": f'BROADCASTIFY_SELECTOR_STATE="{state}"',
        "BROADCASTIFY_SELECTOR_LOCK_STATE": "BROADCASTIFY_SELECTOR_LOCK_STATE=true",
        "BROADCASTIFY_SELECTOR_DESIRED_TYPES": f"BROADCASTIFY_SELECTOR_DESIRED_TYPES={types_s}",
        "BROADCASTIFY_SELECTOR_USE_OLLAMA_RERANK": "BROADCASTIFY_SELECTOR_USE_OLLAMA_RERANK=true",
        "BROADCASTIFY_SELECTOR_OLLAMA_MODEL": "BROADCASTIFY_SELECTOR_OLLAMA_MODEL=scout-rank",
        "JURISDICTION_SCOPE_FILE": f"JURISDICTION_SCOPE_FILE={_DESKTOP / 'stack/config/jurisdiction_scope.active.json'}",
        "JURISDICTION_STATE": "JURISDICTION_STATE=AZ",
        "MAP_SHARD_STATE": "MAP_SHARD_STATE=AZ",
    }
    seen = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in replacements:
            out.append(replacements[key])
            seen.add(key)
        else:
            out.append(line)
    for key, val in replacements.items():
        if key not in seen:
            out.append(val)

    # backup once
    bak = env_path.with_suffix(".env.bak_pre_az")
    if not bak.exists():
        shutil.copy2(env_path, bak)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {
        "updated": True,
        "path": str(env_path),
        "backup": str(bak),
        "broadcastify_channels_file": active_catalog,
        "selector_state": state,
        "selector_city": city,
    }


def apply_all_pipeline_scope() -> Dict[str, Any]:
    """Apply AZ jurisdiction scope across markers, catalogs, stack env, scout outputs."""
    cfg = load_phase_config()
    marker_files = apply_location_marker_filters(cfg)
    catalog = apply_catalog_scope(cfg)
    env_info = apply_vehicle_stack_env(cfg)

    # scout_crew local export for agents/CLI
    scout_out = _DESKTOP / "scout_crew" / "output"
    scout_out.mkdir(parents=True, exist_ok=True)
    status = manager_status_payload(cfg, marker_files=marker_files, catalog=catalog, env_info=env_info)
    (scout_out / "az_manager_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    (scout_out / "jurisdiction_scope.active.json").write_text(
        Path(catalog["scope_file"]).read_text(encoding="utf-8")
        if catalog.get("scope_file") and Path(str(catalog["scope_file"])).exists()
        else json.dumps(status, indent=2) + "\n",
        encoding="utf-8",
    )
    return status


def manager_status_payload(
    cfg: Optional[Dict[str, Any]] = None,
    *,
    marker_files: Optional[List[str]] = None,
    catalog: Optional[Dict[str, Any]] = None,
    env_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = cfg or load_phase_config()
    paths = [str(p) for p in az_shard_paths(cfg)]
    filters = location_marker_filters(cfg)
    if marker_files is None:
        marker_files = apply_location_marker_filters(cfg)
    if catalog is None:
        catalog = apply_catalog_scope(cfg)
    map_cache_az = Path.home() / ".scanner_stream" / "map_cache" / "shards" / "AZ"
    map_cache_tiles = 0
    if map_cache_az.is_dir():
        map_cache_tiles = sum(1 for _ in map_cache_az.glob("*.mvt.gz"))
    text_shard_dirs_ok = all(Path(p).is_dir() for p in paths)
    ready = (
        text_shard_dirs_ok
        and len(filters) > 0
        and bool(catalog.get("az_catalog_exists"))
        and (map_cache_tiles > 0 or text_shard_dirs_ok)
    )
    # Prefer active when text markers/catalog ready even if planet prefetch is thin.
    status = "AZ_JURISDICTION_ACTIVE" if ready else "AZ_SHARD_MISSING"
    return {
        "phase": cfg.get("phase"),
        "phase_class": cfg.get("phase_class") or "alpha_development",
        "deployment_phase": cfg.get("deployment_phase") or 1,
        "phase_lock": cfg.get("phase_lock") or {"enabled": True, "persona": "alpha_development_manager"},
        "jurisdiction": "AZ",
        "jurisdiction_name": "Arizona",
        "lock_state": True,
        "all_facets_functional": True,
        "facets": cfg.get("facets") or {},
        "scanner_essential_within_az": True,
        "location_markers_enabled": True,
        "location_marker_filters": filters,
        "filters_applied_count": len(filters),
        "az_shard_paths": paths,
        "az_map_cache_shard": str(map_cache_az),
        "az_map_cache_tiles": map_cache_tiles,
        "az_filter_files": marker_files,
        "az_shard_ready": ready,
        "catalog": catalog,
        "vehicle_stack_env": env_info,
        "out_of_scope": ["non_az_locations", "non_az_shards", "non_az_catalogs"],
        "manager_status": status,
        "note": (
            "All pipelines/catalogs/facets operate within Arizona only. "
            "Scanner and hazard data are essential inside AZ jurisdictions."
        ),
    }



PHASE_RELEASE_TRIGGERS = [
    "second deployment phase",
    "deployment phase 2",
    "phase 2 deployment",
    "begin deployment phase 2",
    "exit alpha development",
    "promote from alpha",
    "deployment_phase=2",
    "phase_class=beta",
    "phase_class=production",
]


def detect_phase_transition(text: str) -> dict:
    """Return whether operator text unlocks deployment phase 2."""
    raw = (text or "").strip()
    low = raw.lower()
    hit = next((tr for tr in PHASE_RELEASE_TRIGGERS if tr in low), None)
    return {
        "transition_requested": bool(hit),
        "matched_trigger": hit,
        "from_phase": "alpha_development",
        "to_phase": "deployment_phase_2" if hit else None,
        "manager_must_hold_alpha": not bool(hit),
    }


def alpha_persona_block(user_prompt: str = "") -> str:
    """Manager persona lock text for alpha development."""
    transition = detect_phase_transition(user_prompt)
    hold = transition["manager_must_hold_alpha"]
    return (
        "=== PHASE CLASS: ALPHA DEVELOPMENT (LOCKED) ===\n"
        "deployment_phase: 1\n"
        "phase_id: alpha_arizona_jurisdiction\n"
        "persona: alpha_development_manager\n"
        "HOLD: remain in alpha mindset/persona and Arizona-only operations.\n"
        "Do NOT assume beta/production readiness, full multi-state rollout, or\n"
        "deployment-phase-2 behaviors unless the operator prompt explicitly notifies\n"
        "the second deployment phase.\n"
        f"transition_requested: {transition['transition_requested']}\n"
        f"matched_trigger: {transition.get('matched_trigger')}\n"
        f"manager_must_hold_alpha: {hold}\n"
        "Release only on explicit cues such as: 'second deployment phase',\n"
        "'deployment phase 2', 'begin deployment phase 2', 'exit alpha development'.\n"
        "Until release: prioritize AZ jurisdiction lock, marker filters, AZ catalogs,\n"
        "and essential in-AZ scanner/hazard/ranking facets.\n"
        "=== END ALPHA DEVELOPMENT LOCK ==="
    )


def manager_phase_prompt_block(user_prompt: str = "") -> str:
    st = apply_all_pipeline_scope()
    alpha = alpha_persona_block(user_prompt)
    filters = ", ".join(st["location_marker_filters"])
    facets = st.get("facets") or {}
    facet_lines = []
    for name, meta in facets.items():
        if isinstance(meta, dict):
            facet_lines.append(
                f"- {name}: enabled={meta.get('enabled')} scope={meta.get('scope')} essential={meta.get('essential')}"
            )
    facet_txt = "\n".join(facet_lines) if facet_lines else "- (see jurisdiction_scope.active.json)"
    return (
        f"{alpha}\n\n"
        "=== JURISDICTION SCOPE (MANDATORY) ===\n"
        "Phase class: ALPHA DEVELOPMENT (deployment phase 1).\n"
        "Phase: all facets functional within Arizona (AZ) only.\n"
        "Manager persona holds alpha until explicit second-deployment-phase prompt.\n"
        "Target jurisdiction: Arizona / AZ. lock_state=true.\n"
        "Map shards: vlm_text_map_shards/AZ and vlm_text_map_shards_chunked/AZ.\n"
        "Catalog: broadcastify_channels.us.az.json (active catalog pointed here).\n"
        "Scanner/hazard/ranking: ESSENTIAL inside AZ; do not disable.\n"
        "Non-AZ locations, shards, and catalogs: OUT OF SCOPE.\n"
        f"Location marker filters (set_all on AZ shard): {filters}\n"
        "Facets:\n"
        f"{facet_txt}\n"
        f"Current manager_status: {st['manager_status']} "
        f"(filters_applied_count={st['filters_applied_count']}).\n"
        "When ranking channels or citing hazards/scanner, restrict to AZ jurisdictions.\n"
        "=== END JURISDICTION SCOPE ==="
    )


def export_environ() -> Dict[str, str]:
    """Env vars child pipelines can inherit for AZ focus."""
    cfg = load_phase_config()
    selector = dict(DEFAULT_SELECTOR)
    selector.update(cfg.get("selector_defaults") or {})
    active = str(_DESKTOP / "stack/config/broadcastify_channels.active.json")
    scope = str(_DESKTOP / "stack/config/jurisdiction_scope.active.json")
    return {
        "JURISDICTION_STATE": "AZ",
        "JURISDICTION_STATE_NAME": "Arizona",
        "JURISDICTION_LOCK_STATE": "true",
        "JURISDICTION_SCOPE_FILE": scope,
        "MAP_SHARD_STATE": "AZ",
        "BROADCASTIFY_CHANNELS_FILE": active,
        "BROADCASTIFY_SELECTOR_STATE": "AZ",
        "BROADCASTIFY_SELECTOR_CITY": str(selector.get("city") or "Phoenix"),
        "BROADCASTIFY_SELECTOR_COUNTY": str(selector.get("county") or "Maricopa County"),
        "BROADCASTIFY_SELECTOR_LOCK_STATE": "true",
        "BROADCASTIFY_SELECTOR_DESIRED_TYPES": ",".join(selector.get("desired_types") or ["law", "dispatch"]),
    }


if __name__ == "__main__":
    print(json.dumps(apply_all_pipeline_scope(), indent=2))
