from __future__ import annotations

import json
import os
from urllib import parse, request


class LocalAPIBridge:
    def __init__(
        self,
        crm_base: str,
        intake_base: str,
        tenant_scope: str,
        legal_qa_base: str = "http://127.0.0.1:8015",
    ) -> None:
        self.crm_base = crm_base.rstrip("/")
        self.intake_base = intake_base.rstrip("/")
        self.legal_qa_base = legal_qa_base.rstrip("/")
        self.tenant_scope = tenant_scope
        self.internal_api_token = os.getenv("LEGASVEX_INTERNAL_API_TOKEN")
        if not self.internal_api_token and os.getenv("LEGASVEX_ALLOW_DEV_TOKEN") == "1":
            self.internal_api_token = "dev-demo-token"

    def seed_demo(self) -> dict:
        query = parse.urlencode({"tenant_scope": self.tenant_scope})
        return self._request_json(f"{self.crm_base}/crm/demo/seed?{query}", method="POST")

    def dashboard(self) -> dict:
        query = parse.urlencode({"tenant_scope": self.tenant_scope})
        return self._request_json(f"{self.crm_base}/crm/dashboard?{query}")

    def portfolio(self) -> list[dict]:
        query = parse.urlencode({"tenant_scope": self.tenant_scope})
        return self._request_json(f"{self.crm_base}/crm/portfolio?{query}")

    def submit_intake(self, actor_id: str, client_name: str, summary: str, tags: list[str] | None = None) -> dict:
        payload = {
            "tenant_scope": self.tenant_scope,
            "actor_id": actor_id,
            "client_name": client_name,
            "summary": summary,
            "tags": tags or [],
        }
        return self._request_json(
            f"{self.intake_base}/intake/submit",
            method="POST",
            payload=payload,
        )

    def matter(self, matter_id: str) -> dict:
        return self._request_json(f"{self.crm_base}/crm/matters/{matter_id}")

    def contract_risk_scan(
        self,
        actor_id: str,
        matter_id: str,
        text: str,
        source_document_id: str | None = None,
        jurisdiction: str = "RU",
    ) -> dict:
        payload = {
            "tenant_scope": self.tenant_scope,
            "actor_id": actor_id,
            "action": "CONTRACT_RISK_SCAN",
            "matter_id": matter_id,
            "jurisdiction": jurisdiction,
            "source_document_id": source_document_id,
            "text": text,
        }
        return self._request_json(
            f"{self.legal_qa_base}/legal-qa/contract-risk-scan",
            method="POST",
            payload=payload,
        )

    def document_review(
        self,
        actor_id: str,
        matter_id: str,
        metadata: dict,
        review_type: str = "contract",
    ) -> dict:
        filename = metadata.get("original_filename") or metadata.get("stored_path") or "telegram document"
        caption = metadata.get("caption") or ""
        sha256 = metadata.get("sha256") or ""
        extracted_text = (metadata.get("extracted_text") or "").strip()
        text = (
            f"Telegram document uploaded for lawyer review. "
            f"Review type: {review_type}. "
            f"Filename: {filename}. "
            f"SHA256: {sha256}. "
            f"Caption: {caption}"
        )
        if extracted_text:
            text = f"{text}\n\nExtracted document text:\n{extracted_text}"
        return self.contract_risk_scan(
            actor_id=actor_id,
            matter_id=matter_id,
            text=text,
            source_document_id=sha256 or "telegram-upload",
        )

    def _request_json(self, url: str, method: str = "GET", payload: dict | None = None) -> dict:
        body = None
        headers = {}
        if self.internal_api_token:
            headers["Authorization"] = f"Bearer {self.internal_api_token}"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=4) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return {}
