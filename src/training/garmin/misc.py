"""Esportazione di profilo, dispositivi, peso e record personali."""

import json
import time
from datetime import date
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

from .client import safe_call
from .config import REQUEST_DELAY


def export_misc(api: Garmin, out_dir: Path, start_date: date, end_date: date) -> None:
    misc_dir = out_dir / "misc"
    misc_dir.mkdir(parents=True, exist_ok=True)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    calls = {
        "profile.json": lambda: api.get_full_name(),
        "devices.json": lambda: api.get_devices(),
        "personal_records.json": lambda: api.get_personal_record(),
        "body_composition.json": lambda: api.get_body_composition(start_str, end_str),
        "weigh_ins.json": lambda: api.get_weigh_ins(start_str, end_str),
    }

    print("Scarico profilo, dispositivi, peso e record personali...")
    for filename, func in calls.items():
        try:
            data = safe_call(func)
        except GarminConnectAuthenticationError:
            raise
        except Exception as exc:
            # Come prima: una delle cinque che non risponde non ferma le
            # altre. Ora il motivo si vede.
            print(f"  Non disponibile ({exc}): {filename}")
            data = None
        if data is not None:
            with open(misc_dir / filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            print(f"  Salvato {filename}")
        else:
            print(f"  Non disponibile: {filename}")
        time.sleep(REQUEST_DELAY)
