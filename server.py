import os
import httpx
from xml.etree import ElementTree as ET
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Namecheap")

API_URL = os.getenv("NAMECHEAP_API_URL", "https://api.namecheap.com/xml.response")
API_USER = os.getenv("NAMECHEAP_API_USER")
API_KEY = os.getenv("NAMECHEAP_API_KEY")
USERNAME = os.getenv("NAMECHEAP_USERNAME")
CLIENT_IP = os.getenv("NAMECHEAP_CLIENT_IP")


def base_params(command: str) -> dict:
    return {
        "ApiUser": API_USER,
        "ApiKey": API_KEY,
        "UserName": USERNAME,
        "ClientIp": CLIENT_IP,
        "Command": command,
    }


async def call_api(params: dict) -> ET.Element:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(API_URL, params=params)
        resp.raise_for_status()
    root = ET.fromstring(resp.text)
    status = root.attrib.get("Status", "")
    if status != "OK":
        errors = root.findall(".//{urn:schemas-microsoft-com:xml-diffgram-v1}Error") or root.findall(".//Error")
        msg = "; ".join(e.text for e in errors if e.text) or "Unknown API error"
        raise RuntimeError(msg)
    return root


@mcp.tool()
async def check_domain(domain: str) -> str:
    """Check if a domain name is available for registration."""
    params = base_params("namecheap.domains.check")
    params["DomainList"] = domain
    root = await call_api(params)
    results = []
    for d in root.iter("{https://api.namecheap.com/xml.response}DomainCheckResult"):
        name = d.attrib.get("Domain", domain)
        available = d.attrib.get("Available", "false")
        results.append(f"{name}: {'available' if available == 'true' else 'not available'}")
    return "\n".join(results) if results else "No results returned."


@mcp.tool()
async def list_domains(page: int = 1, page_size: int = 20) -> str:
    """List all domains in your Namecheap account."""
    params = base_params("namecheap.domains.getList")
    params["Page"] = page
    params["PageSize"] = page_size
    root = await call_api(params)
    domains = []
    for d in root.iter("{https://api.namecheap.com/xml.response}Domain"):
        name = d.attrib.get("Name", "")
        expires = d.attrib.get("Expires", "")
        auto_renew = d.attrib.get("AutoRenew", "")
        domains.append(f"{name} | expires: {expires} | auto-renew: {auto_renew}")
    return "\n".join(domains) if domains else "No domains found."


@mcp.tool()
async def get_dns_records(domain: str) -> str:
    """Get DNS host records for a domain."""
    sld, *tld_parts = domain.split(".")
    tld = ".".join(tld_parts)
    params = base_params("namecheap.domains.dns.getHosts")
    params["SLD"] = sld
    params["TLD"] = tld
    root = await call_api(params)
    records = []
    for h in root.iter("{https://api.namecheap.com/xml.response}host"):
        records.append(
            f"{h.attrib.get('Type','')}\t{h.attrib.get('Name','')}\t{h.attrib.get('Address','')}\tTTL:{h.attrib.get('TTL','')}"
        )
    return "\n".join(records) if records else "No DNS records found."


@mcp.tool()
async def set_dns_records(domain: str, records: list[dict]) -> str:
    """
    Set DNS host records for a domain. Replaces all existing records.

    Each record in the list should have: HostName, RecordType, Address, TTL (optional, default 1800).
    Example: [{"HostName": "@", "RecordType": "A", "Address": "1.2.3.4"}]
    """
    sld, *tld_parts = domain.split(".")
    tld = ".".join(tld_parts)
    params = base_params("namecheap.domains.dns.setHosts")
    params["SLD"] = sld
    params["TLD"] = tld
    for i, record in enumerate(records, start=1):
        params[f"HostName{i}"] = record.get("HostName", "@")
        params[f"RecordType{i}"] = record.get("RecordType", "A")
        params[f"Address{i}"] = record["Address"]
        params[f"TTL{i}"] = record.get("TTL", 1800)
    root = await call_api(params)
    result = root.find(".//{https://api.namecheap.com/xml.response}DomainDNSSetHostsResult")
    if result is not None and result.attrib.get("IsSuccess") == "true":
        return f"DNS records for {domain} updated successfully."
    return "Update may have failed — check your Namecheap dashboard."


@mcp.tool()
async def get_account_balance() -> str:
    """Get the current balance of your Namecheap account."""
    params = base_params("namecheap.users.getBalances")
    root = await call_api(params)
    bal = root.find(".//{https://api.namecheap.com/xml.response}UserGetBalancesResult")
    if bal is not None:
        return (
            f"Available balance: {bal.attrib.get('AvailableBalance', 'N/A')} "
            f"| Currency: {bal.attrib.get('Currency', 'USD')}"
        )
    return "Could not retrieve balance."


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
