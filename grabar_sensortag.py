import asyncio
import time
import pandas as pd
from bleak import BleakClient, BleakScanner

MOV_DATA = "f000aa81-0451-4000-b000-000000000000"
MOV_CONF = "f000aa82-0451-4000-b000-000000000000"
MOV_PERI = "f000aa83-0451-4000-b000-000000000000"

NOMBRE_ARCHIVO = "Prueba.csv"
N_MUESTRAS     = 200
N_CALIBRACION  = 30  # 3 segundos a 10Hz para calibrar orientacion

datos = []
fase_calibracion = True

def callback_sensores(sender, raw):
    global datos, fase_calibracion
    if len(raw) < 5:
        return

    # Giroscopio en rad/s (compatible con MobiFall)
    gx = int.from_bytes(raw[0:2], "little", signed=True) * 0.00875 / 57.2958
    gy = int.from_bytes(raw[2:4], "little", signed=True) * 0.00875 / 57.2958
    gz = int.from_bytes(raw[4:6], "little", signed=True) * 0.00875 / 57.2958

    # Acelerometro en g
    ax = int.from_bytes(raw[6:8],  "little", signed=True) / 16384.0
    ay = int.from_bytes(raw[8:10], "little", signed=True) / 16384.0
    az = int.from_bytes(raw[10:12],"little", signed=True) / 16384.0

    datos.append({
        'timestamp': time.time(),
        'acc_x': ax, 'acc_y': ay, 'acc_z': az,
        'gyr_x': gx, 'gyr_y': gy, 'gyr_z': gz
    })

    n = len(datos)

    if n <= N_CALIBRACION:
        restantes = N_CALIBRACION - n
        barra = "█" * (N_CALIBRACION - restantes) + "░" * restantes
        print(f"\r  [{barra}] Calibrando... {restantes} muestras restantes", end="", flush=True)
        if n == N_CALIBRACION:
            print(f"\n  Calibracion lista. REALIZA EL MOVIMIENTO AHORA.")
    else:
        muestras_movimiento = n - N_CALIBRACION
        total_movimiento    = N_MUESTRAS - N_CALIBRACION
        if muestras_movimiento % 20 == 0:
            print(f"  Grabando movimiento: {muestras_movimiento}/{total_movimiento} muestras")

async def grabar():
    global datos, fase_calibracion
    datos          = []
    fase_calibracion = True

    print("Buscando SensorTag...")
    device = None
    detected = await BleakScanner.discover(timeout=5.0)
    for d in detected:
        if d.name and "SensorTag" in d.name:
            device = d
            break

    if not device:
        print("Error: No se encontro el SensorTag."); return

    try:
        async with BleakClient(device) as client:
            print(f"Conectado a {device.address}. Configurando...")

            await client.write_gatt_char(MOV_PERI, bytearray([0x0A]))
            await client.write_gatt_char(MOV_CONF, bytearray([0x3F, 0x00]))
            await asyncio.sleep(1.5)

            await client.start_notify(MOV_DATA, callback_sensores)

            print(f"\n{'='*50}")
            print(f"  FASE 1 — CALIBRACION (3 segundos)")
            print(f"  Coloca el sensor en la cintura y queda COMPLETAMENTE QUIETO.")
            print(f"  No te muevas hasta que aparezca 'REALIZA EL MOVIMIENTO AHORA'")
            print(f"{'='*50}")

            # Esperar calibracion
            while len(datos) < N_CALIBRACION:
                await asyncio.sleep(0.1)

            print(f"\n{'='*50}")
            print(f"  FASE 2 — GRABACION DE MOVIMIENTO ({(N_MUESTRAS - N_CALIBRACION) // 10} segundos)")
            print(f"  Camina 3-4 pasos y realiza la caida sobre la colchoneta.")
            print(f"  Queda en el suelo hasta que aparezca 'Archivo guardado'.")
            print(f"{'='*50}\n")

            # Esperar grabacion completa
            while len(datos) < N_MUESTRAS:
                await asyncio.sleep(0.1)

            await client.stop_notify(MOV_DATA)

            df = pd.DataFrame(datos)
            duracion = df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]
            fs_real  = len(df) / duracion
            print(f"\nFrecuencia real: {fs_real:.2f} Hz")

            # Guardar sin timestamp, columnas ordenadas por eje (datos crudos del sensor)
            columnas = ['acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']
            df[columnas].to_csv(NOMBRE_ARCHIVO, index=False)
            print(f"\nArchivo guardado: {NOMBRE_ARCHIVO}")
            print(f"Duracion total: {duracion:.1f} segundos")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(grabar())