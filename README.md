# Bilibili Manga Client

A Python command-line client to inspect Bilibili Manga series, check chapter access, optionally unlock paid chapters with reading tickets or Manga coins, and download chapter images to your computer.

<details>
<summary><b>🇪🇸 Versión en Español (haz clic para expandir)</b></summary>

<br>

## 📖 Descripción

**Bilibili Manga Client** es un cliente de consola escrito en Python para consultar series de Bilibili Manga y descargar capítulos disponibles en tu cuenta.

Puedes introducir el ID de una serie o su URL web. El programa obtiene la lista de capítulos, muestra su estado de acceso y permite seleccionar qué capítulos descargar. También incluye inicio de sesión mediante QR, consulta del saldo de la cuenta y compra opcional de capítulos bloqueados usando tickets de lectura (`漫读券`) o monedas de Bilibili Manga (`漫币`).

> Esta herramienta no incluye un buscador interno. Debes obtener el ID desde la URL web de la serie o introducirlo directamente.

## ✨ Características principales

- **Inicio de sesión QR:** escanea un código QR con la aplicación oficial de Bilibili. También puedes continuar en modo anónimo para descargar capítulos a los que la API permita acceder sin iniciar sesión.
- **Sesión reutilizable:** después de iniciar sesión, las cookies se guardan localmente en `bilibili_cookies.json` para poder reutilizarlas en la siguiente ejecución.
- **Consulta del saldo:** muestra monedas (`漫币`), tickets de lectura (`漫读券`), cupones generales (`通用券`), tarjetas de lectura gratuita (`限免卡`) y otros campos del monedero que devuelva Bilibili.
- **Estado de capítulos:** utiliza `ComicDetail` como fuente del estado de acceso (`is_locked`). La consulta de precios no reemplaza ni modifica ese estado.
- **Precios y descuentos:** consulta `GetEpisodeBuyInfo` para conocer el precio actual, el precio original y las ofertas de descuento disponibles para cada capítulo bloqueado seleccionado.
- **Compra opcional:** admite compra con tickets de lectura o con monedas. El programa solicita confirmación explícita antes de enviar las compras.
- **Comprobación antes de pagar:** vuelve a consultar `ComicDetail` antes de cada compra para evitar intentar comprar un capítulo que ya esté desbloqueado.
- **Selección por índices y rangos:** por ejemplo, `1,3,5-8`, o `A` para seleccionar todos los capítulos.
- **Numeración de carpetas desde 00:** los capítulos se guardan con nombres como `00-Título`, `01-Título`, `02-Título`, siguiendo la numeración visible en el lector web.
- **Descarga concurrente:** descarga varias páginas a la vez (entre 1 y 8 trabajadores; 4 por defecto) y muestra el progreso en una sola línea.
- **Detección de formato:** identifica imágenes JPG, PNG, WEBP y GIF.
- **Soporte CPX:** incluye descifrado AES-CBC de imágenes protegidas que utilicen el formato CPX, cuando corresponda.
- **Reintentos:** vuelve a intentar las descargas de imágenes que fallen.

## 📋 Requisitos

- **Python 3.10 o superior.**
- Windows, macOS o Linux con acceso a Internet.
- Una cuenta de Bilibili para iniciar sesión y realizar compras. El modo anónimo puede utilizarse para capítulos que permitan acceso sin sesión.

### Dependencias

Abre CMD o PowerShell en la carpeta del proyecto y ejecuta:

```bash
py -m pip install requests "qrcode[pil]" pycryptodome
```

- `requests`: realiza las peticiones HTTP a Bilibili y descarga las imágenes.
- `qrcode[pil]`: genera la imagen del QR de inicio de sesión.
- `pycryptodome`: permite descifrar imágenes CPX cuando la serie utiliza ese formato.

`qrcode[pil]` solo es necesario para iniciar sesión mediante QR. `pycryptodome` es necesario cuando las imágenes descargadas requieren descifrado CPX.

## 📥 Instalación

### Opción A: descargar el código desde GitHub

1. Descarga el repositorio mediante **Code → Download ZIP**, o clónalo:

   ```bash
   git clone https://github.com/EryxZar/Bilibili-Manga-Client.git
   ```

2. Descomprime el ZIP, si corresponde.
3. Abre CMD o PowerShell dentro de la carpeta donde se encuentra `bilibili_manga_client.py`.
4. Instala las dependencias indicadas arriba.
5. Ejecuta el programa.

### Opción B: descargar solo el archivo Python

1. Descarga `bilibili_manga_client.py` desde el repositorio.
2. Guárdalo en una carpeta propia, por ejemplo `C:\BilibiliMangaClient\`.
3. Abre una terminal en esa carpeta.
4. Instala las dependencias y ejecuta el script.

## 🚀 Uso

### 1. Inicio interactivo

La forma más sencilla es ejecutar:

```bash
py bilibili_manga_client.py
```

El programa preguntará si deseas iniciar sesión con QR.

- Si eliges **Yes**, generará un QR y abrirá la imagen para que la escanees con la aplicación oficial de Bilibili.
- Si ya existe una sesión guardada, preguntará si deseas reutilizarla.
- Si eliges **No**, continuará sin iniciar sesión.

Después, introduce la URL de la serie o su ID numérico.

Ejemplos de ID y URL:

```text
34224
https://manga.bilibili.com/detail/mc34224
```

### 2. Inicio de sesión QR

También puedes forzar el inicio de sesión QR desde los argumentos:

```bash
py bilibili_manga_client.py --qr-login
```

El QR se guarda junto al script como `bilibili_login_qr.png`. El programa espera la confirmación del teléfono. Cuando el login es válido, guarda las cookies en `bilibili_cookies.json`.

**Importante:** `bilibili_cookies.json` contiene credenciales de sesión. No lo compartas, no lo adjuntes a incidencias y nunca lo subas a GitHub. El archivo se guarda como JSON local; no está cifrado por el programa. Protégelo como protegerías una contraseña.

### 3. Modo anónimo

Para evitar que el programa cargue una sesión guardada o pregunte por el QR:

```bash
py bilibili_manga_client_english.py --no-login --comic-id 34224
```

El modo anónimo no puede realizar compras. Además, los capítulos que requieren una cuenta o una compra previa no estarán disponibles.

### 4. Introducir una serie por argumento

Puedes proporcionar el ID o la URL directamente:

```bash
py bilibili_manga_client_english.py --comic-id 34224
```

```bash
py bilibili_manga_client_english.py --url "https://manga.bilibili.com/detail/mc34224"
```

Para forzar QR y pasar la serie en el mismo comando:

```bash
py bilibili_manga_client_english.py --qr-login --url "https://manga.bilibili.com/detail/mc34224"
```

### 5. Seleccionar capítulos

Después de consultar la serie, el programa muestra el título, número de orden, páginas, precio disponible e ID del capítulo. El estado de acceso se obtiene de `ComicDetail`.

En el campo de selección puedes escribir:

| Entrada | Acción |
|---|---|
| `A` | Seleccionar todos los capítulos. |
| `1` | Seleccionar el primer capítulo de la lista. |
| `1,3,5` | Seleccionar los capítulos 1, 3 y 5. |
| `1-10` | Seleccionar del capítulo 1 al 10. |
| `1-5,8,10-12` | Combinar rangos e índices. |

Los índices se refieren a la posición de los capítulos en la lista mostrada, no al `ep_id` de Bilibili.

### 6. Comprar capítulos bloqueados

La compra es opcional. Si seleccionas capítulos bloqueados y has iniciado sesión, el programa consulta los datos de compra y muestra las opciones disponibles.

**Tickets de lectura (`漫读券`):**

1. Elige la opción de tickets.
2. El programa consulta los tickets activos mediante `GetCoupons`.
3. Muestra los tickets que parecen compatibles con el manga, su cantidad restante y su vencimiento cuando Bilibili lo proporciona.
4. Confirma cuántos tickets deseas utilizar.

**Monedas (`漫币`):**

1. Elige la opción de monedas.
2. El programa consulta `GetEpisodeBuyInfo` para cada capítulo bloqueado seleccionado.
3. Muestra el precio actual, el precio original si es diferente y las ofertas de tarjeta de descuento que Bilibili comunica.
4. Calcula un total estimado antes de comprar.

Antes de cada compra, el cliente vuelve a consultar `ComicDetail` para comprobar que el capítulo continúa bloqueado. También vuelve a consultar la información de precio/descuento. Si el total estimado cambia, solicita una nueva confirmación para ese capítulo.

Para confirmar el lote de compras debes escribir exactamente:

```text
BUY
```

Si escribes otra cosa, no se envía la petición de compra.

> **Aviso sobre compras:** las monedas y tickets tienen valor dentro de tu cuenta. Revisa cuidadosamente el resumen antes de escribir `BUY`. La respuesta final de Bilibili es la autoridad sobre si una compra se acepta y qué descuento se aplicó. La disponibilidad y las condiciones de descuentos/tickets pueden cambiar según el capítulo y la cuenta.

### 7. Descarga y ubicación de los archivos

Después de seleccionar los capítulos, el programa descarga los que `ComicDetail` identifica como desbloqueados. Los capítulos que continúen bloqueados se omiten.

La estructura predeterminada es:

```text
Bilibili_Downloads/
└── Nombre de la serie/
    ├── 00-Título del capítulo/
    │   ├── 0001.jpg
    │   ├── 0002.jpg
    │   └── 0003.webp
    ├── 01-Título del capítulo/
    │   ├── 0001.jpg
    │   └── 0002.jpg
    └── 02-Título del capítulo/
        └── ...
```

La numeración de carpeta comienza en `00` y sigue el orden de la lista de capítulos. Los archivos de página se nombran con cuatro dígitos (`0001`, `0002`, etc.). La extensión depende del formato real de cada imagen.

Si la carpeta de un capítulo ya contiene imágenes, el programa pregunta si deseas omitirlo. Responde `Y` para omitir (valor predeterminado) o `n` para volver a descargarlo.

El progreso de las páginas se actualiza en una sola línea. Los errores se muestran en líneas separadas.

## ⚙️ Argumentos de línea de comandos

| Argumento | Descripción | Predeterminado |
|---|---|---|
| `--comic-id ID` | ID numérico de la serie. | Preguntar al iniciar. |
| `--url URL` | URL web de la serie que contiene `mc<ID>`. | Preguntar al iniciar. |
| `--qr-login` | Fuerza el inicio de sesión QR. | Desactivado. |
| `--no-login` | No carga la sesión guardada ni pregunta por QR. | Desactivado. |
| `--output PATH` | Carpeta raíz de descarga. | `Bilibili_Downloads` |
| `--workers N` | Número de descargas simultáneas (1–8). | `4` |
| `--help` | Muestra la ayuda. | — |

`--qr-login` y `--no-login` son opciones incompatibles.

Ejemplo con carpeta de salida personalizada y 6 descargas simultáneas:

```bash
py bilibili_manga_client.py --comic-id 34224 --output "D:\Manga" --workers 6
```

Consultar todos los argumentos:

```bash
py bilibili_manga_client.py --help
```

## 🧩 Explicación técnica y APIs utilizadas

El cliente utiliza peticiones HTTP a los servicios de Bilibili Manga. Varias rutas son servicios Twirp. Los nombres de los campos y parámetros se basan en las respuestas y peticiones observadas durante el análisis de la aplicación y las pruebas del cliente; Bilibili puede modificarlos sin previo aviso.

### 1. Inicio de sesión QR y sesión local

- `GET /x/passport-login/web/qrcode/generate`: solicita un QR y una clave de seguimiento.
- `GET /x/passport-login/web/qrcode/poll`: consulta si el QR fue escaneado y confirmado.
- `GET /x/web-interface/nav`: comprueba si la sesión se reconoce como iniciada.
- Las cookies recibidas se mantienen en `requests.Session` y se guardan localmente en `bilibili_cookies.json`.

El programa no implementa un mecanismo propio para renovar indefinidamente una sesión caducada. Si Bilibili deja de aceptar las cookies, inicia sesión otra vez mediante QR.

### 2. Huella del cliente

El programa consulta `https://api.bilibili.com/x/frontend/finger/spi` para obtener `buvid3` y `buvid4` cuando están disponibles. Si algunas peticiones devuelven `code=99`, realiza un intento de actualización de `buvid` y repite la petición una vez.

### 3. Información de la serie y capítulos

- **`ComicDetail`**: obtiene los metadatos de la serie y `ep_list`, con los IDs, títulos, orden, cantidad de páginas, precios disponibles y estado de acceso.
- **`is_locked`**: el estado de acceso mostrado y utilizado por el programa procede de `ComicDetail`.
- **`is_in_free`**: se utiliza junto con el estado de bloqueo al decidir si un capítulo debe pasar por el flujo de compra.

`GetEpisodeBuyInfo` no se utiliza para determinar si un capítulo está comprado o desbloqueado.

### 4. Monedero y tickets

- **`user.v1.User/GetWallet`**: consulta el saldo del monedero (`remain_gold`, `remain_coupon`, `remain_silver`, `remain_item` y otros campos disponibles).
- **`user.v1.User/GetCoupons`**: consulta los tickets activos y sus IDs. El programa utiliza `remain_amount`, `ID`, `expire_time` y restricciones disponibles para preparar la selección.

### 5. Precio y descuentos

- **`Comic/GetEpisodeBuyInfo`**: consulta el precio del capítulo y los datos de compra/descuento, entre ellos `pay_gold`, `ep_original_gold`, `free_gold_card` y `prime_info.single`.
- El cliente distingue el descuento que ya está incorporado en el precio actual de una oferta adicional de tarjeta de monedas.
- La estimación se vuelve a calcular antes de comprar. La respuesta del servidor puede rechazar una tarjeta o ajustar condiciones; por eso el importe estimado no debe interpretarse como garantía hasta que Bilibili confirme la compra.

### 6. Compra de capítulos

- **`Comic/BuyEpisode` con `buyMethod=2`**: modalidad de compra mediante ticket de lectura; envía `couponIds`.
- **`Comic/BuyEpisode` con `buyMethod=3`**: modalidad de compra mediante monedas; envía `payAmount` y, cuando la oferta se reconoce como aplicable, `freeGoldCardId` y `freeGoldAmount`.
- El programa requiere una sesión iniciada y una confirmación explícita con `BUY`.
- Antes de cada compra consulta de nuevo `ComicDetail` y `GetEpisodeBuyInfo`. Si el estado ya es desbloqueado, omite la compra.

### 7. Índice, tokens y descarga de imágenes

- **`Comic/GetImageIndex`**: recupera las rutas de las páginas del capítulo.
- **`Comic/ImageToken`**: solicita los URLs/tokens necesarios para descargar esas páginas.
- El cliente descarga las imágenes con concurrencia limitada y hasta tres intentos por página.
- Reconoce JPG, PNG, WEBP y GIF por su contenido.
- Cuando el URL y la respuesta indican contenido CPX, utiliza AES-CBC mediante `pycryptodome` para restaurar la imagen.

## 🛠️ Solución de problemas

**El inicio de sesión QR no se completa**

- Comprueba que el QR no haya caducado y vuelve a ejecutar con `--qr-login`.
- Asegúrate de escanearlo y confirmar el inicio de sesión en la aplicación oficial.
- Si una sesión guardada ya no sirve, permite que el programa la rechace y vuelve a iniciar sesión.

**`code=99` o error al consultar la serie**

- Puede deberse a controles de riesgo, parámetros de cliente que hayan cambiado o restricciones temporales de Bilibili.
- El programa renueva `buvid` y reintenta una vez, pero no puede garantizar que Bilibili acepte la petición.
- Prueba de nuevo más tarde y utiliza una sesión QR válida cuando el endpoint lo requiera.

**No aparecen precios para algunos capítulos**

- `ComicDetail` puede no proporcionar el precio en todos los registros. Para capítulos bloqueados seleccionados, el cliente intenta consultar `GetEpisodeBuyInfo`.
- Si esa consulta falla, el capítulo se excluye del lote de compra para evitar enviar una petición con información incompleta.

**Un ticket no se puede utilizar**

- Algunos tickets tienen restricciones de serie, tipo o vencimiento. El cliente filtra las restricciones que puede interpretar, pero Bilibili valida finalmente si el ticket puede utilizarse.

**Una imagen no se descarga o no se puede descifrar**

- Comprueba la conexión y vuelve a intentar la descarga.
- Verifica que instalaste `pycryptodome` si el mensaje indica que la imagen requiere CPX.
- Algunas imágenes o capítulos pueden dejar de estar disponibles o cambiar su mecanismo de entrega.

**El capítulo aparece bloqueado y se omite**

- El cliente sigue el estado recibido de `ComicDetail`. Comprueba que la compra se haya completado en Bilibili y vuelve a consultar la serie.

## 🔐 Privacidad y seguridad

- `bilibili_cookies.json` contiene cookies de autenticación y debe tratarse como una contraseña.
- No publiques cookies, `SESSDATA`, `bili_jct`, `access_key`, tokens de imagen ni capturas de Network que los incluyan.
- El cliente no necesita que pegues manualmente tu `access_key`; utiliza la sesión obtenida mediante QR.
- Usa el proyecto únicamente con tu propia cuenta y respeta los términos de Bilibili y los derechos de autor de los creadores.

## ⚠️ Aviso legal

Este proyecto es una herramienta independiente y no está afiliado, respaldado ni mantenido por Bilibili. Se proporciona con fines de aprendizaje, interoperabilidad y archivo personal. No distribuyas capítulos descargados ni utilices el programa para eludir pagos, restricciones regionales o controles de acceso. Las compras utilizan el saldo real de la cuenta y son responsabilidad del usuario.

Las APIs no son interfaces públicas estables para terceros. Bilibili puede cambiar las rutas, parámetros, autenticación o mecanismos de protección; por lo tanto, no se garantiza disponibilidad continua ni compatibilidad futura.

</details>

<details>
<summary><b>🇬🇧 English Version (click to expand)</b></summary>

<br>

## 📖 Overview

**Bilibili Manga Client** is a Python command-line tool for inspecting Bilibili Manga series and downloading chapters available to your account.

Enter a comic ID or its web URL. The client retrieves the chapter list, displays access status, and lets you select chapters to download. It also supports QR login, wallet balance lookup, and optional purchases of locked chapters using reading tickets (`漫读券`) or Bilibili Manga coins (`漫币`).

> There is no built-in series search. Get the comic ID from its web URL or enter the numeric ID directly.

## ✨ Key Features

- **QR login:** scan a QR code with the official Bilibili app. Anonymous mode is also available for chapters that can be accessed without signing in.
- **Reusable session:** after login, cookies are saved locally in `bilibili_cookies.json` and can be reused on the next run.
- **Wallet display:** shows Manga coins (`漫币`), reading tickets (`漫读券`), general coupons (`通用券`), free-reading cards (`限免卡`), and other wallet fields returned by Bilibili.
- **Chapter access status:** uses `ComicDetail` as the source of truth for chapter access (`is_locked`). Purchase-price lookups do not replace or modify that status.
- **Prices and discounts:** calls `GetEpisodeBuyInfo` to retrieve the current price, original price, and discount-card offers for each selected locked chapter.
- **Optional purchases:** supports reading-ticket and Manga-coin purchases. Explicit confirmation is required before purchase requests are sent.
- **Pre-purchase check:** queries `ComicDetail` again before each purchase to avoid buying a chapter that has already become unlocked.
- **Range selection:** select chapters using expressions such as `1,3,5-8`, or enter `A` to select all chapters.
- **00-based folder numbering:** downloaded chapter folders use names such as `00-Title`, `01-Title`, and `02-Title`, matching the numbering shown in the web reader.
- **Concurrent downloads:** downloads multiple pages at once (1–8 workers; 4 by default) and updates progress on a single console line.
- **Image format detection:** recognizes JPG, PNG, WEBP, and GIF images.
- **CPX support:** includes AES-CBC decryption for protected CPX images when required.
- **Retries:** retries failed image downloads.

## 📋 Requirements

- **Python 3.10 or newer.**
- Windows, macOS, or Linux with Internet access.
- A Bilibili account for QR login and purchases. Anonymous mode may be used for content available without an account.

### Dependencies

Open CMD, PowerShell, or a terminal in the project folder and run:

```bash
py -m pip install requests "qrcode[pil]" pycryptodome
```

- `requests`: sends HTTP requests to Bilibili and downloads images.
- `qrcode[pil]`: generates the QR login image.
- `pycryptodome`: decrypts CPX images when a series uses that format.

`qrcode[pil]` is only needed for QR login. `pycryptodome` is needed only when downloaded images require CPX decryption.

## 📥 Installation

### Option A: Download the repository from GitHub

1. Download the repository using **Code → Download ZIP**, or clone it:

   ```bash
   git clone https://github.com/EryxZar/Bilibili-Manga-Client.git
   ```

2. Extract the ZIP if needed.
3. Open CMD, PowerShell, or a terminal in the folder containing `bilibili_manga_client.py`.
4. Install the dependencies listed above.
5. Run the client.

### Option B: Download the Python file only

1. Download `bilibili_manga_client.py` from the repository.
2. Save it in a dedicated folder, for example `C:\BilibiliMangaClient\`.
3. Open a terminal in that folder.
4. Install the dependencies and run the script.

## 🚀 Usage

### 1. Interactive startup

The easiest way to start the client is:

```bash
py bilibili_manga_client.py
```

The program asks whether you want to log in using a QR code.

- Select **Yes** to generate a QR image and open it so you can scan it with the official Bilibili app.
- If a saved session exists, the program asks whether you want to reuse it.
- Select **No** to continue anonymously.

Then enter the series URL or numeric ID.

Example ID and URL:

```text
34224
https://manga.bilibili.com/detail/mc34224
```

### 2. QR login

You can force QR login using:

```bash
py bilibili_manga_client.py --qr-login
```

The QR image is saved beside the script as `bilibili_login_qr.png`. The program waits for confirmation on your phone. Once login is validated, cookies are saved to `bilibili_cookies.json`.

**Important:** `bilibili_cookies.json` contains session credentials. Do not share it, attach it to bug reports, or commit it to GitHub. The program stores this file as local JSON; it does not encrypt it. Protect it like a password.

### 3. Anonymous mode

To prevent the program from loading a saved session or prompting for QR login, run:

```bash
py bilibili_manga_client.py --no-login --comic-id 34224
```

Anonymous mode cannot make purchases. Chapters that require an account or prior purchase will not be accessible.

### 4. Pass a series as a command-line argument

You can provide the numeric ID or URL directly:

```bash
py bilibili_manga_client.py --comic-id 34224
```

```bash
py bilibili_manga_client.py --url "https://manga.bilibili.com/detail/mc34224"
```

To force QR login and provide the series in the same command:

```bash
py bilibili_manga_client.py --qr-login --url "https://manga.bilibili.com/detail/mc34224"
```

### 5. Select chapters

After retrieving the series, the client displays the title, chapter order, page count, available price, and chapter ID. Access status comes from `ComicDetail`.

At the selection prompt, enter:

| Input | Action |
|---|---|
| `A` | Select all chapters. |
| `1` | Select the first chapter in the list. |
| `1,3,5` | Select chapters 1, 3, and 5. |
| `1-10` | Select chapters 1 through 10. |
| `1-5,8,10-12` | Combine ranges and individual indexes. |

Selection indexes refer to the position in the displayed list, not Bilibili's `ep_id`.

### 6. Purchase locked chapters

Purchases are optional. If selected chapters are locked and you are logged in, the program retrieves purchase information and displays the available options.

**Reading tickets (`漫读券`):**

1. Choose the reading-ticket option.
2. The client queries active tickets using `GetCoupons`.
3. It displays tickets that appear compatible with the comic, their remaining quantity, and expiration date when provided by Bilibili.
4. Confirm how many tickets you want to use.

**Manga coins (`漫币`):**

1. Choose the coin option.
2. The program queries `GetEpisodeBuyInfo` for each selected locked chapter.
3. It displays the current price, original price when different, and coin discount-card offers returned by Bilibili.
4. It calculates an estimated total before purchasing.

Before each purchase, the client queries `ComicDetail` again to verify that the chapter is still locked. It also refreshes the price/discount information. If the estimated amount changes, the program asks for a new confirmation for that chapter.

To confirm the purchase batch, type exactly:

```text
BUY
```

If you enter anything else, no purchase request is sent.

> **Purchase warning:** coins and tickets have real value in your account. Carefully review the purchase summary before typing `BUY`. Bilibili's response is authoritative for whether a purchase succeeds and which discount is applied. Discount and ticket availability may vary by chapter and account.

### 7. Downloads and output structure

After selection, the program downloads chapters that `ComicDetail` marks as unlocked. Chapters that remain locked are skipped.

The default output structure is:

```text
Bilibili_Downloads/
└── Series_Name/
    ├── 00-Chapter_Title/
    │   ├── 0001.jpg
    │   ├── 0002.jpg
    │   └── 0003.webp
    ├── 01-Chapter_Title/
    │   ├── 0001.jpg
    │   └── 0002.jpg
    └── 02-Chapter_Title/
        └── ...
```

Folder numbering starts at `00` and follows the order of the displayed chapter list. Page files use four-digit numbering (`0001`, `0002`, etc.). The file extension is based on the actual image format.

If a chapter folder already contains images, the program asks whether to skip it. Enter `Y` to skip (the default) or `n` to download it again.

Page progress is updated on a single console line. Errors are printed on separate lines.

## ⚙️ Command-line arguments

| Argument | Description | Default |
|---|---|---|
| `--comic-id ID` | Numeric series ID. | Prompt at startup. |
| `--url URL` | Series webpage URL containing `mc<ID>`. | Prompt at startup. |
| `--qr-login` | Force QR login. | Disabled. |
| `--no-login` | Do not load a saved session or prompt for QR login. | Disabled. |
| `--output PATH` | Download root folder. | `Bilibili_Downloads` |
| `--workers N` | Number of concurrent downloads (1–8). | `4` |
| `--help` | Show help. | — |

`--qr-login` and `--no-login` cannot be used together.

Example using a custom output folder and 6 concurrent downloads:

```bash
py bilibili_manga_client_english.py --comic-id 34224 --output "D:\Manga" --workers 6
```

Show all available arguments:

```bash
py bilibili_manga_client_english.py --help
```

## 🧩 Technical overview and APIs

The client sends HTTP requests to Bilibili Manga services. Several endpoints are Twirp services. Request fields and parameters are based on observed API responses/requests and client testing; Bilibili may change them without notice.

### 1. QR authentication and local session

- `GET /x/passport-login/web/qrcode/generate`: requests a QR code and tracking key.
- `GET /x/passport-login/web/qrcode/poll`: checks whether the QR code has been scanned and confirmed.
- `GET /x/web-interface/nav`: validates the authenticated session.
- Cookies are retained in `requests.Session` and saved locally in `bilibili_cookies.json`.

The client does not implement indefinite automatic renewal of expired sessions. If Bilibili no longer accepts the saved cookies, log in again using QR.

### 2. Client fingerprint

The program queries `https://api.bilibili.com/x/frontend/finger/spi` to obtain `buvid3` and `buvid4` when available. If a request returns `code=99`, it refreshes the `buvid` fingerprint and retries the request once.

### 3. Series and chapter information

- **`ComicDetail`**: retrieves series metadata and `ep_list`, including IDs, titles, order, page count, available prices, and access status.
- **`is_locked`**: the displayed access status and purchase eligibility are based on `ComicDetail`.
- **`is_in_free`**: is considered together with the lock flag when deciding whether a chapter should enter the purchase flow.

`GetEpisodeBuyInfo` is not used to determine whether a chapter has already been purchased or unlocked.

### 4. Wallet and tickets

- **`user.v1.User/GetWallet`**: retrieves wallet balances such as `remain_gold`, `remain_coupon`, `remain_silver`, `remain_item`, and other available fields.
- **`user.v1.User/GetCoupons`**: retrieves active tickets and their IDs. The client uses fields such as `remain_amount`, `ID`, `expire_time`, and available restrictions to prepare the selection.

### 5. Prices and discounts

- **`Comic/GetEpisodeBuyInfo`**: retrieves chapter purchase details, including `pay_gold`, `ep_original_gold`, `free_gold_card`, and `prime_info.single`.
- The client distinguishes a discount already reflected in the current price from an additional coin-discount-card offer.
- The price is checked again before purchase. The server may reject a card or adjust the purchase conditions, so an estimate is not a guarantee until Bilibili confirms the transaction.

### 6. Chapter purchases

- **`Comic/BuyEpisode` with `buyMethod=2`**: reading-ticket purchase; sends `couponIds`.
- **`Comic/BuyEpisode` with `buyMethod=3`**: Manga-coin purchase; sends `payAmount` and, when the offer is recognized as applicable, `freeGoldCardId` and `freeGoldAmount`.
- A logged-in session and explicit `BUY` confirmation are required.
- Before each purchase, the client queries `ComicDetail` and `GetEpisodeBuyInfo` again. If the chapter is already unlocked, the purchase is skipped.

### 7. Image index, tokens, and downloads

- **`Comic/GetImageIndex`**: retrieves chapter page paths.
- **`Comic/ImageToken`**: requests the URLs/tokens needed to download the pages.
- The client downloads images with limited concurrency and retries each failed page up to three times.
- It identifies JPG, PNG, WEBP, and GIF formats from the response content.
- When the URL and response indicate CPX content, AES-CBC decryption is performed through `pycryptodome`.

## 🛠️ Troubleshooting

**QR login does not complete**

- Check that the QR code has not expired and rerun with `--qr-login`.
- Scan the code and confirm login in the official app.
- If a saved session is no longer valid, let the client reject it and sign in again.

**`code=99` or an error while loading the series**

- This may be caused by risk-control checks, changed client parameters, or temporary Bilibili restrictions.
- The program refreshes `buvid` and retries once, but cannot guarantee that Bilibili will accept the request.
- Try again later and use a valid QR session when the endpoint requires one.

**Prices are missing for some chapters**

- `ComicDetail` may not include a price for every chapter. For selected locked chapters, the client attempts `GetEpisodeBuyInfo`.
- If that lookup fails, the chapter is excluded from the purchase batch to avoid sending a request with incomplete information.

**A reading ticket cannot be used**

- Some tickets have comic, type, or expiration restrictions. The client filters restrictions it can interpret, but Bilibili makes the final eligibility decision.

**An image cannot be downloaded or decrypted**

- Check your connection and retry.
- Install `pycryptodome` if the error says the image requires CPX decryption.
- Some images or chapters may become unavailable or use a changed delivery method.

**A chapter is shown as locked and skipped**

- The client follows the access status returned by `ComicDetail`. Check that the purchase completed on Bilibili, then query the series again.

## 🔐 Privacy and security

- `bilibili_cookies.json` contains authentication cookies and must be treated like a password.
- Do not publish cookies, `SESSDATA`, `bili_jct`, `access_key`, image tokens, or Network captures containing them.
- The client does not require you to paste an `access_key` manually; it uses the session obtained through QR login.
- Use the project only with your own account and respect Bilibili's terms and creators' copyrights.

## ⚠️ Disclaimer

This is an independent project and is not affiliated with, endorsed by, or maintained by Bilibili. It is provided for learning, interoperability, and personal archiving. Do not redistribute downloaded chapters or use the program to bypass payments, regional restrictions, or access controls. Purchases use the real balance in your account and are the user's responsibility.

These APIs are not stable public third-party interfaces. Bilibili may change endpoints, parameters, authentication, or protection mechanisms; therefore, continued availability and future compatibility are not guaranteed.

</details>
