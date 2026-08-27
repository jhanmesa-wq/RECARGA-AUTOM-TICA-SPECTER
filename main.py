# -*- coding: utf-8 -*-
import requests
import asyncio
import json
import os
import re
import functools

from telegram import Update, Message, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# ─────────── CONFIGURACIÓN ───────────
GRIZZLY_API_KEY = os.getenv("GRIZZLY_API_KEY", "PON_TU_CLAVE_GRIZZLY_AQUI")
BOT_TOKEN = os.getenv("BOT_TOKEN", "PON_TU_TOKEN_TELEGRAM_AQUI")
ADMIN_ID_ENV = os.getenv("ADMIN_ID", "")
BASE_URL = "https://api.grizzly-sms.com/v2"

# 👑 CONFIGURACIÓN DE CRÉDITOS
ADMIN_IDS = ["PON_TU_ID_TELEGRAM_AQUI"]
COSTO_POR_NUMERO = 1
CREDITOS_INICIALES = 0
ARCHIVO_CREDITOS = "creditos.json"

# 🌍 PAÍSES DISPONIBLES
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

# 📱 SERVICIOS
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
    metodos = (
        "send_message", "reply_text", "edit_message_text", "edit_text",
        "send_photo", "reply_photo", "send_video", "reply_video",
    )
    for metodo in metodos:
        if hasattr(Message, metodo):
            _patch_premium_method(Message, metodo)
    for metodo in metodos:
        if hasattr(Bot, metodo):
            _patch_premium_method(Bot, metodo)

# ──────────────────────────────────────────────────────────────
# 💳 SISTEMA DE CRÉDITOS PREMIUM
# ──────────────────────────────────────────────────────────────
def cargar_creditos():
    if not os.path.exists(ARCHIVO_CREDITOS):
        with open(ARCHIVO_CREDITOS, "w", encoding="utf-8") as f:
            json.dump({}, f)
        return {}
    try:
        with open(ARCHIVO_CREDITOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

# ──────────────────────────────────────────────────────────────
# 🛡️ ANTI-DORMIR FIX PARA RENDER + PTB v21 + Python 3.14
# ──────────────────────────────────────────────────────────────
async def anti_dormir_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        # Petición ligera para que Render no duerma y la API siga viva
        requests.get("https://api.grizzly-sms.com/v2/user/profile", headers=headers, timeout=15)
    except:
        pass

# ──────────────────────────────────────────────────────────────
# 💳 COMANDOS CRÉDITOS CON ESTIKER PREMIUM GLOBAL
# ──────────────────────────────────────────────────────────────
async def creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    saldo = get_creditos(user_id)
    texto = (
        f"[1] 💳 <b>SISTEMA DE CRÉDITOS PREMIUM</b>\n\n"
        f"[2] 👤 Usuario: <code>{user_id}</code>\n"
        f"[3] 💰 Saldo actual: <b>{saldo} créditos</b>\n"
        f"[4] 💵 Costo: <b>{COSTO_POR_NUMERO} crédito = 1 número</b>\n\n"
        f"[5] 🛒 Para comprar:\n<code>/comprar pe wa</code>\n\n"
        f"[6] 📞 Contacta al admin para recargar."
    )
    await update.message.reply_text(texto, parse_mode="HTML")

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await creditos(update, context)

async def agregar_creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = str(update.effective_user.id)
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("[9] ❌ <b>No tienes permisos para usar este comando.</b>", parse_mode="HTML")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "[1] ⚠️ <b>Uso ADMIN:</b>\n<code>/addcreditos [ID_USUARIO] [CANTIDAD]</code>\n\nEjemplo:\n<code>/addcreditos 123456789 10</code>",
            parse_mode="HTML"
        )
        return
    target_id = context.args[0]
    try:
        cantidad = int(context.args[1])
    except:
        await update.message.reply_text("[9] ❌ La cantidad debe ser un número.", parse_mode="HTML")
        return
    nuevo_saldo = add_creditos(target_id, cantidad)
    await update.message.reply_text(
        f"[7] ✅ <b>CRÉDITOS AGREGADOS CON ÉXITO</b>\n\n"
        f"[2] 👤 Usuario: <code>{target_id}</code>\n"
        f"[3] ➕ Agregados: <b>{cantidad}</b>\n"
        f"[4] 💰 Nuevo saldo: <b>{nuevo_saldo} créditos</b>",
        parse_mode="HTML"
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"[7] 💳 <b>¡RECARGA EXITOSA!</b>\n\n[3] Se te agregaron <b>{cantidad} créditos</b>\n[4] 💰 Saldo actual: <b>{nuevo_saldo} créditos</b>",
            parse_mode="HTML"
        )
    except:
        pass

# ──────────────────────────────────────────────────────────────
# 📋 LISTAR PAÍSES
# ──────────────────────────────────────────────────────────────
async def paises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    saldo_actual = get_creditos(user_id)
    texto = f"[1] 🌍 <b>PAÍSES DISPONIBLES</b> | 💰 Saldo: <b>{saldo_actual}</b>\n\n"
    for clave, info in PAISES.items():
        texto += f"{info['nombre']} → <code>/comprar {clave} wa</code>\n"
    texto += "\n[2] 📱 <b>Servicios:</b>\n"
    for clave, info in SERVICIOS.items():
        texto += f"{info['nombre']} → <code>{clave}</code>\n"
    texto += f"\n[3] 💳 <b>Ver saldo:</b> /creditos"
    await update.message.reply_text(texto, parse_mode="HTML")

# ──────────────────────────────────────────────────────────────
# 🛒 COMPRAR NÚMERO
# ──────────────────────────────────────────────────────────────
async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text(
            "[1] ⚠️ <b>Uso:</b>\n<code>/comprar [país] [servicio] [cantidad]</code>\n\n"
            "Ejemplos:\n/comprar pe wa → Perú, WhatsApp\n/comprar mx tg 3 → México, Telegram\n\n"
            "[2] 💳 Usa /creditos para ver tu saldo",
            parse_mode="HTML"
        )
        return
    clave_pais = context.args[0].lower()
    clave_servicio = context.args[1].lower()
    cantidad = 1
    if len(context.args) >= 3:
        try:
            cantidad = max(1, min(20, int(context.args[2])))
        except:
            cantidad = 1
    if clave_pais not in PAISES:
        await update.message.reply_text(f"[9] ❌ País inválido: <code>{clave_pais}</code>", parse_mode="HTML")
        return
    if clave_servicio not in SERVICIOS:
        await update.message.reply_text(f"[9] ❌ Servicio inválido: <code>{clave_servicio}</code>", parse_mode="HTML")
        return
    saldo_actual = get_creditos(user_id)
    costo_total = cantidad * COSTO_POR_NUMERO
    if saldo_actual < costo_total:
        await update.message.reply_text(
            f"[9] ❌ <b>SALDO INSUFICIENTE</b>\n\n"
            f"[3] 💰 Tu saldo: <b>{saldo_actual} créditos</b>\n"
            f"[4] 💵 Costo requerido: <b>{costo_total} créditos</b> ({cantidad} x {COSTO_POR_NUMERO})\n"
            f"[5] 📉 Te faltan: <b>{costo_total - saldo_actual} créditos</b>\n\n"
            f"[6] 📞 Contacta al admin para recargar.",
            parse_mode="HTML"
        )
        return
    pais = PAISES[clave_pais]
    servicio = SERVICIOS[clave_servicio]
    mensaje = await update.message.reply_text(
        f"[2] 🔄 Comprando <b>{cantidad}</b> número(s) de {pais['nombre']} para {servicio['nombre']}...\n"
        f"[3] 💳 Costo: <b>{costo_total} créditos</b>",
        parse_mode="HTML"
    )
    resultados = []
    errores = []
    for i in range(cantidad):
        try:
            resp = requests.get(
                f"{BASE_URL}/buy/number",
                params={"country": pais["codigo"], "service": servicio["codigo"]},
                headers=headers,
                timeout=30
            )
            datos = resp.json()
            if datos.get("success") or datos.get("number"):
                numero = datos.get("number")
                id_solicitud = datos.get("id") or datos.get("request_id")
                resultados.append({"numero": numero, "id": id_solicitud, "pais": pais["nombre"], "servicio": servicio["nombre"]})
                if user_id not in numeros_activos:
                    numeros_activos[user_id] = []
                numeros_activos[user_id].append({"numero": numero, "id": id_solicitud, "pais": pais["nombre"], "servicio": servicio["nombre"]})
            else:
                errores.append(f"#{i+1}: {datos.get('message', 'Sin stock/saldo')}")
        except Exception as e:
            errores.append(f"#{i+1}: Error - {str(e)}")
    if resultados:
        descontar_creditos(user_id, len(resultados) * COSTO_POR_NUMERO)
    saldo_restante = get_creditos(user_id)
    texto = (
        "[7] ✅ <b>COMPRA COMPLETADA</b>\n"
        "🌍 País: {}\n"
        "📱 Servicio: {}\n"
        "📱 Comprados: <b>{}/{}</b>\n"
        "💳 Descontado: <b>{}</b> | Saldo: <b>{}</b>\n\n"
    ).format(pais["nombre"], servicio["nombre"], len(resultados), cantidad, len(resultados) * COSTO_POR_NUMERO, saldo_restante)
    if resultados:
        texto += "[8] <b>📋 NÚMEROS:</b>\n"
        for idx, item in enumerate(resultados, 1):
            texto += f"{idx}. 📱 <code>+{item['numero']}</code>\n 🆔 <code>{item['id']}</code>\n"
    if errores:
        texto += "\n[9] ❌ <b>Errores:</b>\n" + "\n".join(errores[:3])
        if len(errores) > 3:
            texto += f"\n... y {len(errores) - 3} más"
    await mensaje.edit_text(texto, parse_mode="HTML")

async def codigos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in numeros_activos or not numeros_activos[user_id]:
        await update.message.reply_text("[1] ❌ No tienes números guardados.", parse_mode="HTML")
        return
    mensaje = await update.message.reply_text("[2] 🔄 Consultando códigos... ⏳")
    texto = ("[3] 📋 <b>TUS NÚMEROS Y CÓDIGOS</b> — Total: {}\n\n").format(len(numeros_activos[user_id]))
    for idx, item in enumerate(numeros_activos[user_id], 1):
        codigo = await consultar_codigo(item["id"])
        if codigo:
            texto += f"[4] {idx}. 📱 <code>+{item['numero']}</code>\n🔐 <b>CÓDIGO:</b> <code>{codigo}</code>\n\n"
        else:
            texto += f"[5] {idx}. 📱 <code>+{item['numero']}</code>\n⏳ <b>Esperando código...</b>\n\n"
    await mensaje.edit_text(texto, parse_mode="HTML")

async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("[1] ⚠️ <b>Uso:</b> /verificar [ID]", parse_mode="HTML")
        return
    id_solicitud = context.args[0]
    codigo = await consultar_codigo(id_solicitud)
    if codigo:
        await update.message.reply_text(f"[2] ✅ <b>CÓDIGO:</b> <code>{codigo}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"[3] ⏳ Aún no llega el código para ID <code>{id_solicitud}</code>.", parse_mode="HTML")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in numeros_activos:
        cant = len(numeros_activos[user_id])
        del numeros_activos[user_id]
        await update.message.reply_text(f"[1] ✅ Borrados {cant} números.", parse_mode="HTML")
    else:
        await update.message.reply_text("[2] No tenías números guardados.", parse_mode="HTML")

async def consultar_codigo(id_solicitud):
    try:
        resp = requests.get(f"{BASE_URL}/sms/{id_solicitud}", headers=headers, timeout=30)
        datos = resp.json()
        return datos.get("sms") or datos.get("code") or None
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────
# 🚀 INICIAR BOT - FIX RENDER
# ──────────────────────────────────────────────────────────────
def main():
    # ⭐ ACTIVAR STICKERS/EMOJIS PREMIUM GLOBALES
    instalar_stickers_premium_globales()

    # FIX para Python 3.14 + Render: crear loop manualmente
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("paises", paises))
    application.add_handler(CommandHandler("comprar", comprar))
    application.add_handler(CommandHandler("codigos", codigos))
    application.add_handler(CommandHandler("verificar", verificar))
    application.add_handler(CommandHandler("limpiar", limpiar))
    application.add_handler(CommandHandler("creditos", creditos))
    application.add_handler(CommandHandler("saldo", saldo))
    application.add_handler(CommandHandler("miscreditos", creditos))
    application.add_handler(CommandHandler("addcreditos", agregar_creditos))
    application.add_handler(CommandHandler("addcredito", agregar_creditos))

    # 🛡️ ANTI-DORMIR AHORA COMO JOB, NO COMO THREAD (evita el crash)
    if application.job_queue:
        application.job_queue.run_repeating(anti_dormir_job, interval=240, first=10)

    print("==============================================")
    print("✅ BOT INICIADO")
    print("⭐ STICKERS/EMOJIS PREMIUM GLOBALES ACTIVADOS")
    print("💳 SISTEMA DE CRÉDITOS PREMIUM ACTIVADO")
    print("🛡️ ANTI-DORMIR ACTIVADO (JOB MODE)")
    print("==============================================")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
