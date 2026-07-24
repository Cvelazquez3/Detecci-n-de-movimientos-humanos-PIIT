import os
import sys
import re
import time
import math
import random
import json
import queue
import threading
import asyncio
import webbrowser
import io
from collections import deque
import pandas as pd
import numpy as np
from flask import Flask, Response, render_template, jsonify, request, send_file

# SensorTag GATT UUIDs
MOV_DATA = "f000aa81-0451-4000-b000-000000000000"
MOV_CONF = "f000aa82-0451-4000-b000-000000000000"
MOV_PERI = "f000aa83-0451-4000-b000-000000000000"

# ---------------------------------------------------------------------------
# Frecuencias de muestreo soportadas por la interfaz
# ---------------------------------------------------------------------------
# El registro MOV_PERI del CC2650 SensorTag tiene, segun la documentacion
# oficial de TI, un rango DOCUMENTADO de periodo de 100ms (0x0A) a 2.55s
# (0xFF), con resolucion de 10ms. Es decir: 10Hz es la frecuencia MAXIMA
# soportada por el firmware de fabrica. Pedir 50Hz (periodo de 20ms) esta
# fuera de ese rango: el firmware puede ignorarlo y quedarse en 10Hz. Por
# eso el sistema SIEMPRE mide la frecuencia real lograda a partir de los
# timestamps de los paquetes BLE recibidos, y la expone en /api/status
# como "sample_rate_actual_hz" para que la interfaz pueda avisar si la
# Fs solicitada no fue honrada por el hardware.
SAMPLE_RATES = {
    10: 0x0A,  # 100ms -> dentro del rango documentado por TI
    50: 0x02,  #  20ms -> fuera del rango documentado por TI
}
DEFAULT_FREQ_HZ = 10
FS_TOLERANCE_HZ = 1.0

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder="templates", static_folder="static")

# Threading locks and queues
client_queues = []
client_queues_lock = threading.Lock()
recording_lock = threading.Lock()

class RecordingState:
    def __init__(self):
        self.is_recording = False
        self.recorded_data = []
        self.filename = ""
        self.start_time = 0
        self.freq_hz = DEFAULT_FREQ_HZ  # Fs de la fuente activa al iniciar la grabacion

state = RecordingState()

# BLE SensorTag Client Class
from bleak import BleakClient, BleakScanner

class BLEManager:
    def __init__(self):
        self.client = None
        self.status = "disconnected"  # "disconnected", "scanning", "connecting", "connected", "error"
        self.error = None 
        self.loop = None
        self.thread = None
        self.freq_hz = DEFAULT_FREQ_HZ          # Fs solicitada al SensorTag
        self._ts_window = deque(maxlen=100)     # timestamps recientes, para medir la Fs real
        self.actual_hz = None                   # Fs real medida a partir de los timestamps BLE
        self.freq_warning = None                # aviso si la Fs real no coincide con la solicitada

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def connect(self, freq_hz=DEFAULT_FREQ_HZ):
        if self.status in ["scanning", "connecting", "connected"]:
            return
        if freq_hz not in SAMPLE_RATES:
            freq_hz = DEFAULT_FREQ_HZ
        self.freq_hz = freq_hz
        self.actual_hz = None
        self.freq_warning = None
        self._ts_window.clear()
        self.status = "scanning"
        self.error = None
        asyncio.run_coroutine_threadsafe(self._connect_coro(), self.loop)

    def disconnect(self):
        if self.status == "disconnected":
            return
        asyncio.run_coroutine_threadsafe(self._disconnect_coro(), self.loop)

    async def _connect_coro(self):
        try:
            print("[BLE] Escaneando dispositivos en busca de SensorTag...")
            detected = await BleakScanner.discover(timeout=4.0)
            target = None
            for d in detected:
                if d.name and "SensorTag" in d.name:
                    target = d
                    break
            if not target:
                self.status = "error"
                self.error = "No se encontro el SensorTag en el escaneo BLE. Asegurate de que este encendido."
                print("[BLE] Error:", self.error)
                return

            self.status = "connecting"
            print(f"[BLE] Conectando a {target.name} ({target.address})...")
            self.client = BleakClient(target)
            await self.client.connect()

            # Configurar periodo de muestreo segun la Fs solicitada
            period_byte = SAMPLE_RATES[self.freq_hz]
            print(f"[BLE] Solicitando Fs = {self.freq_hz}Hz (periodo = {period_byte * 10}ms)")
            if self.freq_hz not in (10,):
                print(f"[BLE] AVISO: {self.freq_hz}Hz esta fuera del rango de periodo documentado por TI "
                      f"(100ms-2.55s). El SensorTag puede ignorarlo y quedarse en 10Hz. Se medira la Fs real.")
            await self.client.write_gatt_char(MOV_PERI, bytearray([period_byte]))
            # Habilitar giroscopio (ejes X, Y, Z) y acelerometro (ejes X, Y, Z) -> 0x3F (binario 00111111)
            await self.client.write_gatt_char(MOV_CONF, bytearray([0x3F, 0x00]))
            await asyncio.sleep(1.0)

            await self.client.start_notify(MOV_DATA, self._sensor_callback)
            self.status = "connected"
            print("[BLE] Conectado y recibiendo datos.")

        except Exception as e:
            self.status = "error"
            self.error = str(e)
            print(f"[BLE] Error en conexion: {e}")
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
            self.status = "error"

    async def _disconnect_coro(self):
        try:
            if self.client:
                if self.client.is_connected:
                    await self.client.stop_notify(MOV_DATA)
                    await self.client.disconnect()
            self.status = "disconnected"
            print("[BLE] Desconectado exitosamente.")
        except Exception as e:
            self.status = "error"
            self.error = str(e)
            print(f"[BLE] Error al desconectar: {e}")

    def _sensor_callback(self, sender, raw):
        if len(raw) < 12:
            return

        # Giroscopio en rad/s (conversion de datos crudos compatible con MobiFall)
        gx = int.from_bytes(raw[0:2], "little", signed=True) * 0.00875 / 57.2958
        gy = int.from_bytes(raw[2:4], "little", signed=True) * 0.00875 / 57.2958
        gz = int.from_bytes(raw[4:6], "little", signed=True) * 0.00875 / 57.2958

        # Acelerometro en g
        ax = int.from_bytes(raw[6:8],  "little", signed=True) / 16384.0
        ay = int.from_bytes(raw[8:10], "little", signed=True) / 16384.0
        az = int.from_bytes(raw[10:12],"little", signed=True) / 16384.0

        ts_now = time.time()

        # Medir la Fs REAL a partir de los timestamps de llegada (no confiar
        # ciegamente en el valor escrito en MOV_PERI; el firmware puede
        # ignorarlo, ver nota al inicio del archivo).
        self._ts_window.append(ts_now)
        if len(self._ts_window) >= 10:
            span = self._ts_window[-1] - self._ts_window[0]
            if span > 0:
                self.actual_hz = (len(self._ts_window) - 1) / span
                if abs(self.actual_hz - self.freq_hz) > FS_TOLERANCE_HZ:
                    self.freq_warning = (
                        f"Fs solicitada {self.freq_hz}Hz, pero se esta midiendo "
                        f"{self.actual_hz:.1f}Hz real (el SensorTag pudo haber "
                        f"ignorado la configuracion)."
                    )
                else:
                    self.freq_warning = None

        payload = {
            'timestamp': ts_now,
            'acc_x': ax, 'acc_y': ay, 'acc_z': az,
            'gyr_x': gx, 'gyr_y': gy, 'gyr_z': gz
        }
        _agregar_campos_calibrados(payload)

        # Guardar en grabacion
        with recording_lock:
            if state.is_recording:
                state.recorded_data.append(payload)

        # Enviar a todos los clientes SSE conectados
        with client_queues_lock:
            for q in client_queues:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass

ble_manager = BLEManager()

def _agregar_campos_calibrados(payload):
    """
    Si hay una calibracion activa (calculada en la pestaña Calibracion), calcula
    la aceleracion calibrada (m/s^2). Si el usuario activo 'aplicar calibracion
    en vivo', agrega campos EXTRA (acc_x_cal, acc_y_cal, acc_z_cal) al payload
    sin tocar los originales (acc_x, acc_y, acc_z, que siguen en g). Asi la
    vista en vivo "cruda" no cambia de comportamiento a menos que el usuario
    lo pida.

    Si ademas hay una nivelacion de montaje activa (matriz R, ver seccion 1
    del documento de nivelacion / formula de Rodrigues) y el usuario activo
    'aplicar nivelacion en vivo', agrega tambien los campos en el marco del
    cuerpo (acc_x_body/y/z en m/s^2, gyr_x_body/y/z en rad/s): R se aplica
    por igual al acelerometro ya calibrado y al giroscopio crudo (el bias del
    giroscopio aun no esta integrado en la interfaz web, ver PENDIENTES).
    """
    if calibracion_activa is None:
        return
    acc_g = np.array([payload['acc_x'], payload['acc_y'], payload['acc_z']])
    C = calibracion_activa["C"]
    b_a = calibracion_activa["b_a"]
    acc_cal_ms2 = C @ acc_g + b_a

    if aplicar_calibracion_en_vivo:
        payload['acc_x_cal'], payload['acc_y_cal'], payload['acc_z_cal'] = acc_cal_ms2.tolist()

    if aplicar_nivelacion_en_vivo and nivelacion_activa is not None:
        R = nivelacion_activa["R"]
        acc_body = R @ acc_cal_ms2
        gyr_raw = np.array([payload['gyr_x'], payload['gyr_y'], payload['gyr_z']])
        gyr_body = R @ gyr_raw
        payload['acc_x_body'], payload['acc_y_body'], payload['acc_z_body'] = acc_body.tolist()
        payload['gyr_x_body'], payload['gyr_y_body'], payload['gyr_z_body'] = gyr_body.tolist()

# Simulador de SensorTag
simulating = False
sim_thread = None
sim_freq_hz = DEFAULT_FREQ_HZ

def simulate_data_generator(freq_hz=DEFAULT_FREQ_HZ):
    global simulating
    dt = 1.0 / freq_hz
    print(f"[SIM] Iniciando generador de datos simulados a {freq_hz}Hz...")
    t = 0
    while simulating:
        time.sleep(dt)
        t += dt
        
        # Simular rotacion de balanceo y cabeceo
        pitch = 0.4 * math.sin(t * 0.5)
        roll = 0.25 * math.cos(t * 0.8)
        
        # Aceleraciones: Gravedad (1.0g) + ruido
        ax = -math.sin(pitch) + random.uniform(-0.015, 0.015)
        ay = math.sin(roll) * math.cos(pitch) + random.uniform(-0.015, 0.015)
        az = math.cos(roll) * math.cos(pitch) + random.uniform(-0.015, 0.015)
        
        # Velocidades angulares: Derivadas de los angulos + un sesgo (bias/drift)
        # Esto sirve para demostrar la deriva en el giroscopio.
        bias_x = 0.035  # rad/s (~2 deg/s)
        bias_y = -0.020 # rad/s
        bias_z = 0.015  # rad/s
        
        gx = -0.4 * 0.5 * math.cos(t * 0.5) + bias_x + random.uniform(-0.005, 0.005)
        gy = -0.25 * 0.8 * math.sin(t * 0.8) + bias_y + random.uniform(-0.005, 0.005)
        gz = 0.05 * math.sin(t * 0.2) + bias_z + random.uniform(-0.005, 0.005)
        
        payload = {
            'timestamp': time.time(),
            'acc_x': ax, 'acc_y': ay, 'acc_z': az,
            'gyr_x': gx, 'gyr_y': gy, 'gyr_z': gz
        }
        _agregar_campos_calibrados(payload)

        with recording_lock:
            if state.is_recording:
                state.recorded_data.append(payload)
                
        with client_queues_lock:
            for q in client_queues:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass
    print("[SIM] Generador de datos simulados detenido.")

# Rutas Flask
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/api/status')
def get_status():
    global simulating, sim_freq_hz
    return jsonify({
        "ble_status": ble_manager.status,
        "ble_error": ble_manager.error,
        "is_simulating": simulating,
        "is_recording": state.is_recording,
        "recorded_samples": len(state.recorded_data) if state.is_recording else 0,
        "recording_filename": state.filename,
        # Frecuencia de muestreo: la que se solicito y la que realmente se
        # esta midiendo a partir de los timestamps (pueden diferir si el
        # SensorTag no honra el periodo pedido; ver notas al inicio del archivo)
        "sample_rate_target_hz": ble_manager.freq_hz if ble_manager.status == "connected" else (sim_freq_hz if simulating else None),
        "sample_rate_actual_hz": round(ble_manager.actual_hz, 2) if (ble_manager.status == "connected" and ble_manager.actual_hz) else (sim_freq_hz if simulating else None),
        "sample_rate_warning": ble_manager.freq_warning if ble_manager.status == "connected" else None,
        "supported_frequencies": sorted(SAMPLE_RATES.keys())
    })

@app.route('/api/csv_files')
def get_csv_files():
    files = [f for f in os.listdir(WORKSPACE_DIR) if f.endswith('.csv')]
    # Ordenar archivos
    files.sort()
    return jsonify(files)

@app.route('/api/csv_data/<filename>')
def get_csv_data(filename):
    # Validar que el archivo sea un CSV seguro
    if not filename.endswith('.csv') or '..' in filename:
        return jsonify({"error": "Nombre de archivo invalido"}), 400
    
    filepath = os.path.join(WORKSPACE_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Archivo no encontrado"}), 404
    
    try:
        df = pd.read_csv(filepath)
        # Validar columnas
        req_cols = ['acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']
        for col in req_cols:
            if col not in df.columns:
                return jsonify({"error": f"El archivo no tiene la columna requerida: {col}"}), 400

        # Rellenar timestamp si no existe. Los CSV crudos no guardan la Fs
        # con la que se capturaron, asi que se recibe por query param
        # (?fs=10 o ?fs=50); si no se especifica, se asume 10Hz por
        # compatibilidad con archivos antiguos.
        if 'timestamp' not in df.columns:
            fs = request.args.get('fs', default=DEFAULT_FREQ_HZ, type=float)
            if fs <= 0:
                fs = DEFAULT_FREQ_HZ
            df['timestamp'] = [i / fs for i in range(len(df))]

        data = df[['timestamp', 'acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']].to_dict(orient='records')
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/connect', methods=['POST'])
def connect_ble():
    global simulating
    if simulating:
        stop_simulation()
    req = request.get_json(silent=True) or {}
    freq_hz = int(req.get("freq", DEFAULT_FREQ_HZ))
    if freq_hz not in SAMPLE_RATES:
        return jsonify({"error": f"Frecuencia no soportada: {freq_hz}Hz. Opciones: {sorted(SAMPLE_RATES.keys())}"}), 400
    ble_manager.connect(freq_hz=freq_hz)
    return jsonify({"status": "connecting", "freq": freq_hz})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_ble():
    ble_manager.disconnect()
    return jsonify({"status": "disconnecting"})

@app.route('/api/start_simulation', methods=['POST'])
def start_simulation_endpoint():
    global simulating, sim_thread, sim_freq_hz
    if ble_manager.status == "connected":
        ble_manager.disconnect()

    req = request.get_json(silent=True) or {}
    freq_hz = int(req.get("freq", DEFAULT_FREQ_HZ))
    if freq_hz not in SAMPLE_RATES:
        return jsonify({"error": f"Frecuencia no soportada: {freq_hz}Hz. Opciones: {sorted(SAMPLE_RATES.keys())}"}), 400

    if not simulating:
        sim_freq_hz = freq_hz
        simulating = True
        sim_thread = threading.Thread(target=simulate_data_generator, args=(freq_hz,), daemon=True)
        sim_thread.start()
    return jsonify({"status": "simulating", "freq": freq_hz})

@app.route('/api/stop_simulation', methods=['POST'])
def stop_simulation_endpoint():
    stop_simulation()
    return jsonify({"status": "stopped"})

def stop_simulation():
    global simulating
    simulating = False

@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    global simulating, sim_freq_hz
    req = request.json or {}
    filename = req.get("filename", "Prueba.csv")
    if not filename.endswith(".csv"):
        filename += ".csv"

    # La Fs de la grabacion es la de la fuente activa en este momento
    if ble_manager.status == "connected":
        freq_hz = ble_manager.freq_hz
    elif simulating:
        freq_hz = sim_freq_hz
    else:
        freq_hz = DEFAULT_FREQ_HZ

    with recording_lock:
        state.is_recording = True
        state.recorded_data = []
        state.filename = filename
        state.start_time = time.time()
        state.freq_hz = freq_hz

    print(f"[REC] Grabando datos en {filename} (Fs objetivo: {freq_hz}Hz)...")
    return jsonify({"status": "recording", "filename": filename, "freq": freq_hz})

@app.route('/api/stop_recording', methods=['POST'])
def stop_recording():
    with recording_lock:
        if not state.is_recording:
            return jsonify({"error": "No hay ninguna grabacion activa"}), 400
        
        state.is_recording = False
        if not state.recorded_data:
            return jsonify({"status": "stopped", "samples": 0, "error": "No se capturaron muestras."})
        
        df = pd.DataFrame(state.recorded_data)
        # Alinear timestamps respecto al inicio
        t0 = df['timestamp'].iloc[0]
        df['timestamp'] = df['timestamp'] - t0

        filepath = os.path.join(WORKSPACE_DIR, state.filename)
        # Guardar columnas correspondientes a datos crudos
        columnas = ['acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']
        df[columnas].to_csv(filepath, index=False)

        samples = len(df)
        duration = df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]
        fs_real = round((samples - 1) / duration, 2) if duration > 0 else None
        freq_hz = state.freq_hz
        filename = state.filename
        state.recorded_data = []
        state.filename = ""

    print(f"[REC] Grabacion completada. Guardado en {filepath} ({samples} muestras, {duration:.1f}s, "
          f"Fs objetivo: {freq_hz}Hz, Fs real: {fs_real}Hz)")
    return jsonify({
        "status": "saved",
        "filename": filename,
        "samples": samples,
        "duration": duration,
        "sample_rate_target_hz": freq_hz,
        "sample_rate_actual_hz": fs_real
    })
@app.route('/api/download_excel/<path:filename>')
def download_excel(filename):
    """Convierte un CSV grabado a Excel con columnas organizadas por eje."""
    if not filename.endswith('.csv') or '..' in filename:
        return jsonify({"error": "Nombre de archivo invalido"}), 400

    filepath = os.path.join(WORKSPACE_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Archivo no encontrado"}), 404

    try:
        df = pd.read_csv(filepath)

        # Reconstruir timestamp si no existe (misma logica que /api/csv_data,
        # Fs indicada por query param ?fs=, default 10Hz por compatibilidad)
        if 'timestamp' not in df.columns:
            fs = request.args.get('fs', default=DEFAULT_FREQ_HZ, type=float)
            if fs <= 0:
                fs = DEFAULT_FREQ_HZ
            df.insert(0, 'Tiempo (s)', [round(i / fs, 3) for i in range(len(df))])
        else:
            df.insert(0, 'Tiempo (s)', df['timestamp'].round(3))

        # Organizar columnas por eje
        col_map = {
            'acc_x':  'Acc X (g)',
            'acc_y':  'Acc Y (g)',
            'acc_z':  'Acc Z (g)',
            'gyr_x':  'Gyr α (rad/s)',
            'gyr_y':  'Gyr β (rad/s)',
            'gyr_z':  'Gyr γ (rad/s)',
        }
        columnas_export = ['Tiempo (s)']
        for src, dst in col_map.items():
            if src in df.columns:
                df[dst] = df[src].round(6)
                columnas_export.append(dst)

        df_export = df[columnas_export]

        # Generar Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='IMU Data')

            ws = writer.sheets['IMU Data']

            # Anchos de columna
            col_widths = {'Tiempo (s)': 12, 'Acc X (g)': 14, 'Acc Y (g)': 14, 'Acc Z (g)': 14,
                          'Gyr α (rad/s)': 16, 'Gyr β (rad/s)': 16, 'Gyr γ (rad/s)': 16}
            for i, col_name in enumerate(columnas_export, 1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = col_widths.get(col_name, 14)

        output.seek(0)
        excel_filename = filename.replace('.csv', '.xlsx')
        return send_file(
            output,
            as_attachment=True,
            download_name=excel_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Calibracion del acelerometro (ver calibracion_MPU_CC2650.pdf y
# calculo_promedios.py). El usuario sube la CARPETA con los 6 CSV crudos
# (uno por posicion estatica +X,-X,+Y,-Y,+Z,-Z) y aqui se reproduce el MISMO
# algoritmo de calculo_promedios.py: promedio por archivo (descartando el
# transitorio), matriz homogenea M (4x6), pseudoinversa, y Theta = G @ pinv(M).
#
# Diferencia respecto al script original: en vez de asumir el orden de los
# archivos que da glob.glob() (orden alfabetico del sistema de archivos, que
# podria desalinear una posicion con la columna equivocada de G), aqui se
# detecta la posicion (eje + signo) a partir del NOMBRE de cada archivo. Si
# algun archivo es ambiguo (no se pudo determinar eje o signo) o faltan/sobran
# posiciones, se devuelve un error explicito en vez de adivinar en silencio.
#
# Las lecturas crudas del sensor ya vienen en g (ver grabar_sensortag.py /
# _sensor_callback: raw/16384). Para que la calibracion resultante (C, b_a)
# convierta directamente a m/s^2 en vez de g, el valor "ideal" de la gravedad
# usado al armar G es 9.81 (no 1.0) — el resto del algebra es identica.
# ---------------------------------------------------------------------------
CALIB_ORDEN_POSICIONES = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
CALIB_N_DESCARTE_SEGUNDOS = 2  # mismo criterio que calculo_promedios.py (fila 22 en Excel = indice 20)
GRAVEDAD_MS2 = 9.81

# Matriz de valores ideales G (3x6). Antes se usaba +-1 (g); ahora +-9.81
# (m/s^2) para que C y b_a salgan directamente en m/s^2.
CALIB_G = np.array([
    [1, -1, 0, 0, 0, 0],
    [0, 0, 1, -1, 0, 0],
    [0, 0, 0, 0, 1, -1],
], dtype=float) * GRAVEDAD_MS2

# Calibracion actualmente cargada (None si aun no se ha procesado ninguna)
calibracion_activa = None          # {"C": np.array(3x3), "b_a": np.array(3,), "fs_hz": float}
aplicar_calibracion_en_vivo = False  # si True, el stream SSE agrega acc_x_cal, etc.

# La calibracion se guarda en disco para no tener que volver a subir los 6
# CSV cada vez: C y b_a son constantes fijas una vez calculadas; lo unico
# que cambia en tiempo real son las lecturas crudas que se le aplican.
CALIB_JSON_PATH = os.path.join(WORKSPACE_DIR, "calibracion.json")


def _guardar_calibracion_en_disco(C, b_a, fs_hz):
    with open(CALIB_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "C": C.tolist(),
            "b_a": b_a.tolist(),
            "fs_hz": fs_hz,
            "unidad": "m/s^2",
        }, f, indent=2, ensure_ascii=False)


def _cargar_calibracion_de_disco():
    if not os.path.exists(CALIB_JSON_PATH):
        return None
    try:
        with open(CALIB_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "C": np.array(data["C"]),
            "b_a": np.array(data["b_a"]),
            "fs_hz": data.get("fs_hz"),
        }
    except Exception as e:
        print(f"[CALIB] No se pudo cargar {CALIB_JSON_PATH}: {e}")
        return None


# Cargar automaticamente al iniciar el servidor, si ya existe una calibracion
# guardada de una sesion anterior
calibracion_activa = _cargar_calibracion_de_disco()
if calibracion_activa is not None:
    print(f"[CALIB] Calibracion previa cargada desde {CALIB_JSON_PATH} "
          f"(C diagonal ~ {calibracion_activa['C'][0][0]:.3f}, {calibracion_activa['C'][1][1]:.3f}, {calibracion_activa['C'][2][2]:.3f})")


def _detectar_posicion(nombre_archivo):
    """
    Intenta determinar a que posicion (+X,-X,+Y,-Y,+Z,-Z) corresponde un
    archivo a partir de su nombre. Devuelve la posicion (str) o None si es
    ambiguo. Reglas:
      - Eje: la primera letra X/Y/Z que no esta pegada a OTRA letra a su
        izquierda, y a su derecha o bien tampoco hay letra (ej. "eje X +",
        "eje_x") o bien le sigue "up"/"down" (ej. "Xup.csv", "Xdown.csv").
      - Signo: '-' o 'down' o 'abajo' -> negativo; '+' o 'up' o 'arriba' ->
        positivo. Se busca en todo el nombre (case-insensitive).
    """
    base = os.path.splitext(nombre_archivo)[0]
    base_lower = base.lower()

    eje = None
    for m in re.finditer(r'(?<![A-Za-z])([XYZxyz])', base):
        siguiente = base[m.end():m.end() + 4].lower()
        if not siguiente[:1].isalpha() or siguiente.startswith('up') or siguiente.startswith('down'):
            eje = m.group(1).upper()
            break
    if eje is None:
        return None

    tiene_negativo = ('-' in base) or ('down' in base_lower) or ('abajo' in base_lower)
    tiene_positivo = ('+' in base) or ('up' in base_lower) or ('arriba' in base_lower)

    if tiene_negativo and not tiene_positivo:
        signo = '-'
    elif tiene_positivo and not tiene_negativo:
        signo = '+'
    else:
        return None  # ambiguo: tiene ambos indicios o ninguno

    return f"{signo}{eje}"


@app.route('/api/calibracion/procesar', methods=['POST'])
def calibracion_procesar():
    """
    Espera un form-data con:
      - los archivos de la carpeta bajo la clave 'archivos' (multiples,
        input con webkitdirectory en el frontend)
      - campo opcional 'fs' (Hz) con la frecuencia de muestreo de las
        capturas (default 10), usado para saber cuantas muestras descartar.
    """
    global calibracion_activa

    fs_hz = float(request.form.get('fs', DEFAULT_FREQ_HZ))
    if fs_hz <= 0:
        return jsonify({"error": "La frecuencia (fs) debe ser mayor que 0"}), 400

    archivos_subidos = [f for f in request.files.getlist('archivos') if f.filename]
    if not archivos_subidos:
        return jsonify({"error": "No se recibio ningun archivo. Selecciona la carpeta con los 6 CSV."}), 400

    # --- Detectar la posicion de cada archivo por su nombre ---
    detectados = {}       # posicion -> FileStorage
    no_reconocidos = []
    duplicados = []
    for archivo in archivos_subidos:
        nombre = os.path.basename(archivo.filename)
        if not nombre.lower().endswith('.csv'):
            continue
        pos = _detectar_posicion(nombre)
        if pos is None:
            no_reconocidos.append(nombre)
            continue
        if pos in detectados:
            duplicados.append(f"{nombre} (misma posicion {pos} que {os.path.basename(detectados[pos].filename)})")
            continue
        detectados[pos] = archivo

    faltantes = [p for p in CALIB_ORDEN_POSICIONES if p not in detectados]
    if no_reconocidos or duplicados or faltantes:
        partes = []
        if faltantes:
            partes.append(f"faltan posiciones: {faltantes}")
        if no_reconocidos:
            partes.append(f"no se pudo determinar la posicion de: {no_reconocidos}")
        if duplicados:
            partes.append(f"archivos duplicados para la misma posicion: {duplicados}")
        detectado_resumen = {p: os.path.basename(f.filename) for p, f in detectados.items()}
        return jsonify({
            "error": "No se pudo identificar automaticamente las 6 posiciones a partir de los nombres de archivo "
                     "(" + "; ".join(partes) + "). Los nombres deben incluir el eje (X/Y/Z) y el signo "
                     "(+ / - , o 'up'/'down', o 'arriba'/'abajo'). Detectado hasta ahora: " + str(detectado_resumen)
        }), 400

    n_descarte = int(round(fs_hz * CALIB_N_DESCARTE_SEGUNDOS))

    promedios = []
    detalles = {}

    for pos in CALIB_ORDEN_POSICIONES:
        archivo = detectados[pos]
        try:
            df = pd.read_csv(archivo)
        except Exception as e:
            return jsonify({"error": f"No se pudo leer el archivo de {pos} ({archivo.filename}): {e}"}), 400

        # Igual que calculo_promedios.py: usa las primeras 3 columnas
        # (acc_x, acc_y, acc_z), por nombre si existen o por posicion si no.
        if {"acc_x", "acc_y", "acc_z"}.issubset(df.columns):
            columnas = ["acc_x", "acc_y", "acc_z"]
        elif df.shape[1] >= 3:
            columnas = df.columns[:3].tolist()
        else:
            return jsonify({"error": f"{pos} ({archivo.filename}): el archivo no tiene al menos 3 columnas"}), 400

        if n_descarte >= len(df):
            return jsonify({
                "error": f"{pos} ({archivo.filename}): la captura tiene {len(df)} muestras, no alcanza "
                         f"para descartar {n_descarte} muestras de transitorio ({CALIB_N_DESCARTE_SEGUNDOS}s a {fs_hz}Hz)."
            }), 400

        ventana = df.iloc[n_descarte:]
        promedio = ventana[columnas].mean().to_numpy(dtype=float)
        promedios.append(promedio)
        detalles[pos] = {
            "archivo": os.path.basename(archivo.filename),
            "muestras_totales": int(len(df)),
            "muestras_usadas": int(len(ventana)),
            "promedio_g": promedio.tolist(),
        }

    # --- Mismo algoritmo que calculo_promedios.py, Pasos 2 y 3 ---
    # Nota: los promedios de entrada siguen en g (unidad nativa del sensor);
    # lo que cambia a m/s^2 es el lado "ideal" (CALIB_G), lo cual hace que
    # C y b_a mapeen g -> m/s^2 directamente.
    matriz_transpuesta = np.array(promedios).T          # 3x6 (filas -> columnas)
    fila_unos = np.ones((1, len(CALIB_ORDEN_POSICIONES)))
    M = np.vstack([matriz_transpuesta, fila_unos])       # 4x6, matriz homogenea

    M_plus = np.linalg.pinv(M)                           # pseudoinversa de Moore-Penrose
    Theta = CALIB_G @ M_plus                              # 3x4

    C = Theta[:, 0:3]
    b_a = Theta[:, 3]

    # Verificacion independiente (formula de pares), eje por eje, en m/s^2
    verificacion = {}
    pares = {"x": ("+X", "-X", 0), "y": ("+Y", "-Y", 1), "z": ("+Z", "-Z", 2)}
    for eje, (pos_mas, pos_menos, idx) in pares.items():
        m_mas = detalles[pos_mas]["promedio_g"][idx]
        m_menos = detalles[pos_menos]["promedio_g"][idx]
        s = 2.0 * GRAVEDAD_MS2 / (m_mas - m_menos)
        b = -s * (m_mas + m_menos) / 2
        verificacion[eje] = {"escala": s, "bias_ms2": b}

    # Verificacion por sustitucion: aplicar la C y b_a YA CALCULADAS de vuelta
    # a los datos crudos de cada una de las 6 posiciones, y comparar contra
    # el valor ideal (misma idea que calculo_promedios.py extendido, pero
    # para las 6 posiciones en vez de solo +X,+Y,+Z).
    verificacion_sustitucion = {}
    for i, pos in enumerate(CALIB_ORDEN_POSICIONES):
        crudo_g = np.array(detalles[pos]["promedio_g"])
        cal_ms2 = C @ crudo_g + b_a
        ideal_ms2 = CALIB_G[:, i]
        verificacion_sustitucion[pos] = {
            "crudo_g": crudo_g.tolist(),
            "calibrado_ms2": cal_ms2.tolist(),
            "ideal_ms2": ideal_ms2.tolist(),
            "error_ms2": (cal_ms2 - ideal_ms2).tolist(),
        }

    # Guardar como calibracion activa (disponible para aplicar en vivo) y
    # persistir en disco para no depender de volver a subir los CSV
    calibracion_activa = {"C": C, "b_a": b_a, "fs_hz": fs_hz}
    _guardar_calibracion_en_disco(C, b_a, fs_hz)

    return jsonify({
        "status": "ok",
        "unidad": "m/s^2",
        "fs_hz": fs_hz,
        "n_descarte_muestras": n_descarte,
        "C": C.tolist(),
        "b_a": b_a.tolist(),
        "detalles_por_posicion": detalles,
        "verificacion_formula_pares": verificacion,
        "verificacion_sustitucion": verificacion_sustitucion,
    })


@app.route('/api/calibracion/aplicar', methods=['POST'])
def calibracion_aplicar():
    """Activa/desactiva que el stream en vivo (SSE) incluya campos calibrados."""
    global aplicar_calibracion_en_vivo
    req = request.json or {}
    activar = bool(req.get("activar", False))

    if activar and calibracion_activa is None:
        return jsonify({"error": "Aun no se ha procesado ninguna calibracion."}), 400

    aplicar_calibracion_en_vivo = activar
    return jsonify({"status": "ok", "aplicar_calibracion_en_vivo": aplicar_calibracion_en_vivo})


@app.route('/api/calibracion/estado')
def calibracion_estado():
    return jsonify({
        "tiene_calibracion": calibracion_activa is not None,
        "aplicar_calibracion_en_vivo": aplicar_calibracion_en_vivo,
        "fs_hz": calibracion_activa["fs_hz"] if calibracion_activa else None,
        "C": calibracion_activa["C"].tolist() if calibracion_activa else None,
        "b_a": calibracion_activa["b_a"].tolist() if calibracion_activa else None,
    })



# ---------------------------------------------------------------------------
# Nivelacion de montaje (formula de Rodrigues) - ver seccion 1 del documento
# de nivelacion (calibracion_MPU_CC2650, seccion "Nivelacion de montaje").
#
# La calibracion de arriba (C, b_a) corrige los defectos internos del sensor
# (escala, acoplamiento cruzado, bias), pero no sabe como esta orientado el
# sensor respecto al marco del laboratorio. Eso se corrige aparte, DESPUES de
# calibrar: se sube un CSV con el sensor en reposo ya en su posicion final de
# montaje, se promedia la aceleracion YA CALIBRADA de los primeros segundos
# (estimacion de la direccion de la gravedad vista desde el sensor) y se
# calcula, via la formula de Rodrigues, la matriz de rotacion R que lleva esa
# direccion al eje Z: R se aplica por igual al acelerometro calibrado y al
# giroscopio (a_body = R(M a_raw + b), w_body = R(w_raw - b_g)).
# ---------------------------------------------------------------------------
NIVELACION_JSON_PATH = os.path.join(WORKSPACE_DIR, "nivelacion.json")
NIVEL_SEGUNDOS_DEFAULT = 2.0

nivelacion_activa = None            # {"R": np.array(3x3)} o None si no se ha calculado
aplicar_nivelacion_en_vivo = False  # si True, el stream SSE agrega acc_x_body/gyr_x_body, etc.


def _rodrigues(k, theta):
    """Construye la matriz de rotacion R = I + sin(theta)K + (1-cos(theta))K^2."""
    kx, ky, kz = k
    K = np.array([[0, -kz, ky],
                  [kz, 0, -kx],
                  [-ky, kx, 0]], dtype=float)
    return np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * (K @ K)


def _calcular_R_nivelacion(g_prom):
    """
    g_prom: vector 3 de la aceleracion promedio YA CALIBRADA (m/s^2), con el
    sensor en reposo. Devuelve (R, eje, theta) donde R @ (g_prom/||g_prom||)
    ~= (0,0,1), eje es el vector unitario k y theta el angulo en radianes
    (ver seccion 1.2 del documento de nivelacion / formula de Rodrigues).
    """
    norma = np.linalg.norm(g_prom)
    if norma < 1e-9:
        raise ValueError("La aceleracion promedio es practicamente cero; no se puede nivelar con estos datos.")
    u = g_prom / norma
    v = np.array([0.0, 0.0, 1.0])
    eje_cruz = np.cross(u, v)
    s = np.linalg.norm(eje_cruz)
    c = float(np.dot(u, v))
    if s < 1e-12:
        if c > 0:
            # Vectores ya alineados (theta ~ 0)
            R = np.eye(3)
            eje = np.array([1.0, 0.0, 0.0])  # arbitrario: el angulo es 0, el eje no importa
            theta = 0.0
        else:
            # Antiparalelos (theta ~ 180): girar 180 grados alrededor de
            # cualquier eje perpendicular a u (ver seccion 1.4 del documento)
            perp = np.array([1.0, 0.0, 0.0]) if abs(u[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
            eje_perp = np.cross(u, perp)
            eje_perp = eje_perp / np.linalg.norm(eje_perp)
            R = _rodrigues(eje_perp, math.pi)
            eje = eje_perp
            theta = math.pi
    else:
        theta = math.atan2(s, c)
        eje = eje_cruz / s
        R = _rodrigues(eje, theta)
    return R, eje, theta


def _guardar_nivelacion_en_disco(datos):
    payload = {
        "R": datos["R"].tolist(),
        "eje": datos["eje"].tolist(),
        "theta_rad": datos["theta_rad"],
        "g_prom": datos["g_prom"].tolist(),
        "g_rotado": datos["g_rotado"].tolist(),
        "roll_antes_deg": datos["roll_antes_deg"],
        "pitch_antes_deg": datos["pitch_antes_deg"],
        "roll_despues_deg": datos["roll_despues_deg"],
        "pitch_despues_deg": datos["pitch_despues_deg"],
        "magnitud_g_ms2": datos["magnitud_g_ms2"],
    }
    with open(NIVELACION_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _cargar_nivelacion_de_disco():
    if not os.path.exists(NIVELACION_JSON_PATH):
        return None
    try:
        with open(NIVELACION_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "R": np.array(data["R"]),
            "eje": np.array(data["eje"]),
            "theta_rad": data["theta_rad"],
            "g_prom": np.array(data["g_prom"]),
            "g_rotado": np.array(data["g_rotado"]),
            "roll_antes_deg": data["roll_antes_deg"],
            "pitch_antes_deg": data["pitch_antes_deg"],
            "roll_despues_deg": data["roll_despues_deg"],
            "pitch_despues_deg": data["pitch_despues_deg"],
            "magnitud_g_ms2": data["magnitud_g_ms2"],
        }
    except Exception as e:
        # Si el archivo es de un formato anterior (solo tenia "R"), se ignora
        # y hay que volver a procesar la nivelacion desde la pestaña Calibracion.
        print(f"[NIVEL] No se pudo cargar {NIVELACION_JSON_PATH}: {e}")
        return None


# Cargar automaticamente al iniciar el servidor, si ya existe una nivelacion
# guardada de una sesion anterior
nivelacion_activa = _cargar_nivelacion_de_disco()
if nivelacion_activa is not None:
    print(f"[NIVEL] Nivelacion de montaje previa cargada desde {NIVELACION_JSON_PATH}")


@app.route('/api/nivelacion/procesar', methods=['POST'])
def nivelacion_procesar():
    """
    Espera un form-data con:
      - 'archivo': un unico CSV con el sensor en reposo, ya en su posicion
        final de montaje (NO tiene que ser ninguna de las 6 posiciones de
        la calibracion de arriba).
      - 'fs' (Hz, opcional, default 10): frecuencia de muestreo de la captura.
      - 'segundos' (opcional, default 2): cuantos segundos iniciales
        promediar para estimar la direccion de la gravedad.
    Requiere que ya exista una calibracion de acelerometro procesada (C, b_a):
    la nivelacion se calcula sobre la aceleracion YA CALIBRADA.
    """
    global nivelacion_activa

    if calibracion_activa is None:
        return jsonify({
            "error": "Primero hay que procesar la calibracion del acelerometro (arriba); "
                     "la nivelacion se calcula sobre datos ya calibrados."
        }), 400

    archivo = request.files.get('archivo')
    if archivo is None or not archivo.filename:
        return jsonify({"error": "No se recibio ningun archivo. Selecciona el CSV con el sensor en reposo."}), 400

    fs_hz = float(request.form.get('fs', DEFAULT_FREQ_HZ))
    if fs_hz <= 0:
        return jsonify({"error": "La frecuencia (fs) debe ser mayor que 0"}), 400

    segundos = float(request.form.get('segundos', NIVEL_SEGUNDOS_DEFAULT))
    if segundos <= 0:
        return jsonify({"error": "Los segundos a promediar deben ser mayores que 0"}), 400

    try:
        df = pd.read_csv(archivo)
    except Exception as e:
        return jsonify({"error": f"No se pudo leer el archivo: {e}"}), 400

    if {"acc_x", "acc_y", "acc_z"}.issubset(df.columns):
        columnas = ["acc_x", "acc_y", "acc_z"]
    elif df.shape[1] >= 3:
        columnas = df.columns[:3].tolist()
    else:
        return jsonify({"error": "El archivo no tiene al menos 3 columnas de aceleracion"}), 400

    n_muestras = max(1, int(round(fs_hz * segundos)))
    if n_muestras > len(df):
        return jsonify({
            "error": f"La captura tiene {len(df)} muestras, no alcanza para promediar "
                     f"{segundos}s a {fs_hz}Hz ({n_muestras} muestras)."
        }), 400

    ventana = df.iloc[:n_muestras]
    promedio_crudo_g = ventana[columnas].mean().to_numpy(dtype=float)

    # Aplicar la calibracion YA calculada (C, b_a) al promedio crudo. Al ser
    # una transformacion afin, promediar-y-luego-calibrar da lo mismo que
    # calibrar-y-luego-promediar.
    C = calibracion_activa["C"]
    b_a = calibracion_activa["b_a"]
    g_prom = C @ promedio_crudo_g + b_a  # m/s^2, aceleracion promedio calibrada

    try:
        R, eje, theta = _calcular_R_nivelacion(g_prom)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    g_rotado = R @ g_prom
    magnitud = float(np.linalg.norm(g_prom))

    # Chequeos descritos en la seccion 1.5 del documento: roll/pitch ANTES
    # (con la gravedad cruda calibrada, sin nivelar) y DESPUES (ya rotada,
    # deben salir ~0 grados por construccion) para poder comparar.
    roll_antes_deg = math.degrees(math.atan2(g_prom[1], g_prom[2]))
    pitch_antes_deg = math.degrees(math.atan2(-g_prom[0], math.sqrt(g_prom[1] ** 2 + g_prom[2] ** 2)))
    roll_deg = math.degrees(math.atan2(g_rotado[1], g_rotado[2]))
    pitch_deg = math.degrees(math.atan2(-g_rotado[0], math.sqrt(g_rotado[1] ** 2 + g_rotado[2] ** 2)))

    nivelacion_activa = {
        "R": R,
        "eje": eje,
        "theta_rad": theta,
        "g_prom": g_prom,
        "g_rotado": g_rotado,
        "roll_antes_deg": roll_antes_deg,
        "pitch_antes_deg": pitch_antes_deg,
        "roll_despues_deg": roll_deg,
        "pitch_despues_deg": pitch_deg,
        "magnitud_g_ms2": magnitud,
    }
    _guardar_nivelacion_en_disco(nivelacion_activa)

    return jsonify({
        "status": "ok",
        "R": R.tolist(),
        "eje_k": eje.tolist(),
        "theta_deg": math.degrees(theta),
        "muestras_usadas": n_muestras,
        "promedio_crudo_g": promedio_crudo_g.tolist(),
        "g_promedio_calibrado_ms2": g_prom.tolist(),
        "g_rotado_ms2": g_rotado.tolist(),
        "magnitud_g_ms2": magnitud,
        "roll_antes_deg": roll_antes_deg,
        "pitch_antes_deg": pitch_antes_deg,
        "roll_deg": roll_deg,
        "pitch_deg": pitch_deg,
    })


@app.route('/api/nivelacion/aplicar', methods=['POST'])
def nivelacion_aplicar():
    """Activa/desactiva que el stream en vivo (SSE) incluya campos en el marco del cuerpo."""
    global aplicar_nivelacion_en_vivo
    req = request.json or {}
    activar = bool(req.get("activar", False))

    if activar and (nivelacion_activa is None or calibracion_activa is None):
        return jsonify({"error": "Aun no se ha calculado la nivelacion (o falta la calibracion del acelerometro)."}), 400

    aplicar_nivelacion_en_vivo = activar
    return jsonify({"status": "ok", "aplicar_nivelacion_en_vivo": aplicar_nivelacion_en_vivo})


@app.route('/api/nivelacion/estado')
def nivelacion_estado():
    if nivelacion_activa is None:
        return jsonify({
            "tiene_nivelacion": False,
            "aplicar_nivelacion_en_vivo": aplicar_nivelacion_en_vivo,
        })
    return jsonify({
        "tiene_nivelacion": True,
        "aplicar_nivelacion_en_vivo": aplicar_nivelacion_en_vivo,
        "R": nivelacion_activa["R"].tolist(),
        "eje_k": nivelacion_activa["eje"].tolist(),
        "theta_deg": math.degrees(nivelacion_activa["theta_rad"]),
        "g_promedio_calibrado_ms2": nivelacion_activa["g_prom"].tolist(),
        "g_rotado_ms2": nivelacion_activa["g_rotado"].tolist(),
        "roll_antes_deg": nivelacion_activa["roll_antes_deg"],
        "pitch_antes_deg": nivelacion_activa["pitch_antes_deg"],
        "roll_deg": nivelacion_activa["roll_despues_deg"],
        "pitch_deg": nivelacion_activa["pitch_despues_deg"],
        "magnitud_g_ms2": nivelacion_activa["magnitud_g_ms2"],
    })


@app.route('/api/stream')
def stream_data():
    def event_stream():
        q = queue.Queue(maxsize=100)
        with client_queues_lock:
            client_queues.append(q)
        
        print(f"[SSE] Nuevo cliente conectado. Clientes activos: {len(client_queues)}")
        try:
            while True:
                # Esperar datos de la cola
                try:
                    payload = q.get(timeout=2.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except queue.Empty:
                    # Enviar heartbeat
                    yield "data: {\"heartbeat\": true}\n\n"
        except GeneratorExit:
            pass
        finally:
            with client_queues_lock:
                if q in client_queues:
                    client_queues.remove(q)
            print(f"[SSE] Cliente desconectado. Clientes activos: {len(client_queues)}")
            
    return Response(event_stream(), mimetype="text/event-stream")

def main():
    # Iniciar BLE manager loop
    ble_manager.start()
    
    # Abrir navegador automaticamente despues de que Flask inicie
    def open_browser():
        time.sleep(1.5)
        print("\n[APP] Abriendo navegador en http://127.0.0.1:5000")
        webbrowser.open("http://127.0.0.1:5000")
        
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Iniciar Flask
    app.run(host="127.0.0.1", port=5000, debug=False)

if __name__ == '__main__':
    main()