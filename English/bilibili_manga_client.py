#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bilibili Manga command-line client: QR login, downloads, and optional coin/ticket purchases.

Install:
    py -m pip install requests qrcode[pil] pycryptodome

Usage:
    py bilibili_manga_client_english.py
    py bilibili_manga_client_english.py --comic-id 12345
    py bilibili_manga_client_english.py --url "https://manga.bilibili.com/detail/mc12345"
    py bilibili_manga_client_english.py --qr-login --url "https://manga.bilibili.com/detail/mc12345"
    py bilibili_manga_client_english.py --no-login --comic-id 12345

There is no built-in search. Enter the comic ID or provide a URL containing mc<ID>.
QR login is optional; accessing purchased chapters requires an account with the
appropriate chapter access.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import getpass
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

try:
    import qrcode
except ImportError:  # QR support is optional until the user selects that login method.
    qrcode = None

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None


MANGA_HOST = "https://manga.bilibili.com"
PASSPORT_HOST = "https://passport.bilibili.com"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
FINGER_URL = "https://api.bilibili.com/x/frontend/finger/spi"
COOKIE_FILE = Path(__file__).with_name("bilibili_cookies.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# Twirp detail/index/token calls use the Android app identity.
BILI_APP_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G9730) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
APP_QUERY = {
    "appkey": "cc8617fd6961e070",
    "mobi_app": "android_comic",
    "version": "4.13.0",
    "build": "36413002",
    "channel": "bilicomic",
    "platform": "android",
    "device": "android",
}

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": MANGA_HOST,
    "Content-Type": "application/json;charset=UTF-8",
}


class BilibiliError(RuntimeError):
    pass


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.headers["Referer"] = MANGA_HOST + "/"
    return session


def load_cookie_jar(session: requests.Session, path: Path = COOKIE_FILE) -> bool:
    if not path.exists():
        return False
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
        for item in cookies:
            session.cookies.set_cookie(requests.cookies.create_cookie(
                name=item["name"], value=item["value"],
                domain=item.get("domain") or ".bilibili.com",
                path=item.get("path") or "/",
                secure=bool(item.get("secure", False)),
                expires=item.get("expires"),
                rest=item.get("rest") or {},
            ))
        return True
    except Exception as exc:
        print(f"[!] Could not read the saved session: {exc}")
        return False


def save_cookie_jar(session: requests.Session, path: Path = COOKIE_FILE) -> None:
    items = []
    for cookie in session.cookies:
        items.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": cookie.secure,
            "expires": cookie.expires,
            "rest": cookie._rest,
        })
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def cookie_value(session: requests.Session, name: str) -> str | None:
    for cookie in session.cookies:
        if cookie.name == name:
            return cookie.value
    return None


def validate_login(session: requests.Session) -> tuple[bool, str]:
    try:
        response = session.get(NAV_URL, headers={"Referer": "https://www.bilibili.com/"}, timeout=20)
        response.raise_for_status()
        data = response.json().get("data") or {}
        if data.get("isLogin"):
            return True, str(data.get("uname") or data.get("mid") or "account")
        return False, "Bilibili does not recognize this session as logged in"
    except Exception as exc:
        return False, f"Could not verify the session: {exc}"


def show_qr(url: str) -> None:
    if qrcode is None:
        raise BilibiliError("The qrcode package is missing. Install it with: py -m pip install qrcode[pil]")
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    qr_path = Path(__file__).with_name("bilibili_login_qr.png")
    image.save(qr_path)
    print(f"QR code saved to: {qr_path}")
    try:
        image.show()
    except Exception:
        pass
    print("Scan the QR code with the official Bilibili app.")


def qr_login(session: requests.Session) -> bool:
    """Perform QR login; requests.Session stores the Set-Cookie values returned by polling."""
    response = session.get(
        f"{PASSPORT_HOST}/x/passport-login/web/qrcode/generate",
        headers={"Referer": "https://www.bilibili.com/"}, timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "0" or not payload.get("data"):
        raise BilibiliError(f"Could not generate the QR code: {payload}")

    qr_data = payload["data"]
    qr_url = qr_data.get("url")
    qr_key = qr_data.get("qrcode_key")
    if not qr_url or not qr_key:
        raise BilibiliError(f"Incomplete QR response: {qr_data}")
    show_qr(qr_url)

    print("Waiting for confirmation (the QR code usually expires after 180 seconds)...")
    start = time.monotonic()
    last_status = None
    while time.monotonic() - start < 180:
        poll = session.get(
            f"{PASSPORT_HOST}/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qr_key},
            headers={"Referer": "https://www.bilibili.com/"}, timeout=20,
        )
        poll.raise_for_status()
        result = poll.json()
        if str(result.get("code")) != "0":
            raise BilibiliError(f"Error while checking the QR code: {result}")
        data = result.get("data") or {}
        status = int(data.get("code", -1))

        if status != last_status:
            if status == 86101:
                print("  QR code has not been scanned yet...")
            elif status == 86090:
                print("  QR code scanned; waiting for confirmation on your phone...")
            elif status == 86038:
                print("  The QR code has expired. Start the login process again.")
                return False
            elif status == 0:
                # The endpoint sets cookies through Set-Cookie. Some
                # Some responses also include values in data.url; use them as
                # a fallback. Never print that URL because it contains credentials.
                session_url = data.get("url") or ""
                query = parse_qs(urlsplit(session_url).query)
                for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                    values = query.get(name)
                    if values and values[0]:
                        session.cookies.set(name, values[0], domain=".bilibili.com", path="/")
                if not cookie_value(session, "SESSDATA"):
                    print("  Bilibili confirmed the QR login, but no SESSDATA cookie was received.")
                    return False
                ok, user = validate_login(session)
                if not ok:
                    print(f"  A cookie was received, but session validation failed: {user}")
                    return False
                save_cookie_jar(session)
                print(f"[OK] Login successful: {user}")
                print(f"[OK] Session saved to {COOKIE_FILE}")
                print("     This file contains account credentials. Do not share it.")
                return True
            last_status = status
        time.sleep(2)

    print("[!] Timed out while waiting for the QR code.")
    return False


def maybe_login(session: requests.Session, args: argparse.Namespace) -> bool:
    if args.no_login:
        print("[i] Anonymous mode requested; login will be skipped.")
        return False

    loaded = load_cookie_jar(session)
    if loaded:
        if args.qr_login:
            pass
        else:
            answer = input("A saved session was found. Reuse it? [Y/n]: ").strip().lower()
            if answer not in ("n", "no"):
                ok, user = validate_login(session)
                if ok:
                    print(f"[OK] Reused saved session: {user}")
                    return True
                print(f"[!] Saved session is not valid: {user}")

    if args.qr_login:
        return qr_login(session)
    answer = input("Would you like to log in by scanning a QR code? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        return qr_login(session)
    print("[i] Continuing without logging in.")
    return False


def obtain_buvid(session: requests.Session) -> bool:
    """Retrieve buvid3/buvid4; Bilibili uses them as anti-abuse fingerprints."""
    try:
        response = session.get(
            FINGER_URL,
            headers={"User-Agent": BILI_APP_UA, "Referer": MANGA_HOST + "/"},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        if data.get("b_3"):
            session.cookies.set("buvid3", data["b_3"], domain=".bilibili.com", path="/")
        if data.get("b_4"):
            session.cookies.set("buvid4", data["b_4"], domain=".bilibili.com", path="/")
        has_buvid3 = bool(cookie_value(session, "buvid3"))
        has_buvid4 = bool(cookie_value(session, "buvid4"))
        print(f"[i] Bilibili fingerprint: buvid3={'OK' if has_buvid3 else 'unavailable'}, "
              f"buvid4={'OK' if has_buvid4 else 'unavailable'}.")
        return has_buvid3
    except Exception as exc:
        print(f"[i] Could not obtain buvid (continuing anyway): {exc}")
        return False


def extract_comic_id(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    match = re.search(r"mc(\d+)", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    raise ValueError("Could not find a comic ID. Enter the numeric ID or a URL containing mc<ID>.")


def api_post(
    session: requests.Session,
    method: str,
    payload: dict[str, Any],
    comic_id: int,
    episode_id: int | None = None,
    service: str = "comic.v1.Comic",
    query_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call Twirp using the APP parameters required by the current implementation.

    Important: ComicDetail/GetImageIndex/ImageToken do not use the web query
    device=pc&platform=web. They require APP_QUERY + ts and camelCase JSON
    field names (comicId / epId).
    """
    url = f"{MANGA_HOST}/twirp/{service}/{method}"
    params = {"ts": int(time.time()), **APP_QUERY, **(query_overrides or {})}
    headers = {
        "User-Agent": BILI_APP_UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        # Remove Origin/Referer inherited from the web session; this is the APP profile.
        "Origin": None,
        "Referer": None,
    }
    result = None
    for attempt in range(2):
        try:
            response = session.post(
                url, params=params, json=payload, headers=headers, timeout=35
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise BilibiliError(f"Request failed for {method}: {exc}") from exc
        except ValueError as exc:
            raise BilibiliError(f"{method} did not return valid JSON: {response.text[:500]}") from exc

        if str(result.get("code")) == "99" and attempt == 0:
            print("[i] Bilibili returned code 99; refreshing buvid and retrying...")
            obtain_buvid(session)
            # Regenerate ts so the previous timestamp is not reused.
            params["ts"] = int(time.time())
            continue
        break

    code = result.get("code") if result else None
    if str(code) != "0":
        message = (result or {}).get("msg") or (result or {}).get("message") or "sin mensaje"
        if str(code) == "99":
            raise BilibiliError(
                f"{method}: code=99; {message}. The APP request with the buvid fingerprint was rejected. "
                "This is not a chapter purchase error."
            )
        raise BilibiliError(f"{method}: code={code}; {message}")
    data = result.get("data")
    if data is None:
        raise BilibiliError(f"{method}: the response does not contain data")
    return data


def get_comic_detail(session: requests.Session, comic_id: int) -> dict[str, Any]:
    # APP schema: the current API expects comicId in camelCase.
    detail = api_post(session, "ComicDetail", {"comicId": comic_id}, comic_id)
    if not isinstance(detail, dict):
        raise BilibiliError("ComicDetail returned an unexpected data structure")
    return detail



def get_account_mid(session: requests.Session) -> int:
    """Retrieve the account MID from the QR cookie or the nav API."""
    value = cookie_value(session, "DedeUserID")
    if value and str(value).isdigit():
        return int(value)
    response = session.get(
        NAV_URL, headers={"Referer": "https://www.bilibili.com/"}, timeout=20
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    if not data.get("isLogin") or not data.get("mid"):
        raise BilibiliError("Could not retrieve the account MID; check whether QR login is still active.")
    return int(data["mid"])


def get_user_wallet(session: requests.Session) -> dict[str, Any]:
    """Retrieve the Bilibili Manga wallet balance (coins, tickets, and cards)."""
    url = f"{MANGA_HOST}/twirp/user.v1.User/GetWallet"
    try:
        response = session.post(
            url,
            params={"platform": "web"},
            json={},
            headers={
                "User-Agent": USER_AGENT,
                "Referer": MANGA_HOST + "/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise BilibiliError(f"Could not retrieve the Manga wallet balance: {exc}") from exc
    except ValueError as exc:
        raise BilibiliError("GetWallet did not return valid JSON") from exc

    if str(payload.get("code")) != "0":
        message = payload.get("msg") or payload.get("message") or "sin mensaje"
        raise BilibiliError(f"GetWallet: code={payload.get('code')}; {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BilibiliError("GetWallet did not return a valid data object")
    return data


def show_account_wallet(session: requests.Session, heading: str = "ACCOUNT BALANCE") -> dict[str, Any] | None:
    """Display wallet balances. A wallet lookup failure does not stop the client."""
    if not cookie_value(session, "SESSDATA"):
        return None
    print("\n" + "=" * 58)
    print(f"{heading:^58}")
    print("=" * 58)
    try:
        wallet = get_user_wallet(session)
        fields = [
            ("Manga coins (漫币)", "remain_gold"),
            ("Reading tickets (漫读券)", "remain_coupon"),
            ("General coupons (通用券)", "remain_silver"),
            ("Free-reading cards (限免卡)", "remain_item"),
            ("Discount coupons/cards", "remain_discount"),
        ]
        for label, key in fields:
            if key in wallet and wallet[key] is not None:
                try:
                    amount = int(wallet[key])
                except (TypeError, ValueError):
                    amount = wallet[key]
                print(f"  {label:<39} {amount}")
        if "unusable_gold" in wallet and wallet["unusable_gold"] is not None:
            print(f"  {'Unavailable coins':<39} {wallet['unusable_gold']}")
        if "point" in wallet and wallet["point"] is not None:
            print(f"  {'Points':<39} {wallet['point']}")
        print("=" * 58 + "\n")
        return wallet
    except (BilibiliError, requests.RequestException) as exc:
        print(f"[!] Could not retrieve the wallet balance: {exc}")
        print("    Your session is still active; you can continue.\n")
        return None


def get_user_coupons(session: requests.Session) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Retrieve active tickets. QR login (SESSDATA) is required."""
    data = api_post(
        session,
        "GetCoupons",
        {"pageNum": 1, "pageSize": 100, "notExpired": True, "tabType": 1, "type": 0},
        comic_id=0,
        service="user.v1.User",
    )
    if not isinstance(data, dict):
        raise BilibiliError("GetCoupons returned an unexpected data structure")
    coupons = data.get("user_coupons") or []
    info = data.get("coupon_info") or {}
    if not isinstance(coupons, list):
        coupons = []
    valid = []
    for coupon in coupons:
        if not isinstance(coupon, dict):
            continue
        try:
            remaining = int(coupon.get("remain_amount", 0) or 0)
            coupon_id = int(coupon.get("ID", 0) or 0)
        except (TypeError, ValueError):
            continue
        if coupon_id > 0 and remaining > 0:
            valid.append(coupon)
    # Prefer tickets with the soonest expiration date; if the values cannot be
    # compared, keep the order returned by Bilibili.
    valid.sort(key=lambda c: str(c.get("expire_time") or "9999"))
    return valid, info


def coupon_applies_to_comic(coupon: dict[str, Any], comic_id: int) -> bool:
    """Tickets with limits can only be used if their restrictions include this comic."""
    limits = coupon.get("limits") or []
    if not limits:
        return True
    for item in limits:
        if str(item) == str(comic_id):
            return True
        if isinstance(item, dict):
            for key in ("comic_id", "comicId", "id"):
                if str(item.get(key, "")) == str(comic_id):
                    return True
    return False


def get_locked_selected(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ep for ep in episodes if ep.get("is_locked") and not ep.get("is_in_free")]


PURCHASE_APP_QUERY = {
    "version": "7.6.0",
    "build": "36706000",
    "machine": "samsung SM-G9880",
    "is_teenager": "0",
    "no_recommend": "0",
    "network": "wifi",
}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _flag_is_true(value: Any) -> bool:
    """Interpret boolean flags returned by Bilibili."""
    return value is True or value == 1 or str(value).strip().lower() in ("true", "1")


def get_episode_buy_info(
    session: requests.Session, comic_id: int, ep_id: int
) -> dict[str, Any]:
    """Retrieve purchase details only: price, tickets, and discounts.

    IMPORTANT: this function never determines whether a chapter is unlocked.
    Access status continues to come exclusively from ComicDetail.
    """
    data = api_post(
        session,
        "GetEpisodeBuyInfo",
        {"epId": int(ep_id)},
        comic_id,
        int(ep_id),
        query_overrides=PURCHASE_APP_QUERY,
    )
    if not isinstance(data, dict):
        raise BilibiliError(f"GetEpisodeBuyInfo returned invalid information for ep_id={ep_id}.")
    return data


def get_episode_from_comic_detail(
    session: requests.Session, comic_id: int, ep_id: int
) -> dict[str, Any] | None:
    """Query ComicDetail again and return the chapter without using BuyInfo."""
    detail = get_comic_detail(session, comic_id)
    for item in detail.get("ep_list") or []:
        if str(item.get("id")) == str(ep_id):
            return item
    return None


def analyze_episode_price(info: dict[str, Any]) -> dict[str, Any]:
    """Calculate the current price and the card discount advertised by Bilibili."""
    current_price = _as_int(info.get("pay_gold"), _as_int(info.get("ep_discount_gold")))
    original_price = _as_int(info.get("ep_original_gold"), current_price)
    if original_price <= 0:
        original_price = current_price
    regular_saving = max(0, original_price - current_price)

    free_card = info.get("free_gold_card") or {}
    prime = (info.get("prime_info") or {}).get("single") or {}
    card_discount = _as_int(
        prime.get("free_gold_card_prime_gold"),
        _as_int(free_card.get("prime_gold_count")),
    )
    card_id = free_card.get("card_id")
    show_card = _flag_is_true(prime.get("show_free_gold_card"))
    usable_flag = _flag_is_true(free_card.get("is_usable"))

    # In the real capture provided by the user, Bilibili returned
    # is_usable=false, but show_free_gold_card=true and a discount greater than 0;
    # the interface still offered the discount. This combination is recognized.
    card_offered = card_discount > 0 and bool(card_id) and (usable_flag or show_card)
    net_price = max(0, current_price - card_discount) if card_offered else current_price
    return {
        "current_price": current_price,
        "original_price": original_price,
        "regular_saving": regular_saving,
        "card_discount": card_discount if card_offered else 0,
        "card_id": str(card_id) if card_id else None,
        "card_offered": card_offered,
        "card_reason": str(free_card.get("reason") or "").strip(),
        "net_price": net_price,
    }


def print_episode_quote(ep: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    pricing = analyze_episode_price(info)
    order = ep.get("ord", "?")
    title = ep.get("title") or ep.get("short_title") or f"Chapter {order}"
    print(f"  - [{order}] {title}: {pricing['current_price']} coins")
    if pricing["regular_saving"]:
        print(f"      Original price: {pricing['original_price']} | discount already applied: -{pricing['regular_saving']}")
    if pricing["card_offered"]:
        print(
            f"      Coin discount card offered: -{pricing['card_discount']} | "
            f"estimated amount due: {pricing['net_price']} coins"
        )
    else:
        print("      No additional discount confirmed; Bilibili's current price will be used.")
    return pricing


def buy_episode_request(
    session: requests.Session,
    comic_id: int,
    episode: dict[str, Any],
    buy_info: dict[str, Any],
    method: str,
    *,
    coupon_id: int | None = None,
) -> dict[str, Any]:
    """Submit BuyEpisode using the latest quote without reading is_locked."""
    ep_id = int(episode["id"])
    order = episode.get("ord", "?")
    title = episode.get("title") or episode.get("short_title") or f"Chapter {order}"
    pricing = analyze_episode_price(buy_info)

    if method == "ticket":
        if not coupon_id:
            raise BilibiliError("No valid couponId is available for this chapter.")
        payload = {
            "epId": ep_id,
            "buyMethod": 2,
            "autoPayGoldStatus": 2,
            "isPresale": 0,
            "couponIds": [int(coupon_id)],
        }
    elif method == "coin":
        if pricing["current_price"] <= 0:
            raise BilibiliError(f"No valid pay_gold value is available for {title}; a coin purchase will not be submitted.")
        payload = {
            "epId": ep_id,
            "buyMethod": 3,
            "couponId": 0,
            "autoPayGoldStatus": 2,
            "payAmount": pricing["current_price"],
            "isPresale": 0,
        }
        if pricing["card_offered"]:
            payload["freeGoldCardId"] = pricing["card_id"]
            payload["freeGoldAmount"] = pricing["card_discount"]
    else:
        raise ValueError("Unknown purchase method")

    query = dict(PURCHASE_APP_QUERY)
    buvid = cookie_value(session, "buvid3")
    if buvid:
        query["buvid"] = buvid
    result = api_post(
        session, "BuyEpisode", payload, comic_id, ep_id,
        query_overrides=query,
    )
    print(f"    [OK] Purchase accepted by Bilibili: [{order}] {title}.")
    if method == "coin":
        if pricing["regular_saving"]:
            print(f"         Price discount already included by Bilibili: -{pricing['regular_saving']} coins.")
        if pricing["card_offered"]:
            print(f"         Card discount submitted: -{pricing['card_discount']} coins.")
            print(f"         Estimated cost: {pricing['net_price']} coins.")
        else:
            print("         No additional discount was submitted; the current price was used.")
    if isinstance(result, dict) and result.get("auto_use_item"):
        print(f"         Item applied by Bilibili: {result.get('auto_use_item')}")
    return pricing


def purchase_selected_chapters(
    session: requests.Session,
    comic_id: int,
    selected: list[dict[str, Any]],
) -> list[int]:
    """Purchase only locked chapters according to the original ComicDetail logic.

    GetEpisodeBuyInfo is used for prices/discounts only. Before each purchase,
    ComicDetail is queried again to avoid repurchasing chapters already unlocked.
    """
    # This condition is preserved exactly as it appears in the
    # working file provided by the user.
    locked_candidates = [
        ep for ep in selected if ep.get("is_locked") and not ep.get("is_in_free")
    ]
    if not locked_candidates:
        print("\n[i] The selected chapters do not need to be purchased.")
        return []
    if not cookie_value(session, "SESSDATA"):
        print("\n[!] QR login is required to make purchases. No purchase request will be sent.")
        return []

    print("\nChecking current prices and discounts (without changing ComicDetail access status)...")
    locked: list[dict[str, Any]] = []
    buy_infos: dict[int, dict[str, Any]] = {}
    pricing_preview: dict[int, dict[str, Any]] = {}
    for ep in locked_candidates:
        ep_id = int(ep["id"])
        try:
            info = get_episode_buy_info(session, comic_id, ep_id)
        except BilibiliError as exc:
            print(f"  [!] Could not retrieve the price for [{ep.get('ord', '?')}]: {exc}")
            print("      This chapter will be excluded; it will not be purchased with incomplete information.")
            continue
        # Deliberately do NOT read or modify info['is_locked'].
        locked.append(ep)
        buy_infos[ep_id] = info
        pricing_preview[ep_id] = print_episode_quote(ep, info)

    if not locked:
        print("\n[i] There are no chapters with a valid purchase quote.")
        return []

    print("\nPurchase method:")
    print("  1. Reading ticket (漫读券) — buyMethod=2")
    print("  2. Manga coins (漫币) — buyMethod=3")
    print("  0. Do not buy; continue without unlocking")
    choice = input("Choose [0]: ").strip() or "0"
    if choice == "0":
        return []
    if choice not in ("1", "2"):
        print("[!] Invalid option; nothing was purchased.")
        return []

    coupon_allocations: list[int] = []
    if choice == "1":
        coupons, _ = get_user_coupons(session)
        usable_coupons = [c for c in coupons if coupon_applies_to_comic(c, comic_id)]
        restricted_coupons = [c for c in coupons if c not in usable_coupons]
        total_tickets = sum(_as_int(c.get("remain_amount")) for c in usable_coupons)
        print(f"\nReading tickets compatible with this comic: {total_tickets}")
        for coupon in usable_coupons:
            print(
                f"  ID {coupon.get('ID')} | remaining: {coupon.get('remain_amount')} | "
                f"expires: {coupon.get('expire_time') or 'not provided'}"
            )
        if restricted_coupons:
            print(f"[i] Skipped {len(restricted_coupons)} ticket(s) with unverified restrictions.")
        if total_tickets <= 0:
            print("[!] No tickets are available. Nothing was purchased.")
            return []
        count = min(len(locked), total_tickets)
        if count < len(locked):
            print(f"[i] There are {len(locked)} locked chapters but only {total_tickets} tickets; at most {count} will be purchased.")
        answer = input(f"Use {count} ticket(s) for the first {count} locked chapters? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            return []
        for coupon in usable_coupons:
            coupon_id = _as_int(coupon.get("ID"))
            remaining = _as_int(coupon.get("remain_amount"))
            if coupon_id > 0:
                coupon_allocations.extend([coupon_id] * remaining)
        locked = locked[:count]
        coupon_allocations = coupon_allocations[:count]
        total_cost_label = f"{count} ticket(s)"
    else:
        total_original = sum(pricing_preview[int(ep["id"])]["original_price"] for ep in locked)
        total_current = sum(pricing_preview[int(ep["id"])]["current_price"] for ep in locked)
        total_card = sum(pricing_preview[int(ep["id"])]["card_discount"] for ep in locked)
        total_estimated = sum(pricing_preview[int(ep["id"])]["net_price"] for ep in locked)
        print("\nCoin purchase summary:")
        print(f"  Original price: {total_original} coins")
        if total_original > total_current:
            print(f"  Discount already applied by Bilibili: -{total_original - total_current} coins")
        if total_card:
            print(f"  Additional card discount: -{total_card} coins")
        print(f"  Estimated total: {total_estimated} coins")
        total_cost_label = f"aproximadamente {total_estimated} coins"

    print(f"\nSummary: {len(locked)} chapter(s); {total_cost_label}.")
    confirm = input("Type BUY to proceed with the purchases: ").strip()
    if confirm != "BUY":
        print("[i] Purchase cancelled; no BuyEpisode request was sent.")
        return []

    purchased: list[int] = []
    for index, ep in enumerate(locked):
        ep_id = int(ep["id"])
        order = ep.get("ord", "?")
        title = ep.get("title") or ep.get("short_title") or f"Chapter {order}"
        try:
            # Access status comes only from ComicDetail, as in the working script.
            fresh_ep = get_episode_from_comic_detail(session, comic_id, ep_id)
            if fresh_ep is None or "is_locked" not in fresh_ep or fresh_ep.get("is_locked") is None:
                print(f"  [SKIPPED] [{order}] {title}: ComicDetail did not confirm the access status; this chapter will not be purchased.")
                continue
            if not fresh_ep.get("is_locked") or fresh_ep.get("is_in_free"):
                print(f"  [SKIPPED] [{order}] {title}: ComicDetail already shows this chapter as unlocked/free.")
                continue

            # Refresh the quote for price/card details only. Never use its is_locked field.
            fresh_info = get_episode_buy_info(session, comic_id, ep_id)
            fresh_pricing = analyze_episode_price(fresh_info)
            old_pricing = pricing_preview.get(ep_id, {})
            if choice == "2" and fresh_pricing["net_price"] != old_pricing.get("net_price"):
                print(
                    f"  [!] The amount changed for [{order}] {title}: "
                    f"previously {old_pricing.get('net_price')} and now {fresh_pricing['net_price']} coins."
                )
                accept = input("      Type YES to accept the new amount: ").strip().upper()
                if accept != "YES":
                    print("      Purchase stopped; nothing was spent on this chapter.")
                    break

            if choice == "1":
                buy_episode_request(
                    session, comic_id, fresh_ep, fresh_info, "ticket",
                    coupon_id=coupon_allocations[index],
                )
            else:
                buy_episode_request(session, comic_id, fresh_ep, fresh_info, "coin")
            purchased.append(ep_id)
            time.sleep(0.8)
        except BilibiliError as exc:
            print(f"    [ERROR] Could not purchase ep_id={ep_id}: {exc}")
            print("    Purchasing is stopped to avoid further charges until this error is reviewed.")
            break

    if purchased:
        print(f"\n[OK] Bilibili accepted {len(purchased)} purchase(s). Refreshing chapter access status...")
    return purchased

def episode_sort_key(ep: dict[str, Any]) -> tuple[float, int]:
    try:
        order = float(ep.get("ord", 0))
    except (TypeError, ValueError):
        order = 0.0
    try:
        episode_id = int(ep.get("id", 0))
    except (TypeError, ValueError):
        episode_id = 0
    return order, episode_id


def clean_name(value: str, max_length: int = 100) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return (value or "untitled")[:max_length]


def display_chapters(detail: dict[str, Any]) -> list[dict[str, Any]]:
    episodes = detail.get("ep_list") or []
    if not isinstance(episodes, list) or not episodes:
        raise BilibiliError("ComicDetail did not return ep_list, or the series has no visible chapters")
    episodes = sorted(episodes, key=episode_sort_key)
    print("\n" + "=" * 78)
    print(f"MANGA: {detail.get('title') or '(untitled)'} | ID: {detail.get('id')}")
    print(f"Chapters received: {len(episodes)}")
    print("=" * 78)
    for index, ep in enumerate(episodes, 1):
        order = ep.get("ord", "?")
        title = ep.get("title") or ep.get("short_title") or f"Chapter {order}"
        locked = " [LOCKED]" if ep.get("is_locked") else " [UNLOCKED]"
        count = ep.get("image_count", "?")
        price = ep.get("pay_gold", 0) or 0
        price_label = f"{price} Manga coins" if price else "price not provided"
        print(f"{index:>4}. [{order}] {title} | {count} pages | {price_label} | ep_id={ep.get('id')}{locked}")
    return episodes


def choose_chapters(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print("\nSelect chapters: A = all; example: 1,3,5-8")
    raw = input("Selection: ").strip().lower()
    if raw in ("a", "all", "*"):
        return episodes
    if not raw:
        return []

    selected: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left.strip()), int(right.strip())
            if start > end:
                start, end = end, start
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))

    invalid = [number for number in selected if number < 1 or number > len(episodes)]
    if invalid:
        raise ValueError(f"Chapter numbers out of range: {', '.join(map(str, sorted(invalid)))}")
    return [episodes[number - 1] for number in sorted(selected)]


def get_image_index(session: requests.Session, comic_id: int, episode_id: int) -> list[str]:
    data = api_post(session, "GetImageIndex", {"epId": episode_id}, comic_id, episode_id)
    images = data.get("images") or []
    paths = [item.get("path") for item in images if isinstance(item, dict) and item.get("path")]
    if not paths:
        raise BilibiliError(f"GetImageIndex returned no pages for ep_id={episode_id}")
    return paths


def append_token(url: str, token: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["token"] = [token]
    new_query = urlencode(query, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def get_image_tokens(
    session: requests.Session,
    comic_id: int,
    episode_id: int,
    paths: list[str],
) -> list[dict[str, Any]]:
    # The urls field is a JSON string containing an array, not a direct JSON array.
    urls_json = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    data = api_post(session, "ImageToken", {"urls": urls_json}, comic_id, episode_id)
    if not isinstance(data, list) or len(data) != len(paths):
        received = len(data) if isinstance(data, list) else type(data).__name__
        raise BilibiliError(f"ImageToken returned {received} results for {len(paths)} paths")

    output = []
    for item in data:
        if not isinstance(item, dict):
            raise BilibiliError("ImageToken returned an unexpected item")
        complete_url = item.get("complete_url")
        if not complete_url:
            base_url = item.get("url")
            token = item.get("token")
            if not base_url or token is None:
                raise BilibiliError("ImageToken returned neither complete_url nor url/token")
            complete_url = append_token(base_url, str(token))
        output.append({"url": complete_url, "hit_encrypt": item.get("hit_encrpyt", False)})
    return output


def is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        or data.startswith((b"GIF87a", b"GIF89a"))
    )


def image_extension(data: bytes, url: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    ext = Path(urlsplit(url).path).suffix.lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".img"


def decrypt_cpx_image(data: bytes, image_url: str) -> bytes:
    """Decrypt the CPX format used by manga images when required."""
    cpx_values = parse_qs(urlsplit(image_url).query).get("cpx")
    if not cpx_values:
        return data
    if is_image(data):
        return data
    if AES is None:
        raise BilibiliError("This image uses cpx; install pycryptodome: py -m pip install pycryptodome")
    if len(data) < 5 or data[0] != 1:
        raise BilibiliError("CPX image: unexpected header or marker")

    data_length = int.from_bytes(data[1:5], "big")
    end = 5 + data_length
    if data_length <= 0 or end > len(data):
        raise BilibiliError("CPX image: encrypted length is out of range")

    try:
        cpx_raw = base64.b64decode(cpx_values[0], validate=False)
    except Exception as exc:
        raise BilibiliError(f"Could not decode the cpx parameter: {exc}") from exc
    iv = cpx_raw[60:76]
    key = data[end:]
    content = data[5:end]
    if len(iv) != 16 or len(key) not in (16, 24, 32):
        raise BilibiliError(f"CPX image: invalid IV or AES key (IV={len(iv)}, key={len(key)})")

    encrypted_head = content[:20496] if len(content) > 20496 else content
    if not encrypted_head or len(encrypted_head) % 16:
        raise BilibiliError("CPX image: AES data length is not block-aligned")
    decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted_head)

    # The first encrypted block segment may contain PKCS#7 padding at the end.
    # Remove it only when the padding sequence is valid.
    if decrypted:
        pad = decrypted[-1]
        if 1 <= pad <= 16 and decrypted.endswith(bytes([pad]) * pad):
            decrypted = decrypted[:-pad]
    restored = decrypted + content[20496:]
    if not is_image(restored):
        raise BilibiliError("CPX output does not appear to be a valid image; possibly corrupted data will not be saved")
    return restored


def download_one_image(url: str, destination_base: Path, page_number: int) -> tuple[int, Path, int]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": MANGA_HOST + "/",
        "Origin": MANGA_HOST,
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, headers=headers, timeout=(15, 60))
            response.raise_for_status()
            raw = response.content
            image_data = decrypt_cpx_image(raw, url)
            if not is_image(image_data):
                raise BilibiliError(f"The response for page {page_number} is not an image")
            extension = image_extension(image_data, url)
            destination = destination_base.with_name(f"{page_number:04d}{extension}")
            destination.write_bytes(image_data)
            return page_number, destination, len(image_data)
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 1.5)
    raise BilibiliError(f"Page {page_number}: {last_error}")


def download_episode(
    session: requests.Session,
    comic_id: int,
    comic_title: str,
    episode: dict[str, Any],
    output_root: Path,
    workers: int = 4,
    chapter_number: int | None = None,
) -> None:
    episode_id = int(episode["id"])
    order = episode.get("ord", "?")
    title = episode.get("title") or episode.get("short_title") or f"Chapter {order}"
    # Bilibili's web reader numbers chapters starting at 00. Use the
    # position in the sorted list (not ep.ord) to reproduce that format.
    if chapter_number is None:
        try:
            chapter_number = max(0, int(float(order)) - 1)
        except (TypeError, ValueError):
            chapter_number = 0
    chapter_name = f"{chapter_number:02d}-{title}"
    folder = output_root / clean_name(comic_title) / clean_name(chapter_name)
    folder.mkdir(parents=True, exist_ok=True)

    existing = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".img")]
    if existing:
        answer = input(f"\nThere are already {len(existing)} files in '{folder}'. Skip this chapter? [Y/n]: ").strip().lower()
        if answer not in ("n", "no"):
            print("  [i] Chapter skipped.")
            return

    print(f"\n[+] {chapter_name} (ep_id={episode_id})")
    paths = get_image_index(session, comic_id, episode_id)
    print(f"    Image index: {len(paths)} pages")
    tokens = get_image_tokens(session, comic_id, episode_id, paths)
    print(f"    Tokens: {len(tokens)} URLs ready")

    failures: list[str] = []
    completed = 0
    total_bytes = 0
    base = folder / "page"
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        future_map = {
            pool.submit(download_one_image, item["url"], base, index): index
            for index, item in enumerate(tokens, 1)
        }
        for future in concurrent.futures.as_completed(future_map):
            page = future_map[future]
            try:
                page_number, saved_path, byte_count = future.result()
                completed += 1
                total_bytes += byte_count
                # Update the same line instead of printing a new line for every page.
                sys.stdout.write(
                    f"\r    [{completed}/{len(tokens)}] Page {page_number:04d} -> {saved_path.name}"
                )
                sys.stdout.flush()
            except Exception as exc:
                failures.append(str(exc))
                # Errors are printed on their own line so they remain visible.
                print(f"\n    [ERROR] {exc}")

    # Close the progress line before printing the chapter summary.
    if completed or failures:
        print()

    if failures:
        print(f"[!] Chapter incomplete: {len(failures)} page(s) failed. Folder: {folder}")
    else:
        print(f"[OK] Chapter downloaded: {completed} pages, {total_bytes / 1024 / 1024:.2f} MiB")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bilibili Manga Python client (anonymous or QR login)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--comic-id", help="Numeric comic ID")
    source.add_argument("--url", help="Comic webpage URL, e.g. .../detail/mc12345")
    parser.add_argument("--qr-login", action="store_true", help="Log in using a QR code")
    parser.add_argument("--no-login", action="store_true", help="Do not load a saved session or prompt for QR login")
    parser.add_argument("--output", default="Bilibili_Downloads", help="Output directory")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent downloads (1-8)")
    args = parser.parse_args()

    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    if args.qr_login and args.no_login:
        parser.error("--qr-login and --no-login cannot be used together")

    print("=" * 72)
    print("        BILIBILI MANGA CLIENT - ComicDetail status + discounts")
    print("=" * 72)
    session = make_session()

    try:
        logged_in = maybe_login(session, args)
    except (BilibiliError, requests.RequestException) as exc:
        print(f"[AUTHENTICATION ERROR] {exc}")
        return 1
    obtain_buvid(session)
    if logged_in:
        show_account_wallet(session)

    raw_id = args.comic_id or args.url or input("Enter the manga URL or numeric ID: ").strip()
    try:
        comic_id = extract_comic_id(raw_id)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 2

    print(f"\n[+] Loading manga ID {comic_id} ({'logged in' if logged_in else 'anonymous'})...")
    try:
        detail = get_comic_detail(session, comic_id)
        episodes = display_chapters(detail)
        # Bilibili display numbering: first chapter = 00, second = 01...
        chapter_numbers_by_id = {
            int(ep["id"]): index
            for index, ep in enumerate(episodes)
            if ep.get("id") is not None
        }
        selected = choose_chapters(episodes)
        if not selected:
            print("No chapters were selected. Exiting.")
            return 0

        # Optional purchase of locked chapters (requires QR login).
        bought_ids = purchase_selected_chapters(session, comic_id, selected)
        if bought_ids:
            show_account_wallet(session, "WALLET BALANCE AFTER PURCHASES")
            try:
                refreshed = get_comic_detail(session, comic_id)
                fresh_by_id = {int(ep.get("id")): ep for ep in (refreshed.get("ep_list") or []) if ep.get("id") is not None}
                selected = [fresh_by_id.get(int(ep["id"]), ep) for ep in selected]
            except Exception as exc:
                print(f"[i] Could not refresh the chapter list after the purchase: {exc}")

        title = detail.get("title") or f"manga_{comic_id}"
        output_root = Path(args.output).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        downloadable = [ep for ep in selected if not ep.get("is_locked")]
        still_locked = [ep for ep in selected if ep.get("is_locked")]
        if still_locked:
            print(f"\n[i] {len(still_locked)} chapter(s) are still locked or could not be purchased; they will be skipped.")
        print(f"\nDownloading {len(downloadable)} unlocked chapter(s) to: {output_root}")
        for episode in downloadable:
            try:
                download_episode(
                    session, comic_id, title, episode, output_root, args.workers,
                    chapter_number=chapter_numbers_by_id.get(int(episode["id"])),
                )
            except BilibiliError as exc:
                print(f"[ERROR] {exc}")
        print("\nProcess completed.")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return 130
    except BilibiliError as exc:
        print(f"\n[ERROR] {exc}")
        if not logged_in:
            print("Note: the ComicDetail error occurs before chapter access is checked; logging in does not guarantee that it will be resolved.")
        return 1
    except requests.RequestException as exc:
        print(f"\n[NETWORK ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
