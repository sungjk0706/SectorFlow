# -*- coding: utf-8 -*-
"""
키움 REST API - 토큰, 호가, 종가
legacy_pc_engine/kiwoom_api.py 이식 (Settings 기반)
"""
import httpx as requests
from typing import Optional

from app.core.broker_urls import build_broker_urls


class KiwoomApi:
    def __init__(self, settings: dict):
        self.settings = settings or {}
        self.host = build_broker_urls("kiwoom")["rest_base"]
        self.app_key = (self.settings.get("kiwoom_app_key") or "").strip()
        self.secret_key = (self.settings.get("kiwoom_app_secret") or "").strip()
        self.access_token: Optional[str] = None

    def get_access_token(self) -> Optional[str]:
        url = f"{self.host}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        data = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.secret_key}
        try:
            res = requests.post(url, headers=headers, json=data, timeout=10)
            if res.status_code == 200:
                j = res.json()
                self.access_token = j.get("token") or j.get("access_token")
                return self.access_token
            return None
        except Exception:
            return None
