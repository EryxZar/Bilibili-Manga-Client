#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente de consola Bilibili Manga: login QR, descargas y compra opcional con monedas/tickets.

Instalacion:
    py -m pip install requests qrcode[pil] pycryptodome

Uso:
    py bilibili_manga_client.py
    py bilibili_manga_client.py --comic-id 12345
    py bilibili_manga_client.py --url "https://manga.bilibili.com/detail/mc12345"
    py bilibili_manga_client.py --qr-login --url "https://manga.bilibili.com/detail/mc12345"
    py bilibili_manga_client.py --no-login --comic-id 12345

No incluye buscador. El identificador se obtiene de la URL mc<ID> o se introduce
como numero. El login QR es opcional; para capitulos comprados se necesita una
sesion con permisos sobre esos capitulos.
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
except ImportError:  # QR opcional hasta que el usuario seleccione ese modo
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
# Las llamadas Twirp de detalle/índice/token usan la identidad de la app Android.
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
        print(f"[!] No pude leer la sesion guardada: {exc}")
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
            return True, str(data.get("uname") or data.get("mid") or "cuenta")
        return False, "Bilibili no reconoce la sesion como iniciada"
    except Exception as exc:
        return False, f"No se pudo verificar la sesion: {exc}"


def show_qr(url: str) -> None:
    if qrcode is None:
        raise BilibiliError("Falta qrcode. Instala dependencias con: py -m pip install qrcode[pil]")
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    qr_path = Path(__file__).with_name("bilibili_login_qr.png")
    image.save(qr_path)
    print(f"QR guardado en: {qr_path}")
    try:
        image.show()
    except Exception:
        pass
    print("Escanea el QR con la aplicacion oficial de Bilibili.")


def qr_login(session: requests.Session) -> bool:
    """Login web QR; requests.Session conserva los Set-Cookie que emite el poll."""
    response = session.get(
        f"{PASSPORT_HOST}/x/passport-login/web/qrcode/generate",
        headers={"Referer": "https://www.bilibili.com/"}, timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "0" or not payload.get("data"):
        raise BilibiliError(f"No se pudo generar el QR: {payload}")

    qr_data = payload["data"]
    qr_url = qr_data.get("url")
    qr_key = qr_data.get("qrcode_key")
    if not qr_url or not qr_key:
        raise BilibiliError(f"Respuesta QR incompleta: {qr_data}")
    show_qr(qr_url)

    print("Esperando confirmacion (el QR suele caducar a los 180 segundos)...")
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
            raise BilibiliError(f"Error consultando el QR: {result}")
        data = result.get("data") or {}
        status = int(data.get("code", -1))

        if status != last_status:
            if status == 86101:
                print("  QR aun no escaneado...")
            elif status == 86090:
                print("  QR escaneado; esperando que confirmes en el telefono...")
            elif status == 86038:
                print("  El QR ha caducado. Vuelve a iniciar el login.")
                return False
            elif status == 0:
                # El endpoint establece las cookies por Set-Cookie. Algunas
                # respuestas tambien incluyen valores en data.url; se usa como
                # respaldo, nunca se imprime ese URL porque contiene credenciales.
                session_url = data.get("url") or ""
                query = parse_qs(urlsplit(session_url).query)
                for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                    values = query.get(name)
                    if values and values[0]:
                        session.cookies.set(name, values[0], domain=".bilibili.com", path="/")
                if not cookie_value(session, "SESSDATA"):
                    print("  Bilibili confirmo el QR, pero no recibimos SESSDATA.")
                    return False
                ok, user = validate_login(session)
                if not ok:
                    print(f"  Se recibio cookie, pero la validacion fallo: {user}")
                    return False
                save_cookie_jar(session)
                print(f"[OK] Login correcto: {user}")
                print(f"[OK] Sesion guardada en {COOKIE_FILE}")
                print("     Ese archivo contiene credenciales. No lo compartas.")
                return True
            last_status = status
        time.sleep(2)

    print("[!] Tiempo agotado esperando el QR.")
    return False


def maybe_login(session: requests.Session, args: argparse.Namespace) -> bool:
    if args.no_login:
        print("[i] Modo anonimo solicitado; no se iniciara sesion.")
        return False

    loaded = load_cookie_jar(session)
    if loaded:
        if args.qr_login:
            pass
        else:
            answer = input("Se encontro una sesion guardada. ¿Reutilizarla? [S/n]: ").strip().lower()
            if answer not in ("n", "no"):
                ok, user = validate_login(session)
                if ok:
                    print(f"[OK] Sesion reutilizada: {user}")
                    return True
                print(f"[!] Sesion guardada no valida: {user}")

    if args.qr_login:
        return qr_login(session)
    answer = input("¿Deseas iniciar sesion escaneando un QR? [s/N]: ").strip().lower()
    if answer in ("s", "si", "sí", "y", "yes"):
        return qr_login(session)
    print("[i] Continuando sin iniciar sesion.")
    return False


def obtain_buvid(session: requests.Session) -> bool:
    """Obtiene buvid3/buvid4; Bilibili los usa como huella antiabuso."""
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
        print(f"[i] Huella Bilibili: buvid3={'OK' if has_buvid3 else 'no disponible'}, "
              f"buvid4={'OK' if has_buvid4 else 'no disponible'}.")
        return has_buvid3
    except Exception as exc:
        print(f"[i] No se pudo obtener buvid (continuare igualmente): {exc}")
        return False


def extract_comic_id(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    match = re.search(r"mc(\d+)", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    raise ValueError("No encontre un ID. Usa el numero o una URL que contenga mc<ID>.")


def api_post(
    session: requests.Session,
    method: str,
    payload: dict[str, Any],
    comic_id: int,
    episode_id: int | None = None,
    service: str = "comic.v1.Comic",
    query_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Llama Twirp con los parámetros APP que usa la implementación actual.

    Importante: ComicDetail/GetImageIndex/ImageToken no usan el query web
    device=pc&platform=web. Requieren APP_QUERY + ts y los nombres camelCase
    en el JSON (comicId / epId).
    """
    url = f"{MANGA_HOST}/twirp/{service}/{method}"
    params = {"ts": int(time.time()), **APP_QUERY, **(query_overrides or {})}
    headers = {
        "User-Agent": BILI_APP_UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        # Quitar Origin/Referer heredados de la sesión web: este es el perfil APP.
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
            raise BilibiliError(f"Fallo la peticion {method}: {exc}") from exc
        except ValueError as exc:
            raise BilibiliError(f"{method} no devolvio JSON valido: {response.text[:500]}") from exc

        if str(result.get("code")) == "99" and attempt == 0:
            print("[i] Bilibili devolvio code 99; renovando buvid y reintentando...")
            obtain_buvid(session)
            # ts se regenera para evitar reutilizar la marca temporal anterior.
            params["ts"] = int(time.time())
            continue
        break

    code = result.get("code") if result else None
    if str(code) != "0":
        message = (result or {}).get("msg") or (result or {}).get("message") or "sin mensaje"
        if str(code) == "99":
            raise BilibiliError(
                f"{method}: code=99; {message}. La llamada APP con huella buvid no fue aceptada. "
                "No es un error de compra de capítulos."
            )
        raise BilibiliError(f"{method}: code={code}; {message}")
    data = result.get("data")
    if data is None:
        raise BilibiliError(f"{method}: la respuesta no contiene data")
    return data


def get_comic_detail(session: requests.Session, comic_id: int) -> dict[str, Any]:
    # Esquema APP: la API actual espera comicId en camelCase.
    detail = api_post(session, "ComicDetail", {"comicId": comic_id}, comic_id)
    if not isinstance(detail, dict):
        raise BilibiliError("ComicDetail devolvio una estructura inesperada")
    return detail



def get_account_mid(session: requests.Session) -> int:
    """Obtiene el MID desde la cookie del QR o desde la API nav."""
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
        raise BilibiliError("No pude obtener el MID; verifica que el login QR siga activo.")
    return int(data["mid"])


def get_user_wallet(session: requests.Session) -> dict[str, Any]:
    """Consulta el saldo de Bilibili Manga (monedas, tickets y tarjetas)."""
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
        raise BilibiliError(f"No se pudo consultar el saldo de Manga: {exc}") from exc
    except ValueError as exc:
        raise BilibiliError("GetWallet no devolvio JSON valido") from exc

    if str(payload.get("code")) != "0":
        message = payload.get("msg") or payload.get("message") or "sin mensaje"
        raise BilibiliError(f"GetWallet: code={payload.get('code')}; {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BilibiliError("GetWallet no devolvio un objeto data valido")
    return data


def show_account_wallet(session: requests.Session, heading: str = "SALDO DE TU CUENTA") -> dict[str, Any] | None:
    """Muestra las cantidades del monedero. Un fallo de saldo no interrumpe el cliente."""
    if not cookie_value(session, "SESSDATA"):
        return None
    print("\n" + "=" * 58)
    print(f"{heading:^58}")
    print("=" * 58)
    try:
        wallet = get_user_wallet(session)
        fields = [
            ("Monedas (漫币)", "remain_gold"),
            ("Tickets de lectura (漫读券)", "remain_coupon"),
            ("Cupones generales (通用券)", "remain_silver"),
            ("Tarjetas de lectura gratuita (限免卡)", "remain_item"),
            ("Cupones/tarjetas de descuento", "remain_discount"),
        ]
        for label, key in fields:
            if key in wallet and wallet[key] is not None:
                try:
                    amount = int(wallet[key])
                except (TypeError, ValueError):
                    amount = wallet[key]
                print(f"  {label:<39} {amount}")
        if "unusable_gold" in wallet and wallet["unusable_gold"] is not None:
            print(f"  {'Monedas no disponibles':<39} {wallet['unusable_gold']}")
        if "point" in wallet and wallet["point"] is not None:
            print(f"  {'Puntos':<39} {wallet['point']}")
        print("=" * 58 + "\n")
        return wallet
    except (BilibiliError, requests.RequestException) as exc:
        print(f"[!] No pude consultar el saldo: {exc}")
        print("    El inicio de sesion sigue activo; puedes continuar.\n")
        return None


def get_user_coupons(session: requests.Session) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Consulta los tickets activos. Requiere la sesión QR (SESSDATA)."""
    data = api_post(
        session,
        "GetCoupons",
        {"pageNum": 1, "pageSize": 100, "notExpired": True, "tabType": 1, "type": 0},
        comic_id=0,
        service="user.v1.User",
    )
    if not isinstance(data, dict):
        raise BilibiliError("GetCoupons devolvio una estructura inesperada")
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
    # Preferir los tickets con vencimiento más próximo; si el formato no es
    # comparable, mantener el orden entregado por Bilibili.
    valid.sort(key=lambda c: str(c.get("expire_time") or "9999"))
    return valid, info


def coupon_applies_to_comic(coupon: dict[str, Any], comic_id: int) -> bool:
    """Los tickets con limits se usan solo si la limitación incluye este manga."""
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
    """Interpreta banderas booleanas devueltas por Bilibili."""
    return value is True or value == 1 or str(value).strip().lower() in ("true", "1")


def get_episode_buy_info(
    session: requests.Session, comic_id: int, ep_id: int
) -> dict[str, Any]:
    """Consulta solo los datos de compra: precio, tickets y descuentos.

    IMPORTANTE: esta función nunca determina si el capítulo está desbloqueado.
    El estado de acceso sigue procediendo exclusivamente de ComicDetail.
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
        raise BilibiliError(f"GetEpisodeBuyInfo no devolvió información válida para ep_id={ep_id}.")
    return data


def get_episode_from_comic_detail(
    session: requests.Session, comic_id: int, ep_id: int
) -> dict[str, Any] | None:
    """Reconsulta ComicDetail y devuelve el capítulo, sin consultar BuyInfo."""
    detail = get_comic_detail(session, comic_id)
    for item in detail.get("ep_list") or []:
        if str(item.get("id")) == str(ep_id):
            return item
    return None


def analyze_episode_price(info: dict[str, Any]) -> dict[str, Any]:
    """Calcula precio vigente y descuento de tarjeta anunciado por Bilibili."""
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

    # En la captura real aportada por el usuario, Bilibili devolvió
    # is_usable=false, pero show_free_gold_card=true y un descuento > 0;
    # la interfaz sí ofrecía el descuento. Se reconoce esa combinación.
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
    title = ep.get("title") or ep.get("short_title") or f"Capítulo {order}"
    print(f"  - [{order}] {title}: {pricing['current_price']} monedas")
    if pricing["regular_saving"]:
        print(f"      Precio original: {pricing['original_price']} | descuento ya reflejado: -{pricing['regular_saving']}")
    if pricing["card_offered"]:
        print(
            f"      Tarjeta de monedas ofrecida: -{pricing['card_discount']} | "
            f"estimado a pagar: {pricing['net_price']} monedas"
        )
    else:
        print("      Sin descuento adicional confirmado; se usará el precio de Bilibili.")
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
    """Envía BuyEpisode usando la cotización más reciente, sin leer is_locked."""
    ep_id = int(episode["id"])
    order = episode.get("ord", "?")
    title = episode.get("title") or episode.get("short_title") or f"Capítulo {order}"
    pricing = analyze_episode_price(buy_info)

    if method == "ticket":
        if not coupon_id:
            raise BilibiliError("No hay un couponId válido para este capítulo.")
        payload = {
            "epId": ep_id,
            "buyMethod": 2,
            "autoPayGoldStatus": 2,
            "isPresale": 0,
            "couponIds": [int(coupon_id)],
        }
    elif method == "coin":
        if pricing["current_price"] <= 0:
            raise BilibiliError(f"No hay pay_gold válido para {title}; no enviaré una compra con monedas.")
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
        raise ValueError("Método de compra desconocido")

    query = dict(PURCHASE_APP_QUERY)
    buvid = cookie_value(session, "buvid3")
    if buvid:
        query["buvid"] = buvid
    result = api_post(
        session, "BuyEpisode", payload, comic_id, ep_id,
        query_overrides=query,
    )
    print(f"    [OK] Compra aceptada por Bilibili: [{order}] {title}.")
    if method == "coin":
        if pricing["regular_saving"]:
            print(f"         Descuento de precio incluido por Bilibili: -{pricing['regular_saving']} monedas.")
        if pricing["card_offered"]:
            print(f"         Descuento de tarjeta enviado: -{pricing['card_discount']} monedas.")
            print(f"         Coste estimado: {pricing['net_price']} monedas.")
        else:
            print("         No se envió descuento adicional; se utilizó el precio vigente.")
    if isinstance(result, dict) and result.get("auto_use_item"):
        print(f"         Elemento aplicado por Bilibili: {result.get('auto_use_item')}")
    return pricing


def purchase_selected_chapters(
    session: requests.Session,
    comic_id: int,
    selected: list[dict[str, Any]],
) -> list[int]:
    """Compra solo capítulos bloqueados según la lógica original de ComicDetail.

    GetEpisodeBuyInfo se usa solo para precios/descuentos. Antes de cada compra
    se vuelve a consultar ComicDetail para evitar recomprar capítulos ya abiertos.
    """
    # Esta condición se conserva exactamente como en el archivo funcional
    # proporcionado por el usuario.
    locked_candidates = [
        ep for ep in selected if ep.get("is_locked") and not ep.get("is_in_free")
    ]
    if not locked_candidates:
        print("\n[i] Los capítulos seleccionados no requieren compra.")
        return []
    if not cookie_value(session, "SESSDATA"):
        print("\n[!] Para comprar hace falta iniciar sesión mediante QR. No se enviará ninguna compra.")
        return []

    print("\nConsultando precio y descuentos actuales (sin alterar el estado de ComicDetail)...")
    locked: list[dict[str, Any]] = []
    buy_infos: dict[int, dict[str, Any]] = {}
    pricing_preview: dict[int, dict[str, Any]] = {}
    for ep in locked_candidates:
        ep_id = int(ep["id"])
        try:
            info = get_episode_buy_info(session, comic_id, ep_id)
        except BilibiliError as exc:
            print(f"  [!] No se pudo consultar el precio de [{ep.get('ord', '?')}]: {exc}")
            print("      Se excluye este capítulo; no se comprará con información incompleta.")
            continue
        # Deliberadamente NO se consulta ni se modifica info['is_locked'].
        locked.append(ep)
        buy_infos[ep_id] = info
        pricing_preview[ep_id] = print_episode_quote(ep, info)

    if not locked:
        print("\n[i] No hay capítulos con cotización válida para comprar.")
        return []

    print("\nMétodo de compra:")
    print("  1. Ticket de lectura (漫读券) — buyMethod=2")
    print("  2. Monedas (漫币) — buyMethod=3")
    print("  0. No comprar; continuar sin desbloquear")
    choice = input("Elige [0]: ").strip() or "0"
    if choice == "0":
        return []
    if choice not in ("1", "2"):
        print("[!] Opción no válida; no se compró nada.")
        return []

    coupon_allocations: list[int] = []
    if choice == "1":
        coupons, _ = get_user_coupons(session)
        usable_coupons = [c for c in coupons if coupon_applies_to_comic(c, comic_id)]
        restricted_coupons = [c for c in coupons if c not in usable_coupons]
        total_tickets = sum(_as_int(c.get("remain_amount")) for c in usable_coupons)
        print(f"\nTickets de lectura compatibles con este manga: {total_tickets}")
        for coupon in usable_coupons:
            print(
                f"  ID {coupon.get('ID')} | quedan {coupon.get('remain_amount')} | "
                f"vence: {coupon.get('expire_time') or 'sin dato'}"
            )
        if restricted_coupons:
            print(f"[i] Se omitieron {len(restricted_coupons)} ticket(s) con restricciones no verificadas.")
        if total_tickets <= 0:
            print("[!] No hay tickets disponibles. No se compró nada.")
            return []
        count = min(len(locked), total_tickets)
        if count < len(locked):
            print(f"[i] Hay {len(locked)} capítulos bloqueados, pero solo {total_tickets} tickets; se comprarán como máximo {count}.")
        answer = input(f"¿Usar {count} ticket(s) para los primeros {count} capítulos bloqueados? [s/N]: ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
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
        print("\nResumen de monedas:")
        print(f"  Precio original: {total_original} monedas")
        if total_original > total_current:
            print(f"  Descuento ya incluido por Bilibili: -{total_original - total_current} monedas")
        if total_card:
            print(f"  Descuento adicional de tarjetas: -{total_card} monedas")
        print(f"  Total estimado: {total_estimated} monedas")
        total_cost_label = f"aproximadamente {total_estimated} monedas"

    print(f"\nResumen: {len(locked)} capítulo(s); {total_cost_label}.")
    confirm = input("Escribe COMPRAR para ejecutar las compras: ").strip()
    if confirm != "COMPRAR":
        print("[i] Compra cancelada; no se envió ninguna petición BuyEpisode.")
        return []

    purchased: list[int] = []
    for index, ep in enumerate(locked):
        ep_id = int(ep["id"])
        order = ep.get("ord", "?")
        title = ep.get("title") or ep.get("short_title") or f"Capítulo {order}"
        try:
            # Estado de acceso: solo ComicDetail, igual que en el script funcional.
            fresh_ep = get_episode_from_comic_detail(session, comic_id, ep_id)
            if fresh_ep is None or "is_locked" not in fresh_ep or fresh_ep.get("is_locked") is None:
                print(f"  [OMITIDO] [{order}] {title}: ComicDetail no confirmó el estado; no se compra.")
                continue
            if not fresh_ep.get("is_locked") or fresh_ep.get("is_in_free"):
                print(f"  [OMITIDO] [{order}] {title}: ComicDetail ya lo muestra desbloqueado/gratuito.")
                continue

            # Cotización nueva solo para coste/tarjeta. Nunca se usa su is_locked.
            fresh_info = get_episode_buy_info(session, comic_id, ep_id)
            fresh_pricing = analyze_episode_price(fresh_info)
            old_pricing = pricing_preview.get(ep_id, {})
            if choice == "2" and fresh_pricing["net_price"] != old_pricing.get("net_price"):
                print(
                    f"  [!] Cambió el importe de [{order}] {title}: "
                    f"antes {old_pricing.get('net_price')} y ahora {fresh_pricing['net_price']} monedas."
                )
                accept = input("      Escribe SI para aceptar el nuevo importe: ").strip().upper()
                if accept != "SI":
                    print("      Compra detenida; no se gastó en este capítulo.")
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
            print(f"    [ERROR] No se pudo comprar ep_id={ep_id}: {exc}")
            print("    Se detiene la compra para evitar gastos adicionales sin revisar el error.")
            break

    if purchased:
        print(f"\n[OK] Bilibili aceptó {len(purchased)} compra(s). Actualizando estado de capítulos...")
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
    return (value or "sin_titulo")[:max_length]


def display_chapters(detail: dict[str, Any]) -> list[dict[str, Any]]:
    episodes = detail.get("ep_list") or []
    if not isinstance(episodes, list) or not episodes:
        raise BilibiliError("ComicDetail no devolvio ep_list o la serie no tiene capitulos visibles")
    episodes = sorted(episodes, key=episode_sort_key)
    print("\n" + "=" * 78)
    print(f"MANGA: {detail.get('title') or '(sin titulo)'} | ID: {detail.get('id')}")
    print(f"Capitulos recibidos: {len(episodes)}")
    print("=" * 78)
    for index, ep in enumerate(episodes, 1):
        order = ep.get("ord", "?")
        title = ep.get("title") or ep.get("short_title") or f"Capitulo {order}"
        locked = " [BLOQUEADO]" if ep.get("is_locked") else " [DISPONIBLE/COMPRADO]"
        count = ep.get("image_count", "?")
        price = ep.get("pay_gold", 0) or 0
        price_label = f"{price} 漫币" if price else "sin precio indicado"
        print(f"{index:>4}. [{order}] {title} | {count} pag. | {price_label} | ep_id={ep.get('id')}{locked}")
    return episodes


def choose_chapters(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print("\nSelecciona capitulos: A = todos; ejemplo: 1,3,5-8")
    raw = input("Seleccion: ").strip().lower()
    if raw in ("a", "all", "todos", "*"):
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
        raise ValueError(f"Indices fuera de rango: {', '.join(map(str, sorted(invalid)))}")
    return [episodes[number - 1] for number in sorted(selected)]


def get_image_index(session: requests.Session, comic_id: int, episode_id: int) -> list[str]:
    data = api_post(session, "GetImageIndex", {"epId": episode_id}, comic_id, episode_id)
    images = data.get("images") or []
    paths = [item.get("path") for item in images if isinstance(item, dict) and item.get("path")]
    if not paths:
        raise BilibiliError(f"GetImageIndex no devolvio paginas para ep_id={episode_id}")
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
    # El campo urls es una cadena JSON que contiene un array, no un array JSON directo.
    urls_json = json.dumps(paths, ensure_ascii=False, separators=(",", ":"))
    data = api_post(session, "ImageToken", {"urls": urls_json}, comic_id, episode_id)
    if not isinstance(data, list) or len(data) != len(paths):
        received = len(data) if isinstance(data, list) else type(data).__name__
        raise BilibiliError(f"ImageToken devolvio {received} resultados para {len(paths)} rutas")

    output = []
    for item in data:
        if not isinstance(item, dict):
            raise BilibiliError("ImageToken devolvio un elemento inesperado")
        complete_url = item.get("complete_url")
        if not complete_url:
            base_url = item.get("url")
            token = item.get("token")
            if not base_url or token is None:
                raise BilibiliError("ImageToken no devolvio complete_url ni url/token")
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
    """Descifra el formato CPX usado por las imagenes manga que lo requieran."""
    cpx_values = parse_qs(urlsplit(image_url).query).get("cpx")
    if not cpx_values:
        return data
    if is_image(data):
        return data
    if AES is None:
        raise BilibiliError("La imagen usa cpx; instala pycryptodome: py -m pip install pycryptodome")
    if len(data) < 5 or data[0] != 1:
        raise BilibiliError("Imagen CPX: cabecera o marcador inesperado")

    data_length = int.from_bytes(data[1:5], "big")
    end = 5 + data_length
    if data_length <= 0 or end > len(data):
        raise BilibiliError("Imagen CPX: longitud cifrada fuera de rango")

    try:
        cpx_raw = base64.b64decode(cpx_values[0], validate=False)
    except Exception as exc:
        raise BilibiliError(f"No se pudo decodificar el parametro cpx: {exc}") from exc
    iv = cpx_raw[60:76]
    key = data[end:]
    content = data[5:end]
    if len(iv) != 16 or len(key) not in (16, 24, 32):
        raise BilibiliError(f"Imagen CPX: IV o clave AES no valida (IV={len(iv)}, key={len(key)})")

    encrypted_head = content[:20496] if len(content) > 20496 else content
    if not encrypted_head or len(encrypted_head) % 16:
        raise BilibiliError("Imagen CPX: longitud AES no alineada a bloques")
    decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted_head)

    # El primer bloque cifrado lleva padding PKCS#7 al final del segmento
    # cifrado. Se retira solo si la secuencia de padding es consistente.
    if decrypted:
        pad = decrypted[-1]
        if 1 <= pad <= 16 and decrypted.endswith(bytes([pad]) * pad):
            decrypted = decrypted[:-pad]
    restored = decrypted + content[20496:]
    if not is_image(restored):
        raise BilibiliError("La salida CPX no parece una imagen valida; no guardare datos posiblemente corruptos")
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
                raise BilibiliError(f"La respuesta de la pagina {page_number} no es una imagen")
            extension = image_extension(image_data, url)
            destination = destination_base.with_name(f"{page_number:04d}{extension}")
            destination.write_bytes(image_data)
            return page_number, destination, len(image_data)
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 1.5)
    raise BilibiliError(f"Pagina {page_number}: {last_error}")


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
    title = episode.get("title") or episode.get("short_title") or f"Capitulo {order}"
    # El lector web de Bilibili numera visualmente desde 00. Usamos la
    # posición de la lista ordenada (no ep.ord) para reproducir ese formato.
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
        answer = input(f"\nYa hay {len(existing)} archivos en '{folder}'. ¿Omitir este capitulo? [S/n]: ").strip().lower()
        if answer not in ("n", "no"):
            print("  [i] Capitulo omitido.")
            return

    print(f"\n[+] {chapter_name} (ep_id={episode_id})")
    paths = get_image_index(session, comic_id, episode_id)
    print(f"    Indice: {len(paths)} paginas")
    tokens = get_image_tokens(session, comic_id, episode_id, paths)
    print(f"    Tokens: {len(tokens)} URLs listas")

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
                # Actualiza la misma linea en lugar de imprimir una por pagina.
                sys.stdout.write(
                    f"\r    [{completed}/{len(tokens)}] Pagina {page_number:04d} -> {saved_path.name}"
                )
                sys.stdout.flush()
            except Exception as exc:
                failures.append(str(exc))
                # Los errores se muestran en una linea propia para que no se pierdan.
                print(f"\n    [ERROR] {exc}")

    # Cierra la linea de progreso antes del resumen del capitulo.
    if completed or failures:
        print()

    if failures:
        print(f"[!] Capitulo incompleto: {len(failures)} pagina(s) fallaron. Carpeta: {folder}")
    else:
        print(f"[OK] Capitulo descargado: {completed} paginas, {total_bytes / 1024 / 1024:.2f} MiB")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cliente Python de Bilibili Manga (anonimo o login QR)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--comic-id", help="ID numerico de la serie")
    source.add_argument("--url", help="URL web de la serie, por ejemplo .../detail/mc12345")
    parser.add_argument("--qr-login", action="store_true", help="Iniciar sesion usando QR")
    parser.add_argument("--no-login", action="store_true", help="No cargar sesion ni mostrar pregunta de QR")
    parser.add_argument("--output", default="Descargas_Bilibili", help="Directorio de salida")
    parser.add_argument("--workers", type=int, default=4, help="Descargas simultaneas (1-8)")
    args = parser.parse_args()

    if args.workers < 1 or args.workers > 8:
        parser.error("--workers debe estar entre 1 y 8")
    if args.qr_login and args.no_login:
        parser.error("No puedes usar --qr-login y --no-login a la vez")

    print("=" * 72)
    print("        BILIBILI MANGA CLIENT - base ComicDetail + descuentos")
    print("=" * 72)
    session = make_session()

    try:
        logged_in = maybe_login(session, args)
    except (BilibiliError, requests.RequestException) as exc:
        print(f"[ERROR de autenticacion] {exc}")
        return 1
    obtain_buvid(session)
    if logged_in:
        show_account_wallet(session)

    raw_id = args.comic_id or args.url or input("Pega la URL web del manga o escribe su ID: ").strip()
    try:
        comic_id = extract_comic_id(raw_id)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 2

    print(f"\n[+] Consultando manga ID {comic_id} ({'con sesion' if logged_in else 'anonimo'})...")
    try:
        detail = get_comic_detail(session, comic_id)
        episodes = display_chapters(detail)
        # Numeración visible de Bilibili: primer capítulo = 00, segundo = 01...
        chapter_numbers_by_id = {
            int(ep["id"]): index
            for index, ep in enumerate(episodes)
            if ep.get("id") is not None
        }
        selected = choose_chapters(episodes)
        if not selected:
            print("No seleccionaste capitulos. Saliendo.")
            return 0

        # Compra opcional de capítulos bloqueados (si hay sesión QR).
        bought_ids = purchase_selected_chapters(session, comic_id, selected)
        if bought_ids:
            show_account_wallet(session, "SALDO ACTUALIZADO TRAS LAS COMPRAS")
            try:
                refreshed = get_comic_detail(session, comic_id)
                fresh_by_id = {int(ep.get("id")): ep for ep in (refreshed.get("ep_list") or []) if ep.get("id") is not None}
                selected = [fresh_by_id.get(int(ep["id"]), ep) for ep in selected]
            except Exception as exc:
                print(f"[i] No pude refrescar la lista tras la compra: {exc}")

        title = detail.get("title") or f"manga_{comic_id}"
        output_root = Path(args.output).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        downloadable = [ep for ep in selected if not ep.get("is_locked")]
        still_locked = [ep for ep in selected if ep.get("is_locked")]
        if still_locked:
            print(f"\n[i] {len(still_locked)} capítulo(s) siguen bloqueados o no se pudieron comprar; se omitirán.")
        print(f"\nSe descargaran {len(downloadable)} capitulo(s) desbloqueados en: {output_root}")
        for episode in downloadable:
            try:
                download_episode(
                    session, comic_id, title, episode, output_root, args.workers,
                    chapter_number=chapter_numbers_by_id.get(int(episode["id"])),
                )
            except BilibiliError as exc:
                print(f"[ERROR] {exc}")
        print("\nProceso terminado.")
        return 0
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        return 130
    except BilibiliError as exc:
        print(f"\n[ERROR] {exc}")
        if not logged_in:
            print("Nota: el error de ComicDetail ocurre antes de comprobar permisos de capítulos; iniciar sesión no garantiza resolverlo.")
        return 1
    except requests.RequestException as exc:
        print(f"\n[ERROR de red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
