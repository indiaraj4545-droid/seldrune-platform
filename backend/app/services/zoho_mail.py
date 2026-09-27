from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx

from backend.app.core.config import settings


class ZohoMailError(RuntimeError):
    """Raised when Zoho Mail rejects or cannot complete an API request."""


_DATA_CENTERS = {
    "com": ("https://accounts.zoho.com", "https://mail.zoho.com"),
    "eu": ("https://accounts.zoho.eu", "https://mail.zoho.eu"),
    "in": ("https://accounts.zoho.in", "https://mail.zoho.in"),
    "com.au": ("https://accounts.zoho.com.au", "https://mail.zoho.com.au"),
    "jp": ("https://accounts.zoho.jp", "https://mail.zoho.jp"),
    "ca": ("https://accounts.zohocloud.ca", "https://mail.zohocloud.ca"),
    "com.cn": ("https://accounts.zoho.com.cn", "https://mail.zoho.com.cn"),
    "ae": ("https://accounts.zoho.ae", "https://mail.zoho.ae"),
    "sa": ("https://accounts.zoho.sa", "https://mail.zoho.sa"),
}
OAUTH_SCOPES = ",".join(
    (
        "ZohoMail.accounts.READ",
        "ZohoMail.folders.READ",
        "ZohoMail.messages.READ",
        "ZohoMail.messages.CREATE",
        "ZohoMail.organization.domains.READ",
        "ZohoMail.organization.domains.UPDATE",
    )
)


@dataclass(frozen=True)
class ZohoTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int


def _hosts(data_center: str) -> tuple[str, str]:
    try:
        return _DATA_CENTERS[data_center]
    except KeyError as exc:
        raise ZohoMailError("The Zoho Mail data center is not supported") from exc


def authorization_url(*, state: str, redirect_uri: str) -> str:
    accounts_url, _ = _hosts(settings.zoho_mail_data_center)
    if not settings.zoho_mail_client_id or not settings.zoho_mail_client_secret:
        raise ZohoMailError("Zoho Mail OAuth credentials are not configured")
    query = urlencode(
        {
            "client_id": settings.zoho_mail_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{accounts_url}/oauth/v2/auth?{query}"


def _token_request(data_center: str, data: dict[str, str]) -> ZohoTokens:
    accounts_url, _ = _hosts(data_center)
    if not settings.zoho_mail_client_id or not settings.zoho_mail_client_secret:
        raise ZohoMailError("Zoho Mail OAuth credentials are not configured")
    form = {
        **data,
        "client_id": settings.zoho_mail_client_id,
        "client_secret": settings.zoho_mail_client_secret,
    }
    try:
        response = httpx.post(
            f"{accounts_url}/oauth/v2/token", data=form, timeout=15.0
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ZohoMailError("Zoho Mail token exchange failed") from exc
    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ZohoMailError("Zoho Mail did not return an access token")
    refresh_token = result.get("refresh_token")
    expires_in = result.get("expires_in", 3600)
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError) as exc:
        raise ZohoMailError("Zoho Mail returned an invalid token lifetime") from exc
    if expires_in <= 0:
        raise ZohoMailError("Zoho Mail returned an invalid token lifetime")
    return ZohoTokens(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        expires_in=expires_in,
    )


def exchange_authorization_code(
    *, data_center: str, code: str, redirect_uri: str
) -> ZohoTokens:
    return _token_request(
        data_center,
        {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )


def refresh_access_token(*, data_center: str, refresh_token: str) -> ZohoTokens:
    return _token_request(
        data_center,
        {"refresh_token": refresh_token, "grant_type": "refresh_token"},
    )


def _mail_request(
    *,
    data_center: str,
    access_token: str,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
) -> object:
    _, mail_url = _hosts(data_center)
    try:
        response = httpx.request(
            method,
            f"{mail_url}/api{path}",
            params=params,
            json=body,
            headers={
                "Authorization": f"Zoho-oauthtoken {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ZohoMailError("Zoho Mail API request failed") from exc
    status_body = result.get("status") if isinstance(result, dict) else None
    if isinstance(status_body, dict):
        code = status_body.get("code")
        if code is not None and str(code) not in {"200", "201"}:
            raise ZohoMailError(f"Zoho Mail rejected the request (code {code})")
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    return result


def list_accounts(*, data_center: str, access_token: str) -> list[dict[str, object]]:
    result = _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="GET",
        path="/accounts",
    )
    if not isinstance(result, list):
        raise ZohoMailError("Zoho Mail returned an invalid account list")
    return [item for item in result if isinstance(item, dict)]


def list_folders(
    *, data_center: str, account_id: str, access_token: str
) -> list[dict[str, object]]:
    result = _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="GET",
        path=f"/accounts/{account_id}/folders",
    )
    if not isinstance(result, list):
        raise ZohoMailError("Zoho Mail returned an invalid folder list")
    return [item for item in result if isinstance(item, dict)]


def list_messages(
    *, data_center: str, account_id: str, folder_id: str, access_token: str, limit: int
) -> list[dict[str, object]]:
    result = _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="GET",
        path=f"/accounts/{account_id}/messages/view",
        params={
            "folderId": folder_id,
            "start": "1",
            "limit": str(limit),
            "sortBy": "date",
            "sortorder": "false",
            "threadedMails": "false",
            "includeto": "true",
        },
    )
    if not isinstance(result, list):
        raise ZohoMailError("Zoho Mail returned an invalid message list")
    return [item for item in result if isinstance(item, dict)]


def get_message_content(
    *,
    data_center: str,
    account_id: str,
    folder_id: str,
    message_id: str,
    access_token: str,
) -> str:
    result = _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="GET",
        path=f"/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/content",
    )
    if not isinstance(result, dict) or not isinstance(result.get("content"), str):
        raise ZohoMailError("Zoho Mail returned invalid message content")
    return result["content"]


def get_domain_details(
    *, data_center: str, zoho_org_id: str, domain: str, access_token: str
) -> dict[str, object]:
    result = _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="GET",
        path=f"/organization/{zoho_org_id}/domains/{domain}",
    )
    if not isinstance(result, dict):
        raise ZohoMailError("Zoho Mail returned invalid domain authentication details")
    return result


def add_dkim_details(
    *,
    data_center: str,
    zoho_org_id: str,
    domain: str,
    selector: str,
    access_token: str,
) -> object:
    return _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="PUT",
        path=f"/organization/{zoho_org_id}/domains/{domain}",
        body={
            "mode": "addDkimDetail",
            "selector": selector,
            "hashType": "sha256",
            "isDefault": True,
        },
    )


def verify_spf_record(
    *, data_center: str, zoho_org_id: str, domain: str, access_token: str
) -> object:
    return _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="PUT",
        path=f"/organization/{zoho_org_id}/domains/{domain}",
        body={"mode": "VerifySpfRecord"},
    )


def verify_dkim_key(
    *,
    data_center: str,
    zoho_org_id: str,
    domain: str,
    dkim_id: str,
    access_token: str,
) -> object:
    return _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="PUT",
        path=f"/organization/{zoho_org_id}/domains/{domain}",
        body={"mode": "verifyDkimKey", "dkimId": dkim_id},
    )


def enable_dkim(
    *, data_center: str, zoho_org_id: str, domain: str, access_token: str
) -> object:
    return _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="PUT",
        path=f"/organization/{zoho_org_id}/domains/{domain}",
        body={"mode": "enableDKIM"},
    )


def send_message(
    *,
    data_center: str,
    account_id: str,
    access_token: str,
    from_address: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    content: str,
) -> object:
    return _mail_request(
        data_center=data_center,
        access_token=access_token,
        method="POST",
        path=f"/accounts/{account_id}/messages",
        body={
            "fromAddress": from_address,
            "toAddress": ",".join(to),
            "ccAddress": ",".join(cc),
            "bccAddress": ",".join(bcc),
            "subject": subject,
            "content": content,
            "mailFormat": "plaintext",
            "encoding": "UTF-8",
        },
    )


class _PlainTextParser(HTMLParser):
    _BLOCK_TAGS = {"br", "div", "p", "li", "tr", "h1", "h2", "h3", "blockquote"}
    _IGNORED_TAGS = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._IGNORED_TAGS:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def message_to_plain_text(content: str) -> str:
    parser = _PlainTextParser()
    try:
        parser.feed(content)
    except Exception:
        return content[:50_000]
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)[:50_000]
