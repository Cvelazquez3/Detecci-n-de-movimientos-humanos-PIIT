import os
import sys
import time
import math
import random
import json
import queue
import threading
import asyncio
import webbrowser
import pandas as pd
from flask import Flask, Response, render_template, jsonify, request

# SensorTag GATT UUIDs
MOV_DATA = "f000aa81-0451-4000-b000-000000000000"
MOV_CONF = "f000aa82-0451-4000-b000-000000000000"
MOV_PERI = "f000aa83-0451-4000-b000-000000000000"

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

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def connect(self):
        if self.status in ["scanning", "connecting", "connected"]:
            return
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
            
            # Configurar periodo de muestreo a 100ms (10Hz)
            await self.client.write_gatt_char(MOV_PERI, bytearray([0x0A]))
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

        payload = {
            'timestamp': time.time(),
            'acc_x': ax, 'acc_y': ay, 'acc_z': az,
            'gyr_x': gx, 'gyr_y': gy, 'gyr_z': gz
        }

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

# Simulador de SensorTag
simulating = False
sim_thread = None

def simulate_data_generator():
    global simulating
    print("[SIM] Iniciando generador de datos simulados...")
    t = 0
    while simulating:
        time.sleep(0.1) # 10Hz
        t += 0.1
        
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
    global simulating
    return jsonify({
        "ble_status": ble_manager.status,
        "ble_error": ble_manager.error,
        "is_simulating": simulating,
        "is_recording": state.is_recording,
        "recorded_samples": len(state.recorded_data) if state.is_recording else 0,
        "recording_filename": state.filename
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
        
        # Rellenar timestamp si no existe
        if 'timestamp' not in df.columns:
            # Asumir 10Hz (0.1s entre muestras)
            df['timestamp'] = [i * 0.1 for i in range(len(df))]
            
        data = df[['timestamp', 'acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']].to_dict(orient='records')
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/connect', methods=['POST'])
def connect_ble():
    global simulating
    if simulating:
        stop_simulation()
    ble_manager.connect()
    return jsonify({"status": "connecting"})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_ble():
    ble_manager.disconnect()
    return jsonify({"status": "disconnecting"})

@app.route('/api/start_simulation', methods=['POST'])
def start_simulation_endpoint():
    global simulating, sim_thread
    if ble_manager.status == "connected":
        ble_manager.disconnect()
    
    if not simulating:
        simulating = True
        sim_thread = threading.Thread(target=simulate_data_generator, daemon=True)
        sim_thread.start()
    return jsonify({"status": "simulating"})

@app.route('/api/stop_simulation', methods=['POST'])
def stop_simulation_endpoint():
    stop_simulation()
    return jsonify({"status": "stopped"})

def stop_simulation():
    global simulating
    simulating = False

@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    req = request.json or {}
    filename = req.get("filename", "Prueba.csv")
    if not filename.endswith(".csv"):
        filename += ".csv"
        
    with recording_lock:
        state.is_recording = True
        state.recorded_data = []
        state.filename = filename
        state.start_time = time.time()
        
    print(f"[REC] Grabando datos en {filename}...")
    return jsonify({"status": "recording", "filename": filename})

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
        filename = state.filename
        state.recorded_data = []
        state.filename = ""
        
    print(f"[REC] Grabacion completada. Guardado en {filepath} ({samples} muestras, {duration:.1f}s)")
    return jsonify({
        "status": "saved",
        "filename": filename,
        "samples": samples,
        "duration": duration
    })

# Stream SSE
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
