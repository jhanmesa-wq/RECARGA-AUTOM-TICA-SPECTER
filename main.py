import requests
import json
import os
import re
import functools
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, Message, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# ─────────── CONFIGURACIÓN ───────────
GRIZZLY_API_KEY = os.getenv("GRIZZLY_API_KEY", "PON_TU_CLAVE_GRIZZLY_AQUI")
BOT_TOKEN = os.getenv("BOT_TOKEN", "PON_TU_TOKEN_TELEGRAM_AQUI")
ADMIN_ID_ENV = os.getenv("ADMIN_ID", "")
BASE_URL = "https://api.grizzly-sms.com/v2"

ADMIN_IDS = [ADMIN_ID_ENV] if ADMIN_ID_ENV else []
COSTO_POR_NUMERO = 1
CREDITOS_INICIALES = 0
ARCHIVO_CREDITOS = "creditos.json"

PAISES = {
    "pe": {"nombre": "🇵🇪 Perú", "codigo": 197, "prefijo": "+51"},
    "mx": {"nombre": "🇲🇽 México", "codigo": 187, "prefijo": "+52"},
    "ar": {"nombre": "🇦🇷 Argentina", "codigo": 6, "prefijo": "+54"},
    "cl": {"nombre": "🇨🇱 Chile", "codigo": 176, "prefijo": "+56"},
    "co": {"nombre": "🇨🇴 Colombia", "codigo": 181, "prefijo": "+57"},
    "es": {"nombre": "🇪🇸 España", "codigo": 146, "prefijo": "+34"},
    "us": {"nombre": "🇺🇸 Estados Unidos", "codigo": 185, "prefijo": "+1"},
    "ve": {"nombre": "🇻🇪 Venezuela", "codigo": 190, "prefijo": "+58"},
    "br": {"nombre": "🇧🇷 Brasil", "codigo": 172, "prefijo": "+55"},
}

SERVICIOS = {
    "wa": {"nombre": "WhatsApp", "codigo": "whatsapp"},
    "tg": {"nombre": "Telegram", "codigo": "telegram"},
    "fb": {"nombre": "Facebook", "codigo": "facebook"},
    "ig": {"nombre": "Instagram", "codigo": "instagram"},
    "gg": {"nombre": "Google", "codigo": "google"},
    "tk": {"nombre": "TikTok", "codigo": "tiktok"},
}

headers = {
    "Authorization": f"Bearer {GRIZZLY_API_KEY}",
    "Content-Type": "application/json"
}

numeros_activos = {}

# ============================================================
# 🛡️ KEEP ALIVE - PARA RENDER WEB SERVICE
# ============================================================
def keep_alive():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot alive - Premium System ON")
        def log_message(self, *args):
            return
    port = int(os.environ.get("PORT", 10000))
    def run():
        try:
            httpd = HTTPServer(("0.0.0.0", port), Handler)
            print(f"🌐 Keep alive server en puerto {port}")
            httpd.serve_forever()
        except Exception as e:
            print(f"Keep alive error: {e}")
    threading.Thread(target=run, daemon=True).start()

# ============================================================
# ⭐ STICKERS / EMOJIS PREMIUM GLOBALES
# ============================================================
PREMIUM_STICKERS = {
    "1": "5431650332419563627",
    "2": "6219810752887262728",
    "3": "6298670698948724690",
    "4": "5098585844931888090",
    "5": "5260553279321944543",
    "6": "5098578393163629920",
    "7": "5429381339851796035",
    "8": "5179570356695860413",
    "9": "5177431372788139022",
    "10": "5098536693326152842",
    "11": "5260463209562776385",
    "12": "5096114086958072826",
}

def premium(texto: str) -> str:
    if texto is None:
        return texto
    texto = str(texto)
    def reemplazar(match):
        numero = match.group(1)
        custom_id = PREMIUM_STICKERS.get(numero)
        if not custom_id:
            return match.group(0)
        return f'<tg-emoji emoji-id="{custom_id}">🔹</tg-emoji>'
    texto = re.sub(r"\[(\d+)\]", reemplazar, texto)
    texto = re.sub(r"\[E(\d+)\]", reemplazar, texto)
    return texto

def _patch_premium_method(cls, method_name):
    original = getattr(cls, method_name, None)
    if original is None:
        return
    if getattr(original, "_premium_global", False):
        return
    @functools.wraps(original)
    async def wrapped(self, *args, **kwargs):
        changed = False
        for key in ("text", "caption"):
            if key in kwargs and isinstance(kwargs[key], str):
                nuevo = premium(kwargs[key])
                if nuevo != kwargs[key]:
                    kwargs[key] = nuevo
                    changed = True
        if not changed and args:
            args = list(args)
            for i, value in enumerate(args):
                if isinstance(value, str) and "[" in value:
                    nuevo = premium(value)
                    if nuevo != value:
                        args[i] = nuevo
                        changed = True
                        break
            args = tuple(args)
        if changed and "parse_mode" not in kwargs:
            kwargs["parse_mode"] = "HTML"
        return await original(self, *args, **kwargs)
    wrapped._premium_global = True
    setattr(cls, method_name, wrapped)

def instalar_stickers_premium_globales():
    metodos = ("send_message", "reply_text", "edit_message_text", "edit_text", "send_photo", "reply_photo", "send_video", "reply_video",)
    for metodo in metodos:
        if hasattr(Message, metodo):
            _patch_premium_method(Message, metodo)
    for metodo in metodos:
        if hasattr(Bot, metodo):
            _patch_premium_method(Bot, metodo)

def cargar_creditos():
    if not os.path.exists(ARCHIVO_CREDITOS):
        with open(ARCHIVO_CREDITOS, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    try:
        with open(ARCHIVO_CREDITOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def guardar_creditos(data):
    with open(ARCHIVO_CREDITOS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_creditos(user_id: str) -> int:
    db = cargar_creditos()
    return db.get(str(user_id), CREDITOS_INICIALES)

def add_creditos(user_id: str, cantidad: int) -> int:
    db = cargar_creditos()
    actual = db.get(str(user_id), CREDITOS_INICIALES)
    nuevo = actual + cantidad
    db[str(user_id)] = nuevo
    guardar_creditos(db)
    return nuevo

def descontar_creditos(user_id: str, cantidad: int) -> bool:
    db = cargar_creditos()
    actual = db.get(str(user_id), CREDITOS_INICIALES)
    if actual < cantidad:
        return False
    db[str(user_id)] = actual - cantidad
    guardar_creditos(db)
    return True

async def creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    saldo = get_creditos(user_id)
    texto = f"[1] 💳 <b>SISTEMA DE CRÉDITOS PREMIUM</b>\n\n[2] 👤 Usuario: <code>{user_id}</code>\n[3] 💰 Saldo actual: <b>{saldo} créditos</b>\n[4] 💵 Costo: <b>{COSTO_POR_NUMERO} crédito = 1 número</b>\n\n[5] 🛒 Para comprar:\n<code>/comprar pe wa</code>"
    await update.message.reply_text(texto, parse_mode="HTML")

async def agregar_creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = str(update.effective_user.id)
    if ADMIN_IDS and admin_id not in ADMIN_IDS:
        await update.message.reply_text("[9] ❌ <b>No tienes permisos.</b>", parse_mode="HTML")
        return
    if len(context.args) < 2:
        await update.message.reply_text("[1] ⚠️ <b>Uso:</b>\n<code>/addcreditos [ID] [CANTIDAD]</code>", parse_mode="HTML")
        return
    target_id = context.args[0]
    try:
        cantidad = int(context.args[1])
    except:
        await update.message.reply_text("[9] ❌ Cantidad inválida.", parse_mode="HTML")
        return
    nuevo = add_creditos(target_id, cantidad)
    await update.message.reply_text(f"[7] ✅ <b>CRÉDITOS AGREGADOS</b>\n\n[2] 👤 <code>{target_id}</code>\n[3] ➕ <b>{cantidad}</b>\n[4] 💰 Nuevo saldo: <b>{nuevo}</b>", parse_mode="HTML")

async def paises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    saldo_actual = get_creditos(user_id)
    texto = f"[1] 🌍 <b>PAÍSES DISPONIBLES</b> | 💰 Saldo: <b>{saldo_actual}</b>\n\n"
    for clave, info in PAISES.items():
        texto += f"{info['nombre']} → <code>/comprar {clave} wa</code>\n"
    texto += "\n[2] 📱 <b>Servicios:</b>\n"
    for clave, info in SERVICIOS.items():
        texto += f"{info['nombre']} → <code>{clave}</code>\n"
    texto += f"\n[3] 💳 /creditos"
    await update.message.reply_text(texto, parse_mode="HTML")

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text("[1] ⚠️ <b>Uso:</b> <code>/comprar [país] [servicio] [cantidad]</code>", parse_mode="HTML")
        return
    clave_pais = context.args[0].lower()
    clave_servicio = context.args[1].lower()
    cantidad = 1
    if len(context.args) >= 3:
        try:
            cantidad = max(1, min(20, int(context.args[2])))
        except:
            cantidad = 1
    if clave_pais not in PAISES or clave_servicio not in SERVICIOS:
        await update.message.reply_text("[9] ❌ País o servicio inválido.", parse_mode="HTML")
        return
    saldo_actual = get_creditos(user_id)
    costo_total = cantidad * COSTO_POR_NUMERO
    if saldo_actual < costo_total:
        await update.message.reply_text(f"[9] ❌ <b>SALDO INSUFICIENTE</b>\n\n[3] 💰 Saldo: <b>{saldo_actual}</b>\n[4] 💵 Requiere: <b>{costo_total}</b>", parse_mode="HTML")
        return
    pais = PAISES[clave_pais]
    servicio = SERVICIOS[clave_servicio]
    mensaje = await update.message.reply_text(f"[2] 🔄 Comprando <b>{cantidad}</b> de {pais['nombre']} para {servicio['nombre']}...", parse_mode="HTML")
    resultados = []
    errores = []
    for i in range(cantidad):
        try:
            resp = requests.get(f"{BASE_URL}/buy/number", params={"country": pais["codigo"], "service": servicio["codigo"]}, headers=headers, timeout=30)
            datos = resp.json()
            if datos.get("success") or datos.get("number"):
                numero = datos.get("number")
                id_solicitud = datos.get("id") or datos.get("request_id")
                resultados.append({"numero": numero, "id": id_solicitud})
                if user_id not in numeros_activos:
                    numeros_activos[user_id] = []
                numeros_activos[user_id].append({"numero": numero, "id": id_solicitud})
            else:
                errores.append(f"#{i+1}: {datos.get('message', 'Sin stock')}")
        except Exception as e:
            errores.append(f"#{i+1}: {str(e)}")
    if resultados:
        descontar_creditos(user_id, len(resultados) * COSTO_POR_NUMERO)
    saldo_restante = get_creditos(user_id)
    texto = f"[7] ✅ <b>COMPRA COMPLETADA</b>\n🌍 {pais['nombre']} | 📱 {servicio['nombre']}\n📱 Comprados: <b>{len(resultados)}/{cantidad}</b>\n💳 Saldo: <b>{saldo_restante}</b>\n\n"
    if resultados:
        texto += "[8] <b>📋 NÚMEROS:</b>\n"
        for idx, item in enumerate(resultados, 1):
            texto += f"{idx}. 📱 <code>+{item['numero']}</code>\n 🆔 <code>{item['id']}</code>\n"
    if errores:
        texto += "\n[9] ❌ <b>Errores:</b>\n" + "\n".join(errores[:3])
    await mensaje.edit_text(texto, parse_mode="HTML")

async def codigos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in numeros_activos or not numeros_activos[user_id]:
        await update.message.reply_text("[1] ❌ No tienes números guardados.", parse_mode="HTML")
        return
    mensaje = await update.message.reply_text("[2] 🔄 Consultando códigos... ⏳")
    texto = f"[3] 📋 <b>TUS CÓDIGOS</b> — Total: {len(numeros_activos[user_id])}\n\n"
    for idx, item in enumerate(numeros_activos[user_id], 1):
        codigo = await consultar_codigo(item["id"])
        if codigo:
            texto += f"[4] {idx}. 📱 <code>+{item['numero']}</code>\n🔐 <b>CÓDIGO:</b> <code>{codigo}</code>\n\n"
        else:
            texto += f"[5] {idx}. 📱 <code>+{item['numero']}</code>\n⏳ Esperando...\n\n"
    await mensaje.edit_text(texto, parse_mode="HTML")

async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("[1] ⚠️ Uso: /verificar [ID]", parse_mode="HTML")
        return
    codigo = await consultar_codigo(context.args[0])
    if codigo:
        await update.message.reply_text(f"[2] ✅ <b>CÓDIGO:</b> <code>{codigo}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"[3] ⏳ Aún no llega.", parse_mode="HTML")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in numeros_activos:
        cant = len(numeros_activos[user_id])
        del numeros_activos[user_id]
        await update.message.reply_text(f"[1] ✅ Borrados {cant}.", parse_mode="HTML")
    else:
        await update.message.reply_text("[2] Vacío.", parse_mode="HTML")

async def consultar_codigo(id_solicitud):
    try:
        resp = requests.get(f"{BASE_URL}/sms/{id_solicitud}", headers=headers, timeout=30)
        datos = resp.json()
        return datos.get("sms") or datos.get("code")
    except:
        return None

def main():
    instalar_stickers_premium_globales()
    keep_alive()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("paises", paises))
    application.add_handler(CommandHandler("comprar", comprar))
    application.add_handler(CommandHandler("codigos", codigos))
    application.add_handler(CommandHandler("verificar", verificar))
    application.add_handler(CommandHandler("limpiar", limpiar))
    application.add_handler(CommandHandler("creditos", creditos))
    application.add_handler(CommandHandler("saldo", creditos))
    application.add_handler(CommandHandler("addcreditos", agregar_creditos))

    print("==============================================")
    print("✅ BOT INICIADO - CON KEEP_ALIVE")
    print("⭐ STICKERS PREMIUM GLOBALES")
    print("💳 CRÉDITOS ACTIVOS")
    print("🌐 KEEP ALIVE ACTIVO")
    print("==============================================")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
