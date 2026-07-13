import asyncio
from bleak import BleakScanner

async def scan():
    print("Escaneando dispositivos BLE durante 8 segundos...")
    
    found = []
    
    def callback(device, adv_data):
        # adv_data contiene el rssi en versiones nuevas de bleak
        entry = {
            "name": device.name or "(sin nombre)",
            "address": device.address,
            "rssi": adv_data.rssi if hasattr(adv_data, "rssi") else "?"
        }
        found.append(entry)

    async with BleakScanner(detection_callback=callback) as scanner:
        await asyncio.sleep(8.0)

    if not found:
        print("No se encontraron dispositivos BLE cercanos.")
        print("Verifica que el Bluetooth de Windows este encendido.")
    else:
        # Eliminar duplicados por direccion
        seen = {}
        for e in found:
            seen[e["address"]] = e
        unique = sorted(seen.values(), key=lambda x: x["rssi"] if isinstance(x["rssi"], int) else -999, reverse=True)
        
        print(f"\nSe encontraron {len(unique)} dispositivo(s) unicos:\n")
        sensortag_found = False
        for e in unique:
            marca = " <-- *** SENSORTAG ENCONTRADO ***" if e["name"] and "SensorTag" in e["name"] else ""
            if marca:
                sensortag_found = True
            print(f"  {e['name']:40s} | {e['address']} | RSSI: {e['rssi']} dBm{marca}")
        
        if not sensortag_found:
            print("\n[!] SensorTag NO encontrado entre los dispositivos. Presiona su boton lateral.")

asyncio.run(scan())

