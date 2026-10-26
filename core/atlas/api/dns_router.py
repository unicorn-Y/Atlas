"""Manual custom-domain planning and DNS/TLS health checks.

Atlas never writes DNS records. This router prepares records for the selected
provider and probes public DNS plus the domain's certificate from this machine.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/dns", tags=["dns"])
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)


class DomainRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    target: str = Field(min_length=1, max_length=253)
    record_type: str = "A"
    provider: str = "manual"


def _domain(value: str) -> str:
    try:
        normalized = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HTTPException(status_code=422, detail="域名不是有效的 IDNA 主机名。") from exc
    if len(normalized) > 253 or "." not in normalized or not all(_LABEL.fullmatch(part) for part in normalized.split(".")):
        raise HTTPException(status_code=422, detail="请输入完整域名，例如 atlas.example.com。")
    return normalized


def _record_plan(payload: DomainRequest) -> dict[str, Any]:
    domain = _domain(payload.domain)
    record_type = payload.record_type.upper()
    if record_type not in {"A", "AAAA", "CNAME"}:
        raise HTTPException(status_code=422, detail="记录类型必须是 A、AAAA 或 CNAME。")
    provider = payload.provider.lower()
    if provider not in {"manual", "cloudflare", "route53"}:
        raise HTTPException(status_code=422, detail="请选择 Manual、Cloudflare 或 Route 53。")
    target = payload.target.strip().rstrip(".")
    if record_type in {"A", "AAAA"}:
        try:
            address = ipaddress.ip_address(target)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{record_type} 记录目标必须是 IP 地址。") from exc
        if (record_type == "A") != (address.version == 4):
            raise HTTPException(status_code=422, detail=f"{record_type} 记录目标地址族不匹配。")
        target = address.compressed
    else:
        target = _domain(target)
    return {
        "domain": domain, "provider": provider,
        "record": {"type": record_type, "name": domain, "value": target, "ttl": 300,
                   "proxy": "DNS only (gray cloud)" if provider == "cloudflare" else None},
        "status": "pending_manual_change",
        "note": "请在所选 DNS 服务商控制台手动添加此记录；Atlas 不会写入或修改 DNS。TLS 检查需在记录生效且 HTTPS 服务已配置后运行。",
    }


def _probe(payload: DomainRequest) -> dict[str, Any]:
    plan = _record_plan(payload)
    domain = plan["domain"]
    expected = plan["record"]["value"]
    try:
        resolved = sorted({item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM)})
        dns_error = None
    except OSError as exc:
        resolved, dns_error = [], str(exc)
    try:
        canonical_name, aliases, _addresses = socket.gethostbyname_ex(domain)
        cname_match = expected.lower() in {canonical_name.rstrip(".").lower(), *(alias.rstrip(".").lower() for alias in aliases)}
    except OSError:
        cname_match = False
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=domain) as secured:
                certificate = secured.getpeercert()
                tls = {"ok": True, "version": secured.version(),
                       "expires_at": certificate.get("notAfter"),
                       "subject": dict(item[0] for item in certificate.get("subject", ()))}
    except (OSError, ssl.SSLError, ValueError) as exc:
        tls = {"ok": False, "error": str(exc)}
    try:
        expected_address = str(ipaddress.ip_address(expected))
    except ValueError:
        expected_address = None
    matches_expected = expected_address in resolved if expected_address else cname_match
    return {
        "domain": domain,
        "dns": {"ok": bool(resolved), "addresses": resolved, "expected": expected,
                "matches_expected": matches_expected,
                "error": dns_error},
        "tls": tls,
        "record_plan": plan["record"],
        "status": "healthy" if resolved and tls["ok"] and matches_expected else "attention",
    }


@router.post("/plan")
async def dns_record_plan(payload: DomainRequest) -> dict[str, Any]:
    return _record_plan(payload)


@router.post("/verify")
async def verify_dns_and_tls(payload: DomainRequest) -> dict[str, Any]:
    return await asyncio.to_thread(_probe, payload)
