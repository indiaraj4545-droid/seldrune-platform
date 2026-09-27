from __future__ import annotations

import json
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies import CurrentUserDep, SessionDep
from backend.app.core.config import settings
from backend.app.core.rbac import Role
from backend.app.models.mailbox_access import MailboxAccess
from backend.app.models.membership import Membership
from backend.app.models.seldrune_mail import (
    Mailbox,
    MailDomain,
    MailDraft,
    ZohoMailConnection,
    ZohoMailOAuthState,
)
from backend.app.models.user import User
from backend.app.services.secret_vault import (
    SecretVaultError,
    decrypt_secret_value,
    encrypt_secret_value,
)
from backend.app.services.zoho_mail import (
    ZohoMailError,
    add_dkim_details,
    authorization_url as zoho_authorization_url,
    enable_dkim,
    exchange_authorization_code,
    get_domain_details,
    get_message_content,
    list_accounts,
    list_folders,
    list_messages,
    message_to_plain_text,
    refresh_access_token,
    send_message as zoho_send_message,
    verify_dkim_key,
    verify_spf_record,
)

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
page_router = APIRouter(tags=["seldrune-mail"])
router = APIRouter(prefix="/organizations/{organization_id}/mail", tags=["seldrune-mail"])
oauth_router = APIRouter(prefix="/mail/zoho", tags=["seldrune-mail"])

_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
_LOCAL_PART_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$")
_DEFAULT_MAILBOXES = (("founder", "Seldrune Founder"),)


@page_router.get("/mail", include_in_schema=False)
def mail_workspace_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "mail.html")


class DomainCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=3, max_length=253)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip().rstrip(".").lower()
        if not _DOMAIN_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid domain name, such as mail.example.com.")
        return normalized


class MailboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: UUID
    local_part: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=2, max_length=160)

    @field_validator("local_part")
    @classmethod
    def normalize_local_part(cls, value: str) -> str:
        normalized = value.strip().lower()
        if (
            not _LOCAL_PART_PATTERN.fullmatch(normalized)
            or ".." in normalized
            or normalized.startswith(".")
            or normalized.endswith(".")
        ):
            raise ValueError("Use a valid mailbox name, such as hello or team.eu.")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return value.strip()


class AccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    permission: Literal["read", "write"] = "write"


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: list[EmailStr] = Field(min_length=1, max_length=25)
    cc: list[EmailStr] = Field(default_factory=list, max_length=25)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=25)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=100_000)

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        return value.strip()


class ZohoConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mailbox_id: UUID


class SendMailRequest(DraftCreate):
    draft_id: UUID | None = None


@router.post("/zoho/connect")
def start_zoho_mail_connection(
    organization_id: UUID,
    payload: ZohoConnectRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    mailbox = session.scalar(
        select(Mailbox).where(
            Mailbox.id == payload.mailbox_id,
            Mailbox.organization_id == organization_id,
        )
    )
    if mailbox is None:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    if not settings.zoho_mail_client_id or not settings.zoho_mail_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Zoho Mail OAuth credentials have not been configured for this "
                "Seldrune deployment."
            ),
        )
    state_value = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state_value.encode("utf-8")).hexdigest()
    state = ZohoMailOAuthState(
        state_hash=state_hash,
        organization_id=organization_id,
        mailbox_id=mailbox.id,
        user_id=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session.add(state)
    session.commit()
    callback_url = (
        f"{settings.public_app_url.rstrip('/')}{settings.api_v1_prefix}"
        "/mail/zoho/oauth/callback"
    )
    try:
        url = zoho_authorization_url(state=state_value, redirect_uri=callback_url)
    except ZohoMailError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url}


@oauth_router.get("/oauth/callback", include_in_schema=False)
def complete_zoho_mail_connection(
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if not state:
        return _callback_redirect("invalid")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    oauth_state = session.get(ZohoMailOAuthState, state_hash)
    now = datetime.now(UTC)
    if oauth_state is None or oauth_state.used_at is not None:
        return _callback_redirect("invalid")
    expires_at = oauth_state.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        oauth_state.used_at = now
        session.commit()
        return _callback_redirect("expired")
    oauth_state.used_at = now
    session.commit()
    if error or not code:
        return _callback_redirect("denied")

    mailbox = session.scalar(
        select(Mailbox).where(
            Mailbox.id == oauth_state.mailbox_id,
            Mailbox.organization_id == oauth_state.organization_id,
        )
    )
    if mailbox is None:
        return _callback_redirect("invalid")
    callback_url = (
        f"{settings.public_app_url.rstrip('/')}{settings.api_v1_prefix}"
        "/mail/zoho/oauth/callback"
    )
    try:
        tokens = exchange_authorization_code(
            data_center=settings.zoho_mail_data_center,
            code=code,
            redirect_uri=callback_url,
        )
        if not tokens.refresh_token:
            return _callback_redirect("failed")
        accounts = list_accounts(
            data_center=settings.zoho_mail_data_center,
            access_token=tokens.access_token,
        )
    except ZohoMailError:
        return _callback_redirect("failed")

    expected_address = mailbox.email_address.casefold()
    account_match = None
    for account in accounts:
        addresses = account.get("emailAddress")
        known_addresses = {
            str(account.get("primaryEmailAddress", "")).casefold(),
            str(account.get("mailboxAddress", "")).casefold(),
        }
        if isinstance(addresses, list):
            known_addresses.update(
                str(item.get("mailId", "")).casefold()
                for item in addresses
                if isinstance(item, dict)
                and item.get("isConfirmed") is not False
                and item.get("status") is not False
            )
        if expected_address in known_addresses:
            account_match = account
            break
    if account_match is None:
        return _callback_redirect("wrong_mailbox")

    policy_id = account_match.get("policyId")
    org_id = policy_id.get("zoid") if isinstance(policy_id, dict) else None
    org_id = org_id or account_match.get("zoid") or account_match.get("organizationId")
    if not org_id:
        return _callback_redirect("failed")
    account_id = account_match.get("accountId")
    if not account_id or not re.fullmatch(r"\d+", str(account_id)):
        return _callback_redirect("failed")
    if not re.fullmatch(r"\d+", str(org_id)):
        return _callback_redirect("failed")

    connection = session.scalar(
        select(ZohoMailConnection).where(
            ZohoMailConnection.mailbox_id == mailbox.id,
            ZohoMailConnection.organization_id == oauth_state.organization_id,
        )
    )
    if connection is None:
        connection = ZohoMailConnection(
            organization_id=oauth_state.organization_id,
            mailbox_id=mailbox.id,
            account_id=str(account_id),
            zoho_org_id=str(org_id),
            account_email=mailbox.email_address,
            data_center=settings.zoho_mail_data_center,
            encrypted_access_token=encrypt_secret_value(tokens.access_token),
            encrypted_refresh_token=encrypt_secret_value(tokens.refresh_token),
            access_token_expires_at=now + timedelta(seconds=tokens.expires_in),
            connected_by_user_id=oauth_state.user_id,
        )
        session.add(connection)
    else:
        connection.account_id = str(account_id)
        connection.zoho_org_id = str(org_id)
        connection.account_email = mailbox.email_address
        connection.data_center = settings.zoho_mail_data_center
        connection.encrypted_access_token = encrypt_secret_value(tokens.access_token)
        connection.encrypted_refresh_token = encrypt_secret_value(tokens.refresh_token)
        connection.access_token_expires_at = now + timedelta(seconds=tokens.expires_in)
        connection.connected_by_user_id = oauth_state.user_id
    session.commit()
    return _callback_redirect("connected")


def _membership(
    session: SessionDep,
    organization_id: UUID,
    current_user: User,
) -> Membership:
    membership = session.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Organization membership required")
    return membership


def _is_manager(membership: Membership) -> bool:
    return membership.role in {Role.OWNER.value, Role.ADMIN.value}


def _require_manager(membership: Membership) -> None:
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="Mail administration access required")


def _mailbox(
    session: SessionDep,
    organization_id: UUID,
    mailbox_id: UUID,
    user: User,
    *,
    write: bool = False,
) -> Mailbox:
    membership = _membership(session, organization_id, user)
    mailbox = session.scalar(
        select(Mailbox).where(
            Mailbox.id == mailbox_id,
            Mailbox.organization_id == organization_id,
        )
    )
    if mailbox is None:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    access = session.get(MailboxAccess, (mailbox.id, user.id))
    if membership.role not in {Role.OWNER.value, Role.ADMIN.value}:
        if access is None:
            raise HTTPException(status_code=403, detail="Mailbox access required")
        if write and access.permission != "write":
            raise HTTPException(status_code=403, detail="Mailbox write access required")
    return mailbox


def _zoho_connection(
    session: SessionDep,
    organization_id: UUID,
    mailbox_id: UUID,
) -> ZohoMailConnection:
    connection = session.scalar(
        select(ZohoMailConnection).where(
            ZohoMailConnection.organization_id == organization_id,
            ZohoMailConnection.mailbox_id == mailbox_id,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect this mailbox to Zoho Mail before using live email.",
        )
    return connection


def _zoho_access_token(
    session: SessionDep,
    connection: ZohoMailConnection,
) -> str:
    now = datetime.now(UTC)
    expires_at = connection.access_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    try:
        if expires_at > now + timedelta(seconds=90):
            return decrypt_secret_value(connection.encrypted_access_token)
        refresh_token = decrypt_secret_value(connection.encrypted_refresh_token)
        tokens = refresh_access_token(
            data_center=connection.data_center,
            refresh_token=refresh_token,
        )
    except (SecretVaultError, ZohoMailError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Zoho Mail authorization expired. Reconnect this mailbox.",
        ) from exc
    connection.encrypted_access_token = encrypt_secret_value(tokens.access_token)
    connection.access_token_expires_at = now + timedelta(seconds=tokens.expires_in)
    session.commit()
    return tokens.access_token


def _zoho_domain_authentication(
    *,
    session: SessionDep,
    mailbox: Mailbox,
    connection: ZohoMailConnection,
) -> dict[str, object]:
    token = _zoho_access_token(session, connection)
    domain = mailbox.email_address.rsplit("@", 1)[-1].lower()
    try:
        details = get_domain_details(
            data_center=connection.data_center,
            zoho_org_id=connection.zoho_org_id,
            domain=domain,
            access_token=token,
        )
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho could not check the domain authentication status.",
        ) from exc
    dkim_details = details.get("dkimDetailList")
    dkim_entries = (
        [item for item in dkim_details if isinstance(item, dict)]
        if isinstance(dkim_details, list)
        else []
    )
    dkim = next((item for item in dkim_entries if item.get("isDefault")), None)
    if dkim is None and dkim_entries:
        dkim = dkim_entries[0]
    selector = str(dkim.get("selector")) if dkim and dkim.get("selector") else None
    record_value = (
        str(dkim.get("publicKey")) if dkim and dkim.get("publicKey") else None
    )
    try:
        txt_response = httpx.get(
            "https://dns.google/resolve",
            params={"name": domain, "type": "TXT"},
            timeout=8.0,
        )
        txt_response.raise_for_status()
        txt_answers = txt_response.json().get("Answer", [])
    except (httpx.HTTPError, ValueError):
        txt_answers = []
    txt_records = [
        str(answer.get("data", "")).strip().strip('"')
        for answer in txt_answers
        if isinstance(answer, dict) and answer.get("data")
    ]
    spf_records = [
        record for record in txt_records if record.lower().startswith("v=spf1")
    ]
    spf_verified = bool(details.get("spfstatus"))
    dkim_verified = bool(details.get("dkimstatus"))
    return {
        "ready": spf_verified and dkim_verified,
        "spf_verified": spf_verified,
        "dkim_verified": dkim_verified,
        "spf_records": spf_records,
        "dkim_selector": selector,
        "dkim_record_name": f"{selector}._domainkey" if selector else None,
        "dkim_record_value": record_value,
        "message": (
            "Zoho confirms SPF and DKIM are enabled for this domain."
            if spf_verified and dkim_verified
            else (
                "Add or verify the Zoho SPF and DKIM records before sending to "
                "external recipients."
            )
        ),
    }


def _callback_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{settings.public_app_url.rstrip('/')}/mail?zoho={result}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _workspace(
    session: SessionDep,
    organization_id: UUID,
    membership: Membership,
    user: User,
) -> dict[str, object]:
    domains = list(
        session.scalars(
            select(MailDomain)
            .where(MailDomain.organization_id == organization_id)
            .order_by(MailDomain.domain)
        )
    )
    all_mailboxes = list(
        session.scalars(
            select(Mailbox)
            .where(Mailbox.organization_id == organization_id)
            .order_by(Mailbox.email_address)
        )
    )
    zoho_connections = {
        item.mailbox_id: item
        for item in session.scalars(
            select(ZohoMailConnection).where(
                ZohoMailConnection.organization_id == organization_id
            )
        )
    }
    shared_access = {
        access.mailbox_id: access.permission
        for access in session.scalars(
            select(MailboxAccess).where(MailboxAccess.user_id == user.id)
        )
    }
    is_manager = _is_manager(membership)
    is_owner = membership.role == Role.OWNER.value
    visible_mailboxes = [
        item
        for item in all_mailboxes
        if is_manager or item.id in shared_access
    ]
    mailbox_rows = []
    for item in visible_mailboxes:
        domain = next((entry for entry in domains if entry.id == item.domain_id), None)
        connection = zoho_connections.get(item.id)
        shared_with = []
        if is_manager:
            access_rows = session.execute(
                select(MailboxAccess, User)
                .join(User, User.id == MailboxAccess.user_id)
                .where(MailboxAccess.mailbox_id == item.id)
                .order_by(User.display_name)
            ).all()
            shared_with = [
                {
                    "user_id": str(access.user_id),
                    "email": shared_user.email,
                    "display_name": shared_user.display_name,
                    "permission": access.permission,
                }
                for access, shared_user in access_rows
            ]
        mailbox_rows.append(
            {
                "id": str(item.id),
                "email_address": item.email_address,
                "display_name": item.display_name,
                "domain_id": str(item.domain_id),
                "domain": domain.domain if domain else None,
                "access": (
                    "owner"
                    if is_owner
                    else "write"
                    if is_manager
                    else shared_access.get(item.id, "read")
                ),
                "shared_with": shared_with,
                "provider_connected": connection is not None,
                "provider_email": connection.account_email if connection else None,
            }
        )
    domain_rows = [
        {
            "id": str(item.id),
            "domain": item.domain,
            "status": "verified" if item.verified_at is not None else "pending_dns",
            "verification_record_name": f"_seldrune-mail.{item.domain}",
            "verification_record_value": (
                f"seldrune-mail-verification={item.verification_token}"
                if is_manager
                else None
            ),
        }
        for item in domains
    ]

    members = []
    if is_manager:
        pairs = session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(User.display_name)
        ).all()
        members = [
            {
                "user_id": str(member.user_id),
                "email": member_user.email,
                "display_name": member_user.display_name,
                "role": member.role,
            }
            for member, member_user in pairs
        ]

    any_zoho_connected = any(
        item.id in zoho_connections for item in visible_mailboxes
    )
    return {
        "organization_id": str(organization_id),
        "setup_required": not domains,
        "can_manage": is_manager,
        "domains": domain_rows,
        "mailboxes": mailbox_rows,
        "members": members,
        "delivery": {
            "ready": any_zoho_connected,
            "status": "zoho_connected" if any_zoho_connected else "mail_host_required",
            "message": (
                "Zoho Mail is connected. Verify SPF and DKIM in Domains & access before "
                "sending to external recipients."
                if any_zoho_connected
                else "Connect Zoho Mail to read and send messages here. Domain ownership "
                "verification alone does not activate mail delivery."
            ),
        },
    }


@router.get("/workspace")
def get_mail_workspace(
    organization_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    membership = _membership(session, organization_id, current_user)
    return _workspace(session, organization_id, membership, current_user)


@router.get("/mailboxes/{mailbox_id}/deliverability")
def get_mailbox_deliverability(
    organization_id: UUID,
    mailbox_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    mailbox = _mailbox(session, organization_id, mailbox_id, current_user)
    connection = _zoho_connection(session, organization_id, mailbox_id)
    return _zoho_domain_authentication(
        session=session,
        mailbox=mailbox,
        connection=connection,
    )


@router.post("/mailboxes/{mailbox_id}/deliverability/dkim")
def create_mailbox_dkim_record(
    organization_id: UUID,
    mailbox_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    mailbox = _mailbox(session, organization_id, mailbox_id, current_user)
    connection = _zoho_connection(session, organization_id, mailbox_id)
    token = _zoho_access_token(session, connection)
    domain = mailbox.email_address.rsplit("@", 1)[-1].lower()
    try:
        details = get_domain_details(
            data_center=connection.data_center,
            zoho_org_id=connection.zoho_org_id,
            domain=domain,
            access_token=token,
        )
        existing = details.get("dkimDetailList")
        entries = (
            [item for item in existing if isinstance(item, dict)]
            if isinstance(existing, list)
            else []
        )
        if not entries:
            add_dkim_details(
                data_center=connection.data_center,
                zoho_org_id=connection.zoho_org_id,
                domain=domain,
                selector="seldrune",
                access_token=token,
            )
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho could not create a DKIM selector for this domain.",
        ) from exc
    return _zoho_domain_authentication(
        session=session,
        mailbox=mailbox,
        connection=connection,
    )


@router.post("/mailboxes/{mailbox_id}/deliverability/verify")
def verify_mailbox_domain_authentication(
    organization_id: UUID,
    mailbox_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    mailbox = _mailbox(session, organization_id, mailbox_id, current_user)
    connection = _zoho_connection(session, organization_id, mailbox_id)
    token = _zoho_access_token(session, connection)
    domain = mailbox.email_address.rsplit("@", 1)[-1].lower()
    try:
        verify_spf_record(
            data_center=connection.data_center,
            zoho_org_id=connection.zoho_org_id,
            domain=domain,
            access_token=token,
        )
        details = get_domain_details(
            data_center=connection.data_center,
            zoho_org_id=connection.zoho_org_id,
            domain=domain,
            access_token=token,
        )
        dkim_details = details.get("dkimDetailList")
        entries = (
            [item for item in dkim_details if isinstance(item, dict)]
            if isinstance(dkim_details, list)
            else []
        )
        dkim = next((item for item in entries if item.get("isDefault")), None)
        if dkim is None and entries:
            dkim = entries[0]
        if dkim and dkim.get("dkimId"):
            verify_dkim_key(
                data_center=connection.data_center,
                zoho_org_id=connection.zoho_org_id,
                domain=domain,
                dkim_id=str(dkim["dkimId"]),
                access_token=token,
            )
            refreshed_details = get_domain_details(
                data_center=connection.data_center,
                zoho_org_id=connection.zoho_org_id,
                domain=domain,
                access_token=token,
            )
            refreshed_dkim = refreshed_details.get("dkimDetailList")
            refreshed_entries = (
                [item for item in refreshed_dkim if isinstance(item, dict)]
                if isinstance(refreshed_dkim, list)
                else []
            )
            refreshed_key = next(
                (
                    item
                    for item in refreshed_entries
                    if str(item.get("dkimId")) == str(dkim["dkimId"])
                ),
                None,
            )
            if refreshed_key and refreshed_key.get("isVerified"):
                enable_dkim(
                    data_center=connection.data_center,
                    zoho_org_id=connection.zoho_org_id,
                    domain=domain,
                    access_token=token,
                )
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho could not verify the SPF and DKIM DNS records.",
        ) from exc
    return _zoho_domain_authentication(
        session=session,
        mailbox=mailbox,
        connection=connection,
    )


@router.get("/mailboxes/{mailbox_id}/messages")
def list_mailbox_messages(
    organization_id: UUID,
    mailbox_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    folder: Literal["Inbox", "Sent"] = "Inbox",
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, object]:
    _mailbox(session, organization_id, mailbox_id, current_user)
    connection = _zoho_connection(session, organization_id, mailbox_id)
    token = _zoho_access_token(session, connection)
    try:
        folders = list_folders(
            data_center=connection.data_center,
            account_id=connection.account_id,
            access_token=token,
        )
        selected_folder = next(
            (
                item
                for item in folders
                if str(item.get("folderType", "")).casefold() == folder.casefold()
            ),
            None,
        )
        if selected_folder is None:
            raise HTTPException(status_code=404, detail=f"Zoho {folder} folder was not found")
        folder_id = str(selected_folder.get("folderId", ""))
        if not re.fullmatch(r"\d+", folder_id):
            raise ZohoMailError("Zoho Mail returned an invalid folder identifier")
        messages = list_messages(
            data_center=connection.data_center,
            account_id=connection.account_id,
            folder_id=folder_id,
            access_token=token,
            limit=limit,
        )
    except HTTPException:
        raise
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho Mail could not load this folder.",
        ) from exc
    rows = []
    for item in messages:
        message_id = str(item.get("messageId", ""))
        if not re.fullmatch(r"\d+", message_id):
            continue
        rows.append(
            {
                "id": message_id,
                "folder_id": folder_id,
                "subject": str(item.get("subject", "")),
                "from": str(item.get("fromAddress", "")),
                "to": str(item.get("toAddress", "")),
                "summary": message_to_plain_text(str(item.get("summary", "")))[:500],
                "received_at_ms": str(item.get("receivedTime", "")),
                "unread": str(item.get("status", "1")) == "0",
            }
        )
    return {"folder": folder, "messages": rows}


@router.get("/mailboxes/{mailbox_id}/messages/{message_id}")
def get_mailbox_message(
    organization_id: UUID,
    mailbox_id: UUID,
    message_id: str,
    current_user: CurrentUserDep,
    session: SessionDep,
    folder_id: str = Query(min_length=1, max_length=64),
) -> dict[str, str]:
    _mailbox(session, organization_id, mailbox_id, current_user)
    if not re.fullmatch(r"\d+", message_id) or not re.fullmatch(r"\d+", folder_id):
        raise HTTPException(status_code=422, detail="Invalid Zoho message reference")
    connection = _zoho_connection(session, organization_id, mailbox_id)
    token = _zoho_access_token(session, connection)
    try:
        content = get_message_content(
            data_center=connection.data_center,
            account_id=connection.account_id,
            folder_id=folder_id,
            message_id=message_id,
            access_token=token,
        )
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho Mail could not open this message.",
        ) from exc
    return {"body_text": message_to_plain_text(content)}


@router.post("/mailboxes/{mailbox_id}/send")
def send_mailbox_message(
    organization_id: UUID,
    mailbox_id: UUID,
    payload: SendMailRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    mailbox = _mailbox(session, organization_id, mailbox_id, current_user, write=True)
    connection = _zoho_connection(session, organization_id, mailbox_id)
    authentication = _zoho_domain_authentication(
        session=session,
        mailbox=mailbox,
        connection=connection,
    )
    if not authentication["ready"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Zoho reports that SPF and DKIM are not both verified. Add the displayed "
                "DNS records in your domain provider, verify them in Zoho, then retry."
            ),
        )
    draft = None
    if payload.draft_id:
        draft = session.scalar(
            select(MailDraft).where(
                MailDraft.id == payload.draft_id,
                MailDraft.mailbox_id == mailbox_id,
            )
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
    token = _zoho_access_token(session, connection)
    try:
        zoho_send_message(
            data_center=connection.data_center,
            account_id=connection.account_id,
            access_token=token,
            from_address=mailbox.email_address,
            to=[str(item) for item in payload.to],
            cc=[str(item) for item in payload.cc],
            bcc=[str(item) for item in payload.bcc],
            subject=payload.subject,
            content=payload.body,
        )
    except ZohoMailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Zoho Mail could not send this message.",
        ) from exc
    if draft is not None:
        session.delete(draft)
        session.commit()
    return {"sent": True, "provider": "zoho"}


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def initialize_mail_workspace(
    organization_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)

    domain = session.scalar(
        select(MailDomain).where(
            MailDomain.organization_id == organization_id,
            MailDomain.domain == "seldrune.in",
        )
    )
    if domain is None:
        domain = MailDomain(
            organization_id=organization_id,
            domain="seldrune.in",
            verification_token=secrets.token_hex(24),
            created_by_user_id=current_user.id,
        )
        session.add(domain)
        session.flush()

    for local_part, display_name in _DEFAULT_MAILBOXES:
        address = f"{local_part}@{domain.domain}"
        existing = session.scalar(
            select(Mailbox.id).where(
                Mailbox.organization_id == organization_id,
                Mailbox.email_address == address,
            )
        )
        if existing is None:
            session.add(
                Mailbox(
                    organization_id=organization_id,
                    domain_id=domain.id,
                    email_address=address,
                    display_name=display_name,
                    created_by_user_id=current_user.id,
                )
            )
    session.commit()
    session.refresh(domain)
    return _workspace(session, organization_id, membership, current_user)


@router.post("/domains", status_code=status.HTTP_201_CREATED)
def add_mail_domain(
    organization_id: UUID,
    payload: DomainCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    if session.scalar(
        select(MailDomain.id).where(
            MailDomain.organization_id == organization_id,
            MailDomain.domain == payload.domain,
        )
    ):
        raise HTTPException(status_code=409, detail="That domain is already connected")
    domain = MailDomain(
        organization_id=organization_id,
        domain=payload.domain,
        verification_token=secrets.token_hex(24),
        created_by_user_id=current_user.id,
    )
    session.add(domain)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="That domain is already connected") from exc
    session.refresh(domain)
    return {
        "id": str(domain.id),
        "domain": domain.domain,
        "status": "pending_dns",
        "verification_record_name": f"_seldrune-mail.{domain.domain}",
        "verification_record_value": f"seldrune-mail-verification={domain.verification_token}",
    }


@router.post("/domains/{domain_id}/verify")
def verify_mail_domain(
    organization_id: UUID,
    domain_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    domain = session.scalar(
        select(MailDomain).where(
            MailDomain.id == domain_id,
            MailDomain.organization_id == organization_id,
        )
    )
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    record_name = f"_seldrune-mail.{domain.domain}"
    try:
        response = httpx.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": record_name, "type": "TXT"},
            headers={"accept": "application/dns-json"},
            timeout=5.0,
        )
        response.raise_for_status()
        answers = response.json().get("Answer", [])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="The DNS check is temporarily unavailable. Try again shortly.",
        ) from exc

    expected = f"seldrune-mail-verification={domain.verification_token}"
    if not any(
        str(item.get("data", "")).strip().strip('"') == expected
        for item in answers
        if isinstance(item, dict)
    ):
        raise HTTPException(status_code=409, detail="Verification TXT record was not found")

    domain.verified_at = datetime.now(UTC)
    session.commit()
    return {"domain": domain.domain, "status": "verified"}


@router.post("/mailboxes", status_code=status.HTTP_201_CREATED)
def create_mailbox(
    organization_id: UUID,
    payload: MailboxCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    domain = session.scalar(
        select(MailDomain).where(
            MailDomain.id == payload.domain_id,
            MailDomain.organization_id == organization_id,
        )
    )
    if domain is None:
        raise HTTPException(status_code=404, detail="Mail domain not found")
    address = f"{payload.local_part}@{domain.domain}"
    mailbox = Mailbox(
        organization_id=organization_id,
        domain_id=domain.id,
        email_address=address,
        display_name=payload.display_name,
        created_by_user_id=current_user.id,
    )
    session.add(mailbox)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Mailbox address already exists") from exc
    session.refresh(mailbox)
    return {
        "id": str(mailbox.id),
        "email_address": mailbox.email_address,
        "display_name": mailbox.display_name,
    }


@router.post("/mailboxes/{mailbox_id}/access", status_code=status.HTTP_201_CREATED)
def grant_mailbox_access(
    organization_id: UUID,
    mailbox_id: UUID,
    payload: AccessGrant,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, str]:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    mailbox = session.scalar(
        select(Mailbox).where(
            Mailbox.id == mailbox_id,
            Mailbox.organization_id == organization_id,
        )
    )
    if mailbox is None:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    user = session.scalar(select(User).where(User.email == str(payload.email).lower()))
    target_membership = (
        session.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user.id,
            )
        )
        if user is not None
        else None
    )
    if user is None or target_membership is None:
        raise HTTPException(status_code=404, detail="User must be an organization member first")
    if target_membership.role == Role.OWNER.value:
        raise HTTPException(
            status_code=409,
            detail="Organization owners already have access to every mailbox",
        )
    access = session.get(MailboxAccess, (mailbox.id, user.id))
    if access is None:
        access = MailboxAccess(
            mailbox_id=mailbox.id,
            user_id=user.id,
            permission=payload.permission,
            granted_by_user_id=current_user.id,
        )
        session.add(access)
    else:
        access.permission = payload.permission
        access.granted_by_user_id = current_user.id
    session.commit()
    return {
        "mailbox_id": str(mailbox.id),
        "user_id": str(user.id),
        "email": user.email,
        "permission": access.permission,
    }


@router.delete(
    "/mailboxes/{mailbox_id}/access/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_mailbox_access(
    organization_id: UUID,
    mailbox_id: UUID,
    user_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    membership = _membership(session, organization_id, current_user)
    _require_manager(membership)
    mailbox = session.scalar(
        select(Mailbox).where(
            Mailbox.id == mailbox_id,
            Mailbox.organization_id == organization_id,
        )
    )
    if mailbox is None:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    access = session.get(MailboxAccess, (mailbox_id, user_id))
    if access is None:
        raise HTTPException(status_code=404, detail="Mailbox share not found")
    session.delete(access)
    session.commit()


@router.get("/mailboxes/{mailbox_id}/drafts")
def list_drafts(
    organization_id: UUID,
    mailbox_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[dict[str, object]]:
    _mailbox(session, organization_id, mailbox_id, current_user)
    drafts = session.scalars(
        select(MailDraft)
        .where(MailDraft.mailbox_id == mailbox_id)
        .order_by(MailDraft.updated_at.desc())
    )
    return [_draft_response(item) for item in drafts]


@router.post("/mailboxes/{mailbox_id}/drafts", status_code=status.HTTP_201_CREATED)
def save_draft(
    organization_id: UUID,
    mailbox_id: UUID,
    payload: DraftCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    _mailbox(session, organization_id, mailbox_id, current_user, write=True)
    content = {
        "to": [str(item) for item in payload.to],
        "cc": [str(item) for item in payload.cc],
        "bcc": [str(item) for item in payload.bcc],
        "subject": payload.subject,
        "body": payload.body,
    }
    draft = MailDraft(
        mailbox_id=mailbox_id,
        created_by_user_id=current_user.id,
        encrypted_payload=encrypt_secret_value(json.dumps(content, ensure_ascii=False)),
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return _draft_response(draft)


@router.put("/mailboxes/{mailbox_id}/drafts/{draft_id}")
def update_draft(
    organization_id: UUID,
    mailbox_id: UUID,
    draft_id: UUID,
    payload: DraftCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict[str, object]:
    _mailbox(session, organization_id, mailbox_id, current_user, write=True)
    draft = session.scalar(
        select(MailDraft).where(
            MailDraft.id == draft_id,
            MailDraft.mailbox_id == mailbox_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    content = {
        "to": [str(item) for item in payload.to],
        "cc": [str(item) for item in payload.cc],
        "bcc": [str(item) for item in payload.bcc],
        "subject": payload.subject,
        "body": payload.body,
    }
    draft.encrypted_payload = encrypt_secret_value(
        json.dumps(content, ensure_ascii=False)
    )
    session.commit()
    session.refresh(draft)
    return _draft_response(draft)


@router.delete(
    "/mailboxes/{mailbox_id}/drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_draft(
    organization_id: UUID,
    mailbox_id: UUID,
    draft_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    _mailbox(session, organization_id, mailbox_id, current_user, write=True)
    draft = session.scalar(
        select(MailDraft).where(
            MailDraft.id == draft_id,
            MailDraft.mailbox_id == mailbox_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    session.delete(draft)
    session.commit()


def _draft_response(draft: MailDraft) -> dict[str, object]:
    try:
        content = json.loads(decrypt_secret_value(draft.encrypted_payload))
    except (SecretVaultError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=500, detail="Draft could not be opened") from exc
    return {
        "id": str(draft.id),
        "to": content.get("to", []),
        "cc": content.get("cc", []),
        "bcc": content.get("bcc", []),
        "subject": content.get("subject", ""),
        "body": content.get("body", ""),
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }
