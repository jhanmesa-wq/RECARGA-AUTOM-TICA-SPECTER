import requests
import json
import os
import re
import functools
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, Message, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ─────────── CONFIGURACIÓN ───────────
GRIZZLY_API_KEY = os.getenv("GRIZZLY_API_KEY", "PON_TU_CLAVE_GRIZZLY_AQUI")
BOT_TOKEN = os.getenv("BOT_TOKEN", "PON_TU_TOKEN_TELEGRAM_AQUI")
ADMIN_ID_ENV = os.getenv("ADMIN_ID", "")

GRIZZLY_BASE_URL = "https://api.grizzlysms.com/stubs/handler_api.php"

MAX_PRICE = os.getenv("GRIZZLY_MAX_PRICE", "")
MIN_PRICE = os.getenv("GRIZZLY_MIN_PRICE", "")
PROVIDER_IDS = os.getenv("GRIZZLY_PROVIDER_IDS", "")
EXCEPT_PROVIDER_IDS = os.getenv("GRIZZLY_EXCEPT_PROVIDER_IDS", "")
PHONE_EXCEPTION = os.getenv("GRIZZLY_PHONE_EXCEPTION", "")

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
    "any": {"nombre": "🌍 Auto (Mejor disponible)", "codigo": "any", "prefijo": ""},
}

SERVICIOS = {
    "wa": {"nombre": "WhatsApp", "codigo": "wa"},
    "tg": {"nombre": "Telegram", "codigo": "tg"},
    "fb": {"nombre": "Facebook", "codigo": "fb"},
    "ig": {"nombre": "Instagram", "codigo": "ig"},
    "gg": {"nombre": "Google", "codigo": "go"},
    "tk": {"nombre": "TikTok", "codigo": "tiktok"},
}

numeros_activos = {}

def keep_alive():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot alive - Premium V2 + Cancel Button")
        def log_message(self, *args): return
    port = int(os.environ.get("PORT", 10000))
    def run():
        try:
            httpd = HTTPServer(("0.0.0.0", port), Handler)
            print(f"🌐 Keep alive server en puerto {port}")
            httpd.serve_forever()
        except Exception as e:
            print(f"Keep alive error: {e}")
    threading.Thread(target=run, daemon=True).start()

# ⭐ PREMIUM STICKERS
PREMIUM_STICKERS = {
    "1": "5431650332419563627","2": "6219810752887262728","3": "6298670698948724690","4": "5098585844931888090",
    "5": "5260553279321944543","6": "5098578393163629920","7": "5429381339851796035","8": "5179570356695860413",
    "9": "5177431372788139022","10": "5098536693326152842","11": "5260463209562776385","12": "5096114086958072826",
}
def premium(texto: str) -> str:
    if texto is None: return texto
    texto = str(texto)
    def reemplazar(match):
        numero = match.group(1)
        custom_id = PREMIUM_STICKERS.get(numero)
        if not custom_id: return match.group(0)
        return f'<tg-emoji emoji-id="{custom_id}">🔹</tg-emoji>'
    texto = re.sub(r"\[(\d+)\]", reemplazar, texto)
    texto = re.sub(r"\[E(\d+)\]", reemplazar, texto)
    return texto

def _patch_premium_method(cls, method_name):
    original = getattr(cls, method_name, None)
    if original is None or getattr(original, "_premium_global", False): return
    @functools.wraps(original)
    async def wrapped(self, *args, **kwargs):
        changed=False
        for key in ("text","caption"):
            if key in kwargs and isinstance(kwargs[key], str):
                nuevo=premium(kwargs[key])
                if nuevo!=kwargs[key]: kwargs[key]=nuevo; changed=True
        if not changed and args:
            args=list(args)
            for i,v in enumerate(args):
                if isinstance(v,str) and "[" in v:
                    nuevo=premium(v)
                    if nuevo!=v: args[i]=nuevo; changed=True; break
            args=tuple(args)
        if changed and "parse_mode" not in kwargs: kwargs["parse_mode"]="HTML"
        return await original(self,*args,**kwargs)
    wrapped._premium_global=True
    setattr(cls,method_name,wrapped)

def instalar_stickers_premium_globales():
    metodos = ("send_message","reply_text","edit_message_text","edit_text","send_photo","reply_photo","send_video","reply_video",)
    for metodo in metodos:
        if hasattr(Message,metodo): _patch_premium_method(Message,metodo)
        if hasattr(Bot,metodo): _patch_premium_method(Bot,metodo)

def cargar_creditos():
    if not os.path.exists(ARCHIVO_CREDITOS):
        with open(ARCHIVO_CREDITOS,"w",encoding="utf-8") as f: json.dump({},f)
        return {}
    try:
        with open(ARCHIVO_CREDITOS,"r",encoding="utf-8") as f: return json.load(f)
    except: return {}
def guardar_creditos(data):
    with open(ARCHIVO_CREDITOS,"w",encoding="utf-8") as f: json.dump(data,f,indent=2)
def get_creditos(user_id:str)->int: return cargar_creditos().get(str(user_id),CREDITOS_INICIALES)
def add_creditos(user_id:str,cantidad:int)->int:
    db=cargar_creditos(); db[str(user_id)]=db.get(str(user_id),CREDITOS_INICIALES)+cantidad; guardar_creditos(db); return db[str(user_id)]
def descontar_creditos(user_id:str,cantidad:int)->bool:
    db=cargar_creditos(); actual=db.get(str(user_id),CREDITOS_INICIALES)
    if actual<cantidad: return False
    db[str(user_id)]=actual-cantidad; guardar_creditos(db); return True

# ============================================================
# 🔥 API V2
# ============================================================
def comprar_numero_grizzly(service_code, country_code):
    params = {"api_key": GRIZZLY_API_KEY, "action": "getNumberV2", "service": service_code, "country": country_code}
    if MAX_PRICE: params["maxPrice"]=MAX_PRICE
    if MIN_PRICE: params["minPrice"]=MIN_PRICE
    if PROVIDER_IDS: params["providerIds"]=PROVIDER_IDS
    if EXCEPT_PROVIDER_IDS: params["exceptProviderIds"]=EXCEPT_PROVIDER_IDS
    if PHONE_EXCEPTION: params["phoneException"]=PHONE_EXCEPTION
    try:
        resp=requests.get(GRIZZLY_BASE_URL, params=params, timeout=30)
        text=resp.text.strip()
        try:
            datos=resp.json()
            if isinstance(datos, dict) and "phoneNumber" in datos:
                return {"success":True,"data":datos}
            return {"success":False,"error":json.dumps(datos)}
        except:
            return {"success":False,"error":text}
    except Exception as e:
        return {"success":False,"error":f"EXCEPTION: {str(e)}"}

async def consultar_codigo(activation_id):
    params={"api_key":GRIZZLY_API_KEY,"action":"getStatus","id":activation_id}
    try:
        resp=requests.get(GRIZZLY_BASE_URL, params=params, timeout=20)
        text=resp.text.strip()
        if text.startswith("STATUS_OK:"):
            return text.split("STATUS_OK:")[1].strip()
        elif text in ["STATUS_WAIT_CODE","STATUS_WAIT_RETRY","STATUS_WAIT_RESEND"]:
            return None
        elif "STATUS_CANCEL" in text or "NO_ACTIVATION" in text:
            return "CANCELADO"
        else:
            return None if text.startswith("STATUS_") else text
    except: return None

async def cancelar_activacion(activation_id):
    # status 8 = cancelar, según docs
    params={"api_key":GRIZZLY_API_KEY,"action":"setStatus","id":activation_id,"status":"8"}
    try:
        resp=requests.get(GRIZZLY_BASE_URL, params=params, timeout=15)
        return resp.text.strip()
    except Exception as e:
        return f"Error: {e}"

# ============================================================
# 📱 COMANDOS + BOTONES
# ============================================================
async def creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saldo=get_creditos(str(update.effective_user.id))
    await update.message.reply_text(f"[3] 💰 Tu saldo: <b>{saldo}</b> créditos", parse_mode="HTML")

async def agregar_creditos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID_ENV and str(update.effective_user.id)!=ADMIN_ID_ENV:
        await update.message.reply_text("[9] ❌ No autorizado.", parse_mode="HTML"); return
    if len(context.args)<2:
        await update.message.reply_text("[1] Uso: /addcreditos [user_id] [cantidad]", parse_mode="HTML"); return
    try:
        nuevo=add_creditos(context.args[0], int(context.args[1]))
        await update.message.reply_text(f"[7] ✅ Nuevo saldo: {nuevo}", parse_mode="HTML")
    except Exception as e: await update.message.reply_text(f"Error: {e}", parse_mode="HTML")

async def paises(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saldo=get_creditos(str(update.effective_user.id))
    texto=f"[1] 🌍 <b>PAÍSES</b> | 💰 Saldo: <b>{saldo}</b>\n\n"
    for k,v in PAISES.items(): texto+=f"{v['nombre']} → <code>/comprar {k} wa</code>\n"
    texto+="\n[2] 📱 Servicios:\n"
    for k,v in SERVICIOS.items(): texto+=f"{v['nombre']} → <code>{k}</code>\n"
    await update.message.reply_text(texto, parse_mode="HTML")

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=str(update.effective_user.id)
    if len(context.args)<2:
        await update.message.reply_text("[1] ⚠️ <b>Uso:</b> <code>/comprar [país] [servicio] [cantidad]</code>\nEj: <code>/comprar pe wa</code>", parse_mode="HTML"); return
    clave_pais=context.args[0].lower(); clave_servicio=context.args[1].lower()
    cantidad=1
    if len(context.args)>=3:
        try: cantidad=max(1,min(20,int(context.args[2])))
        except: cantidad=1
    if clave_pais not in PAISES or clave_servicio not in SERVICIOS:
        await update.message.reply_text("[9] ❌ País o servicio inválido. /paises", parse_mode="HTML"); return
    if get_creditos(user_id) < cantidad*COSTO_POR_NUMERO:
        await update.message.reply_text(f"[9] ❌ Saldo insuficiente. Tienes {get_creditos(user_id)} y necesitas {cantidad}", parse_mode="HTML"); return

    pais=PAISES[clave_pais]; servicio=SERVICIOS[clave_servicio]
    mensaje=await update.message.reply_text(f"[2] 🔄 Comprando <b>{cantidad}</b> de {pais['nombre']} para {servicio['nombre']}...", parse_mode="HTML")

    resultados=[]; errores=[]
    for i in range(cantidad):
        res=comprar_numero_grizzly(servicio["codigo"], pais["codigo"])
        if res["success"]:
            d=res["data"]
            resultados.append({"numero":d.get("phoneNumber"),"id":d.get("activationId"),"cost":d.get("activationCost","?"),"end":d.get("activationEnd")})
            if user_id not in numeros_activos: numeros_activos[user_id]=[]
            numeros_activos[user_id].append({"numero":d.get("phoneNumber"),"id":d.get("activationId"),"pais":pais['nombre'],"servicio":servicio['nombre'],"cost":d.get("activationCost")})
        else:
            err=res["error"]
            mapa={"BAD_KEY":"API Key inválida","NO_BALANCE":"Sin saldo en Grizzly","NO_NUMBERS":"Sin stock","SERVICE_UNAVAILABLE_REGION":"Región bloqueada"}
            errores.append(f"#{i+1}: {mapa.get(err,err)}")
            if err in ["BAD_KEY","NO_BALANCE"]: break

    if resultados: descontar_creditos(user_id, len(resultados)*COSTO_POR_NUMERO)
    saldo_rest=get_creditos(user_id)
    texto=f"[7] ✅ <b>COMPRA V2</b> | 🌍 {pais['nombre']} | 📱 {servicio['nombre']}\n📱 {len(resultados)}/{cantidad} | 💳 Saldo: <b>{saldo_rest}</b>\n\n"
    
    # Botones para cada número comprado
    keyboard=[]
    if resultados:
        texto+="[8] <b>📋 NÚMEROS:</b>\n"
        for idx,item in enumerate(resultados,1):
            texto+=f"{idx}. 📱 <code>+{item['numero']}</code>\n 🆔 <code>{item['id']}</code> 💵 ${item['cost']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Cancelar +{item['numero']}", callback_data=f"cancel_{item['id']}"), InlineKeyboardButton(f"🔍 Código {idx}", callback_data=f"check_{item['id']}")])
        texto+=f"\n[2] /codigos para ver todos"
    
    if errores: texto+="\n[9] ❌ Errores:\n"+"\n".join(errores[:5])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await mensaje.edit_text(texto, parse_mode="HTML", reply_markup=reply_markup)

async def codigos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=str(update.effective_user.id)
    if user_id not in numeros_activos or not numeros_activos[user_id]:
        await update.message.reply_text("[1] ❌ No tienes números. /comprar", parse_mode="HTML"); return
    
    texto=f"[3] 📋 <b>TUS NÚMEROS V2</b> — {len(numeros_activos[user_id])}\n\n"
    keyboard=[]
    for idx,item in enumerate(numeros_activos[user_id],1):
        codigo=await consultar_codigo(item["id"])
        if codigo and codigo!="CANCELADO":
            texto+=f"[4] {idx}. 📱 <code>+{item['numero']}</code>\n🔐 <b>{codigo}</b> | 🆔 {item['id']}\n\n"
            keyboard.append([InlineKeyboardButton(f"❌ Cancelar +{item['numero']}", callback_data=f"cancel_{item['id']}")])
        elif codigo=="CANCELADO":
            texto+=f"[9] {idx}. 📱 <code>+{item['numero']}</code> ❌ Cancelado\n\n"
        else:
            texto+=f"[5] {idx}. 📱 <code>+{item['numero']}</code> ⏳ Esperando... /verificar {item['id']}\n\n"
            keyboard.append([
                InlineKeyboardButton(f"🔄 Ver código", callback_data=f"check_{item['id']}"),
                InlineKeyboardButton(f"❌ Cancelar", callback_data=f"cancel_{item['id']}")
            ])
    
    await update.message.reply_text(texto, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("[1] Uso: /verificar [activationId]", parse_mode="HTML"); return
    codigo=await consultar_codigo(context.args[0])
    if codigo and codigo!="CANCELADO":
        await update.message.reply_text(f"[2] ✅ <b>CÓDIGO:</b> <code>{codigo}</code>", parse_mode="HTML")
    elif codigo=="CANCELADO":
        await update.message.reply_text(f"[9] ❌ Cancelada {context.args[0]}", parse_mode="HTML")
    else:
        await update.message.reply_text(f"[3] ⏳ Aún no llega.", parse_mode="HTML")

async def cancelar_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("[1] Uso: /cancelar [activationId]\nTambién puedes usar el botón ❌", parse_mode="HTML"); return
    activation_id=context.args[0]
    resp=await cancelar_activacion(activation_id)
    user_id=str(update.effective_user.id)
    if user_id in numeros_activos:
        numeros_activos[user_id]=[x for x in numeros_activos[user_id] if str(x["id"])!=str(activation_id)]
    await update.message.reply_text(f"[9] ❌ Cancelado {activation_id}\nGrizzly: {resp}", parse_mode="HTML")

async def limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id=str(update.effective_user.id)
    if user_id in numeros_activos:
        cant=len(numeros_activos[user_id]); del numeros_activos[user_id]
        await update.message.reply_text(f"[1] ✅ Borrados {cant}.", parse_mode="HTML")
    else: await update.message.reply_text("[2] Vacío.", parse_mode="HTML")

# 🔘 MANEJO DE BOTONES
async def botones_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    data=query.data
    user_id=str(query.from_user.id)

    if data.startswith("cancel_"):
        activation_id=data.split("cancel_")[1]
        resp=await cancelar_activacion(activation_id)
        if user_id in numeros_activos:
            numeros_activos[user_id]=[x for x in numeros_activos[user_id] if str(x["id"])!=str(activation_id)]
        
        if "ACCESS_CANCEL" in resp or "STATUS_CANCEL" in resp or resp=="":
            texto=f"[7] ✅ <b>CANCELADO</b>\n🆔 <code>{activation_id}</code>\n💰 Saldo devuelto en GrizzlySMS"
        else:
            texto=f"[9] ❌ Intento de cancelar {activation_id}\nRespuesta: {resp}\nSi ya recibió SMS no se puede cancelar."
        
        # Edita el mensaje o manda nuevo
        try:
            await query.edit_message_text(texto, parse_mode="HTML")
        except:
            await query.message.reply_text(texto, parse_mode="HTML")

    elif data.startswith("check_"):
        activation_id=data.split("check_")[1]
        codigo=await consultar_codigo(activation_id)
        if codigo and codigo!="CANCELADO":
            await query.message.reply_text(f"[2] ✅ <b>CÓDIGO de {activation_id}:</b> <code>{codigo}</code>", parse_mode="HTML")
        elif codigo=="CANCELADO":
            await query.message.reply_text(f"[9] ❌ {activation_id} está cancelado", parse_mode="HTML")
        else:
            await query.answer("⏳ Aún no llega el SMS, espera...", show_alert=True)

def main():
    instalar_stickers_premium_globales()
    keep_alive()
    application=Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("paises",paises))
    application.add_handler(CommandHandler("comprar",comprar))
    application.add_handler(CommandHandler("codigos",codigos))
    application.add_handler(CommandHandler("verificar",verificar))
    application.add_handler(CommandHandler("cancelar",cancelar_comando))
    application.add_handler(CommandHandler("limpiar",limpiar))
    application.add_handler(CommandHandler("creditos",creditos))
    application.add_handler(CommandHandler("saldo",creditos))
    application.add_handler(CommandHandler("addcreditos",agregar_creditos))
    application.add_handler(CallbackQueryHandler(botones_callback))

    print("==============================================")
    print("✅ BOT V2 + BOTON CANCELAR ACTIVO")
    print("==============================================")
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
