import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes.DEFAULT_TYPE,
    CallbackQueryHandler
)
from flask import Flask, request, jsonify, render_template_string

load_dotenv()

# ─── CONFIGURACIÓN ───
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_URL = os.getenv("WEB_URL", "http://localhost:5000")
DB_PATH = "specter_peru.db"

# ─── DATOS DE PAGO ───
DATOS_PAGO = {
    "yape_numero": "987654321",
    "yape_titular": "SPECTER PERU",
    "plin_numero": "987654321",
    "banco_nombre": "BCP",
    "cci": "0021234567890987654321",
    "cci_titular": "SPECTER PERU",
    "qr_imagen_url": "https://i.imgur.com/TU_QR_YAPE.jpg",
    "qr_link_pago": "https://link.yape.pe/pago/specterperu"
}

# ─── PLANES ───
PLANES_CREDITOS = {
    "c100": {"nombre": "🥉 100 Créditos", "monto": 10.0, "creditos": 100},
    "c200": {"nombre": "🥈 200 Créditos", "monto": 20.0, "creditos": 200},
    "c400": {"nombre": "🥇 400 Créditos", "monto": 30.0, "creditos": 400},
    "c500": {"nombre": "💠 500 Créditos", "monto": 40.0, "creditos": 500},
    "c800": {"nombre": "🚀 800 Créditos", "monto": 50.0, "creditos": 800},
    "c2000": {"nombre": "👑 2,000 Créditos", "monto": 100.0, "creditos": 2000},
    "c4300": {"nombre": "💎 4,300 Créditos", "monto": 200.0, "creditos": 4300}
}

PLANES_ILIMITADOS = {
    "i7": {"nombre": "💥 7 Días", "monto": 20.0, "dias": 7},
    "i15": {"nombre": "⚡ 15 Días", "monto": 35.0, "dias": 15},
    "i30": {"nombre": "🔱 30 Días", "monto": 60.0, "dias": 30},
    "i60": {"nombre": "👑 60 Días", "monto": 100.0, "dias": 60}
}

# ─── INICIALIZAR BASE DE DATOS ───
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            user_id TEXT PRIMARY KEY,
            creditos INTEGER NOT NULL DEFAULT 0,
            celular TEXT DEFAULT "",
            estado_premio TEXT DEFAULT "",
            vencimiento_premio TEXT DEFAULT ""
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            tipo_plan TEXT NOT NULL,
            monto REAL NOT NULL,
            creditos INTEGER DEFAULT 0,
            dias INTEGER DEFAULT 0,
            comprobante TEXT DEFAULT "",
            estado TEXT DEFAULT "pendiente",
            fecha TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_creditos(user_id: str):
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT creditos FROM usuarios WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO usuarios (user_id, creditos, celular) VALUES (?, 0, '')", (user_id,))
            conn.commit()
            conn.close()
            return 0
        conn.close()
        return row[0]
    except Exception as e:
        print(f"Error get_creditos: {e}")
        return 0

def sumar_creditos(user_id: str, cantidad: int):
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT creditos FROM usuarios WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO usuarios (user_id, creditos, celular) VALUES (?, ?, '')", (user_id, cantidad))
        else:
            cur.execute("UPDATE usuarios SET creditos = creditos + ? WHERE user_id=?", (cantidad, user_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error sumar_creditos: {e}")
        return False

def registrar_transaccion(user_id: str, tipo_plan: str, monto: float, creditos: int=0, dias: int=0, comprobante: str=""):
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        cur = conn.cursor()
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO transacciones (user_id, tipo_plan, monto, creditos, dias, comprobante, estado, fecha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, tipo_plan, monto, creditos, dias, comprobante, "pendiente", fecha))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error registrar_transaccion: {e}")
        return False

# ─── SERVIDOR FLASK ───
app = Flask(__name__)

@app.route("/")
def index():
    with open("web_recarga.html", "r", encoding="utf-8") as f:
        return f.read()

@app.route("/api/confirmar_pago", methods=["POST"])
def confirmar_pago():
    datos = request.get_json()
    user_id = datos.get("user_id", "")
    plan_id = datos.get("plan_id", "")
    comprobante = datos.get("comprobante", "")

    if not user_id or not plan_id:
        return jsonify({"ok": False, "mensaje": "Faltan datos"}), 400

    plan = None
    if plan_id in PLANES_CREDITOS:
        plan = PLANES_CREDITOS[plan_id]
        registrar_transaccion(user_id, plan_id, plan["monto"], plan["creditos"], 0, comprobante)
    elif plan_id in PLANES_ILIMITADOS:
        plan = PLANES_ILIMITADOS[plan_id]
        registrar_transaccion(user_id, plan_id, plan["monto"], 0, plan["dias"], comprobante)
    else:
        return jsonify({"ok": False, "mensaje": "Plan no existe"}), 404

    return jsonify({
        "ok": True,
        "mensaje": "Pago registrado. Esperando confirmación automática...",
        "plan": plan
    })

# 📡 ENDPOINT PARA PANDAX — LEER NOTIFICACIÓN Y SUMAR CRÉDITOS
@app.route("/api/pandax_notificacion", methods=["POST"])
def pandax_notificacion():
    """
    Tu app PandaX envía aquí los datos de la notificación de Yape:
    {
        "numero_destino": "987654321",
        "monto": 10.0,
        "numero_origen": "999888777",
        "fecha": "2026-08-24 19:52:00"
    }
    """
    datos = request.get_json()
    monto = datos.get("monto", 0)
    numero_destino = datos.get("numero_destino", "")
    numero_origen = datos.get("numero_origen", "")

    # Validar que el pago es para nosotros
    if numero_destino != DATOS_PAGO["yape_numero"]:
        return jsonify({"ok": False, "mensaje": "Número destino no coincide"}), 400

    # Buscar el plan según el monto
    plan_encontrado = None
    tipo = ""
    for pid, p in PLANES_CREDITOS.items():
        if abs(p["monto"] - monto) < 0.01:
            plan_encontrado = p
            tipo = "creditos"
            break
    if not plan_encontrado:
        for pid, p in PLANES_ILIMITADOS.items():
            if abs(p["monto"] - monto) < 0.01:
                plan_encontrado = p
                tipo = "ilimitado"
                break

    if not plan_encontrado:
        return jsonify({"ok": False, "mensaje": f"No hay plan para S/ {monto}"}), 404

    # Buscar usuario por número de celular (debe estar registrado con /micelular)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM usuarios WHERE celular = ?", (numero_origen,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "mensaje": f"Usuario con celular {numero_origen} no registrado"}), 404

    user_id = row[0]

    # Sumar créditos o activar plan ilimitado
    if tipo == "creditos":
        sumar_creditos(user_id, plan_encontrado["creditos"])
        mensaje = f"✅ RECARGA AUTOMÁTICA: +{plan_encontrado['creditos']} CRÉDITOS"
    else:
        # Plan ilimitado - establecer fecha de vencimiento
        from datetime import datetime, timedelta
        fecha_vence = (datetime.now() + timedelta(days=plan_encontrado["dias"])).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE usuarios SET estado_premio = 'ACTIVO', vencimiento_premio = ? WHERE user_id = ?", (fecha_vence, user_id))
        conn.commit()
        mensaje = f"✅ PLAN ILIMITADO ACTIVADO: {plan_encontrado['dias']} DÍAS"

    # Actualizar estado de transacciones pendientes
    cur.execute("UPDATE transacciones SET estado = 'completado' WHERE user_id = ? AND monto = ? AND estado = 'pendiente'", (user_id, monto))
    conn.commit()
    conn.close()

    # Notificar al usuario por el bot
    async def notificar_usuario():
        try:
            await application.bot.send_message(
                chat_id=int(user_id),
                text=f"""
╔══════════════════════════════════╗
║   ✅ PAGO CONFIRMADO AUTOMÁTICAMENTE   ║
╚══════════════════════════════════╝

{mensaje}

💰 Monto recibido: S/ {monto}
📱 De: {numero_origen}
⚡ Activación: INSTANTÁNEA

Gracias por confiar en SPECTER PERÚ ⚜️
"""
            )
        except Exception as e:
            print(f"Error notificando usuario: {e}")

    import asyncio
    asyncio.run(notificar_usuario())

    return jsonify({
        "ok": True,
        "mensaje": "Créditos sumados automáticamente",
        "usuario": user_id,
        "plan": plan_encontrado
    })

# ─── COMANDOS DEL BOT ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    get_creditos(user_id)
    texto = """
╔══════════════════════════════════╗
║    ⚜️  SPECTER PERÚ — BOT  ⚜️    ║
╚══════════════════════════════════╝

🚀 PLATAFORMA DE CONSULTAS

📝 /register ➜ Registrar cuenta
📖 /cmds ➜ Ver servicios
👤 /me ➜ Ver perfil
💳 /buy ➜ Recargar créditos
🌐 /web ➜ Abrir web de recarga
📱 /micelular 9XXXXXXXXX ➜ Vincular número para recarga automática
🛡️ /staff ➜ Soporte
"""
    await update.message.reply_text(texto)

async def micelular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        return await update.message.reply_text(
            "📱 Uso: /micelular 987654321\n\nVincula tu número de Yape para que las recargas se sumen automáticamente ⚡"
        )
    celular = context.args[0].strip()
    if not celular.startswith("9") or len(celular) != 9:
        return await update.message.reply_text("❌ Número inválido. Debe empezar con 9 y tener 9 dígitos.")
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO usuarios (user_id, celular, creditos) VALUES (?, ?, COALESCE((SELECT creditos FROM usuarios WHERE user_id=?), 0))", (user_id, celular, user_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Número {celular} vinculado correctamente!\n\nAhora cuando pagues desde este número, los créditos se sumarán automáticamente ⚡")

async def web_recarga_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text(
        f"🌐 Abre la web para recargar:\n{WEB_URL}?user_id={user_id}\n\nSelecciona tu plan, paga con Yape y los créditos se sumarán solos ⚡",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ir a Recargar", url=f"{WEB_URL}?user_id={user_id}")]
        ])
    )

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    creditos = get_creditos(user_id)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT celular, estado_premio, vencimiento_premio FROM usuarios WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    celular = row[0] if row else "No registrado"
    estado = row[1] if row else "INACTIVO"
    vence = row[2] if row else ""
    conn.close()
    
    texto = f"""
╔══════════════════════════════════╗
║         👤 TU PERFIL              ║
╚══════════════════════════════════╝

🆔 ID: {user_id}
💰 Créditos: {creditos}
📱 Celular: {celular}
👑 Estado Premium: {estado}
📅 Vence: {vence if vence else "N/A"}
"""
    await update.message.reply_text(texto)

# ─── INICIAR TODO ───
init_db()
application = Application.builder().token(BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("micelular", micelular))
application.add_handler(CommandHandler("web", web_recarga_comando))
application.add_handler(CommandHandler("me", me))

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🚀 Bot + Web de Recarga Iniciados!")
    application.run_polling()
  
