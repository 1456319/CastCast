import json
import os
import time
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class RuleManager:
    def __init__(self, work_dir: str):
        self.rules_file = os.path.join(work_dir, "rulesets.json")
        self.telemetry_file = os.path.join(work_dir, "telemetry", "discovered_rulesets.jsonl")
        self.rules = self._load()

    def _load(self) -> dict:
        rules = {"domains": {}, "drm_blacklist": []}
        if os.path.exists(self.rules_file):
            try:
                with open(self.rules_file, "r") as f:
                    loaded = json.load(f)
                    rules["domains"].update(loaded.get("domains", {}))
                    rules["drm_blacklist"].extend(loaded.get("drm_blacklist", []))
            except Exception as e:
                logger.warning(f"Failed to load rulesets.json, resetting rules: {e}")
        return rules

    def _save(self):
        os.makedirs(os.path.dirname(self.rules_file), exist_ok=True)
        with open(self.rules_file, "w") as f:
            json.dump(self.rules, f, indent=2)

    def _log_telemetry(self, domain: str, rule_type: str, data: dict):
        if os.environ.get("CASTCAST_TELEMETRY_OPTOUT") == "1":
            return
        os.makedirs(os.path.dirname(self.telemetry_file), exist_ok=True)
        # Opt-out telemetry for automatically generated rulesets
        with open(self.telemetry_file, "a") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "domain": domain,
                "type": rule_type,
                "data": data
            }) + "\n")

    def register_drm(self, url: str):
        domain = urlparse(url).netloc
        if not domain or domain in self.rules["drm_blacklist"]:
            return
        self.rules["drm_blacklist"].append(domain)
        self._save()
        self._log_telemetry(domain, "drm", {"status": "blacklisted"})

    def register_manifest(self, url: str, headers: dict):
        domain = urlparse(url).netloc
        if not domain: return

        # Filter out ephemeral cookies/tokens, keep standard auth bypass headers
        clean_headers = {k: v for k, v in headers.items() if k.lower() in ("referer", "origin", "user-agent", "accept")}

        if domain not in self.rules["domains"] or self.rules["domains"][domain] != clean_headers:
            self.rules["domains"][domain] = clean_headers
            self._save()
            self._log_telemetry(domain, "manifest_headers", {"headers_required": list(clean_headers.keys())})

    def get_headers(self, url: str) -> dict:
        domain = urlparse(url).netloc
        return self.rules["domains"].get(domain, {})

    def is_drm(self, url: str) -> bool:
        domain = urlparse(url).netloc
        return domain in self.rules["drm_blacklist"]
