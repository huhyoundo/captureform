from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_AD_URL = "https://raw.githubusercontent.com/huhyoundo/captureform/master/ads/callcap_ad.json"
_COOLDOWN_SECONDS = 10 * 60  # 10 minutes between ad shows
_CAPTURE_INTERVAL = 5         # Show ad every Nth capture
_NETWORK_TIMEOUT = 5          # Seconds before network fetch times out

_FALLBACK_AD: dict[str, Any] = {
    "ad_id": "fallback_001",
    "title": "Callcap Pro로 업그레이드",
    "description": "더 강력한 캡처 기능, 무제한 저장, OCR 무제한 사용.\n지금 Pro로 업그레이드하세요!",
    "image_url": "",
    "click_url": "https://compl.kr/callcap/pro",
    "sponsor": "Callcap",
}


class AdManager:
    """Manages ad fetching, cooldown, and analytics for Callcap.

    Usage example (from main.py)::

        from ads.ad_manager import AdManager
        from ads.ad_popup import AdPopupWindow

        ad_manager = AdManager()

        # On startup (after 3-second delay):
        QTimer.singleShot(3000, lambda: _maybe_show_ad(ad_manager))

        # After every capture:
        capture_count += 1
        if ad_manager.should_show_ad_for_capture(capture_count):
            _maybe_show_ad(ad_manager)

        def _maybe_show_ad(mgr):
            if not mgr.should_show_ad():
                return
            ad_data = mgr.get_ad_data()
            popup = AdPopupWindow(ad_data)
            popup.ad_clicked.connect(lambda ad_id: mgr.record_ad_clicked(ad_id))
            popup.show()
            mgr.record_ad_shown()
    """

    def __init__(
        self,
        ad_url: str = _DEFAULT_AD_URL,
        state_dir: Path | None = None,
    ) -> None:
        self._ad_url = ad_url
        self._state_dir = state_dir or (Path.home() / ".callcap")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._state_dir / "ad_state.json"

        self._state: dict[str, Any] = self._load_state()
        self._cached_ad: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_show_ad(self) -> bool:
        """Return True when the cooldown has elapsed and the user has not
        suppressed ads for today."""
        if self._is_suppressed_today():
            _log.debug("Ad suppressed for today.")
            return False

        last_shown = self._state.get("last_shown_ts", 0.0)
        elapsed = time.time() - float(last_shown)
        if elapsed < _COOLDOWN_SECONDS:
            _log.debug(
                "Ad cooldown active: %.0f / %d seconds elapsed.",
                elapsed,
                _COOLDOWN_SECONDS,
            )
            return False

        return True

    def should_show_ad_for_capture(self, capture_count: int) -> bool:
        """Return True when *capture_count* is a multiple of the capture
        interval (every 5th capture) AND the cooldown has elapsed."""
        if capture_count <= 0:
            return False
        if capture_count % _CAPTURE_INTERVAL != 0:
            return False
        return self.should_show_ad()

    def get_ad_data(self) -> dict[str, Any]:
        """Fetch ad data from the remote endpoint.

        Falls back to *_FALLBACK_AD* on any network or parse error.
        The result is cached for the lifetime of this process.
        """
        if self._cached_ad is not None:
            return self._cached_ad

        ad = self._fetch_remote_ad()
        if ad is None:
            _log.warning("Using fallback ad (remote fetch failed).")
            ad = dict(_FALLBACK_AD)

        self._cached_ad = ad
        return ad

    def record_ad_shown(self) -> None:
        """Update the timestamp used to enforce the cooldown."""
        self._state["last_shown_ts"] = time.time()
        self._save_state()
        _log.debug("Ad shown timestamp updated.")

    def record_ad_clicked(self, ad_id: str) -> None:
        """Log an ad click for analytics.

        The click is appended to a local JSONL file in the state directory.
        Extend this method to POST to a remote analytics endpoint if needed.
        """
        entry = {
            "event": "ad_click",
            "ad_id": ad_id,
            "ts": datetime.utcnow().isoformat() + "Z",
        }
        click_log = self._state_dir / "ad_clicks.jsonl"
        try:
            with click_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.warning("Could not write ad click log: %s", exc)

        _log.info("Ad clicked: ad_id=%s", ad_id)

    def suppress_today(self) -> None:
        """Mark today's date so ads are not shown for the rest of the day."""
        self._state["suppressed_date"] = date.today().isoformat()
        self._save_state()
        _log.debug("Ads suppressed for today.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_suppressed_today(self) -> bool:
        suppressed_date = self._state.get("suppressed_date", "")
        return suppressed_date == date.today().isoformat()

    def _fetch_remote_ad(self) -> dict[str, Any] | None:
        """HTTP GET the ad endpoint and return the parsed JSON dict.

        Returns None on any error so callers can fall back gracefully.
        """
        try:
            req = Request(
                self._ad_url,
                headers={"Accept": "application/json", "User-Agent": "Callcap/1.0"},
            )
            with urlopen(req, timeout=_NETWORK_TIMEOUT) as resp:
                raw = resp.read()
        except HTTPError as exc:
            _log.warning("Ad endpoint returned HTTP %d: %s", exc.code, exc.reason)
            return None
        except URLError as exc:
            _log.warning("Ad endpoint unreachable: %s", exc.reason)
            return None
        except OSError as exc:
            _log.warning("Network error fetching ad: %s", exc)
            return None

        try:
            data: Any = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _log.warning("Failed to parse ad JSON: %s", exc)
            return None

        if not isinstance(data, dict):
            _log.warning("Ad endpoint returned unexpected type: %s", type(data).__name__)
            return None

        # Validate required fields; fill missing ones with fallback values.
        ad: dict[str, Any] = {}
        fallback = _FALLBACK_AD
        for key in ("ad_id", "title", "description", "image_url", "click_url", "sponsor"):
            ad[key] = data.get(key, fallback.get(key, ""))

        return ad

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        if self._state_path.exists():
            try:
                with self._state_path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    return loaded
            except (json.JSONDecodeError, OSError) as exc:
                _log.warning("Could not load ad state: %s", exc)
        return {}

    def _save_state(self) -> None:
        try:
            with self._state_path.open("w", encoding="utf-8") as fh:
                json.dump(self._state, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            _log.warning("Could not save ad state: %s", exc)
