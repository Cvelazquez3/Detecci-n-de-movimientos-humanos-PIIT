/* ==========================================================================
   Lógica del Cliente - Visualizador IMU PIIT
   Manejo de UI, Gráficos (Chart.js), Renderizado 3D (Three.js) y Fusión
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    // === Variables de Estado ===
    let activeTab = "dashboard";
    let isConnected = false;
    let isSimulating = false;
    let isRecording = false;
    let sseSource = null;
    
    // Datos de Playback CSV
    let csvData = [];
    let playbackInterval = null;
    let playbackIndex = 0;
    let isPlaying = false;
    let playbackSpeed = 1.0;
    
    // Algoritmos de Fusión (Orientación)
    let alpha = 0.98;
    
    // Ángulos acumulados / calculados
    let angleRollAcc = 0, anglePitchAcc = 0;
    let angleRollGyro = 0, anglePitchGyro = 0, angleYawGyro = 0;
    let angleRollFilter = 0, anglePitchFilter = 0, angleYawFilter = 0;
    let lastTimestamp = null;

    // Correccion de bias del giroscopio aplicada a la orientacion en vivo
    // (queda en 0 hasta que exista un mecanismo que la alimente)
    let gyroBias = { x: 0, y: 0, z: 0 };

    // Frecuencia de muestreo: la seleccionada en la UI (se manda al conectar/simular)
    // y la que efectivamente esta activa ahora mismo (para calibracion de bias, etc.)
    let selectedFreqHz = 10;
    let activeSampleRateHz = 10;

    // === Inicialización de Elementos UI ===
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    
    const bleStatusDot = document.getElementById("ble-status-dot");
    const bleStatusText = document.getElementById("ble-status-text");
    const btnConnect = document.getElementById("btn-connect");
    const btnDisconnect = document.getElementById("btn-disconnect");
    const btnSimulate = document.getElementById("btn-simulate");
    const btnStopSimulate = document.getElementById("btn-stop-simulate");

    // Selector de frecuencia de muestreo (10Hz / 50Hz)
    const freqButtons = document.querySelectorAll(".freq-btn");
    const freqLiveBadge = document.getElementById("freq-live-badge");
    const freqTargetVal = document.getElementById("freq-target-val");
    const freqActualVal = document.getElementById("freq-actual-val");
    const freqWarningBox = document.getElementById("freq-warning-box");
    const freqWarningText = document.getElementById("freq-warning-text");
    const csvFsSelect = document.getElementById("csv-fs-select");
    
    const recFilename = document.getElementById("rec-filename");
    const btnRecord = document.getElementById("btn-record");
    const recStatus = document.getElementById("rec-status");
    const recCount = document.getElementById("rec-count");
    const recCountdown = document.getElementById("rec-countdown");
    const btnDownloadExcel = document.getElementById("btn-download-excel");
    const RECORDING_DURATION_S = 60; // Duracion de grabacion en segundos
    let recordingTimer = null;
    
    const csvSelect = document.getElementById("csv-select");
    const btnRefreshCsv = document.getElementById("btn-refresh-csv");
    const playbackControlsBar = document.getElementById("playback-controls-bar");
    const btnPlay = document.getElementById("btn-play");
    const playbackScrubber = document.getElementById("playback-scrubber");
    const timeCurrent = document.getElementById("time-current");
    const timeTotal = document.getElementById("time-total");
    const speedSelect = document.getElementById("speed-select");
    const sourceBadge = document.getElementById("source-badge");

    // Telemetría
    const valAx = document.getElementById("val-ax");
    const valAy = document.getElementById("val-ay");
    const valAz = document.getElementById("val-az");
    const valGx = document.getElementById("val-gx");
    const valGy = document.getElementById("val-gy");
    const valGz = document.getElementById("val-gz");
    const barAx = document.getElementById("bar-ax");
    const barAy = document.getElementById("bar-ay");
    const barAz = document.getElementById("bar-az");
    const barGx = document.getElementById("bar-gx");
    const barGy = document.getElementById("bar-gy");
    const barGz = document.getElementById("bar-gz");
    
    const valRoll = document.getElementById("val-roll");
    const valPitch = document.getElementById("val-pitch");
    const valYaw = document.getElementById("val-yaw");

    // === Nueva pestaña: Calibración del acelerómetro ===
    let calibFreqHz = 10;
    let calibArchivosSeleccionados = [];  // File[] de la carpeta elegida
    const calibFreqSelector = document.getElementById("calib-freq-selector");
    const calibFolderInput = document.getElementById("calib-folder-input");
    const calibFolderLista = document.getElementById("calib-folder-lista");
    const btnCalibProcesar = document.getElementById("btn-calib-procesar");
    const btnCalibDescargar = document.getElementById("btn-calib-descargar");
    const calibErrorBox = document.getElementById("calib-error-box");
    const calibErrorText = document.getElementById("calib-error-text");
    const calibResultadoCard = document.getElementById("calib-resultado-card");
    const calibVerificacionCard = document.getElementById("calib-verificacion-card");
    const calibMatrixC = document.getElementById("calib-matrix-c");
    const calibVectorB = document.getElementById("calib-vector-b");
    const calibVerificacionTabla = document.getElementById("calib-verificacion-tabla");
    const calibSustitucionCard = document.getElementById("calib-sustitucion-card");
    const calibSustitucionTabla = document.getElementById("calib-sustitucion-tabla");
    const calibToggleVivo = document.getElementById("calib-toggle-vivo");
    let ultimoResultadoCalibracion = null;

    // Panel de telemetría calibrada en vivo (Dashboard)
    const calibLiveBadge = document.getElementById("calib-live-badge");
    const valAxCal = document.getElementById("val-ax-cal");
    const valAyCal = document.getElementById("val-ay-cal");
    const valAzCal = document.getElementById("val-az-cal");

    // === Nivelación de montaje (fórmula de Rodrigues) ===
    let nivelArchivoSeleccionado = null;
    let ultimoResultadoNivelacion = null;
    const nivelArchivoInput = document.getElementById("nivel-archivo-input");
    const nivelArchivoNombre = document.getElementById("nivel-archivo-nombre");
    const nivelFsInput = document.getElementById("nivel-fs-input");
    const nivelSegundosInput = document.getElementById("nivel-segundos-input");
    const btnNivelProcesar = document.getElementById("btn-nivel-procesar");
    const btnNivelDescargar = document.getElementById("btn-nivel-descargar");
    const nivelErrorBox = document.getElementById("nivel-error-box");
    const nivelErrorText = document.getElementById("nivel-error-text");
    const nivelResultadoCard = document.getElementById("nivel-resultado-card");
    const nivelVerificacionCard = document.getElementById("nivel-verificacion-card");
    const nivelMatrixR = document.getElementById("nivel-matrix-r");
    const nivelVerificacionTabla = document.getElementById("nivel-verificacion-tabla");
    const nivelToggleVivo = document.getElementById("nivel-toggle-vivo");

    // Panel de telemetría nivelada en vivo (Dashboard, marco del cuerpo)
    const nivelLiveBadge = document.getElementById("nivel-live-badge");
    const valAxBody = document.getElementById("val-ax-body");
    const valAyBody = document.getElementById("val-ay-body");
    const valAzBody = document.getElementById("val-az-body");
    const valGxBody = document.getElementById("val-gx-body");
    const valGyBody = document.getElementById("val-gy-body");
    const valGzBody = document.getElementById("val-gz-body");

    // === Control de Pestañas ===
    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabId = btn.getAttribute("data-tab");
            
            navButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(tc => tc.classList.remove("active"));
            
            btn.classList.add("active");
            document.getElementById(`tab-${tabId}`).classList.add("active");
            
            activeTab = tabId;
            
            // Forzar redimensionamiento de gráficos para evitar glitches visuales
            if (activeTab === "charts") {
                chartAcc.resize();
                chartGyr.resize();
            }

            // La pestaña de nivelación 3D se inicializa la primera vez que se
            // abre (para que el contenedor ya tenga un tamaño real, no 0x0
            // por estar oculta con display:none al cargar la página).
            if (activeTab === "nivelacion3d") {
                if (!nivel3dInicializado) {
                    inicializarEscenaNivel3D();
                } else {
                    nivel3dSceneRefs.camera.aspect = nivel3dSceneRefs.container.clientWidth / nivel3dSceneRefs.container.clientHeight;
                    nivel3dSceneRefs.camera.updateProjectionMatrix();
                    nivel3dSceneRefs.renderer.setSize(nivel3dSceneRefs.container.clientWidth, nivel3dSceneRefs.container.clientHeight);
                }
                cargarNivel3D();
            }
        });
    });

    // === Configuración de Three.js ===
    const threeContainer = document.getElementById("three-container");
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xd6e9fb);
    
    const camera = new THREE.PerspectiveCamera(45, threeContainer.clientWidth / threeContainer.clientHeight, 0.1, 100);
    camera.position.set(5, 4, 7);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(threeContainer.clientWidth, threeContainer.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    threeContainer.appendChild(renderer.domElement);

    // Controles de cámara con el ratón (OrbitControls)
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 2;
    controls.maxDistance = 15;

    // Ajustar Three.js al cambiar tamaño
    window.addEventListener("resize", () => {
        camera.aspect = threeContainer.clientWidth / threeContainer.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(threeContainer.clientWidth, threeContainer.clientHeight);
    });

    // Luces
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);
    
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(5, 10, 7);
    dirLight.castShadow = true;
    scene.add(dirLight);

    // Rejilla de Referencia (Suelo)
    const gridHelper = new THREE.GridHelper(12, 12, 0x3f51b5, 0x1a237e);
    gridHelper.position.y = -2;
    scene.add(gridHelper);

    // SensorTag 3D (Carcasa)
    // Dimensiones relativas del CC2650 SensorTag (Aplanado para yacer sobre la rejilla)
    const bodyGeometry = new THREE.BoxGeometry(3, 0.5, 1.5);
    // Crear materiales individuales para caras y dar aspecto real (tapa superior roja)
    const materials = [
        new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.5 }), // Derecho (+X)
        new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.5 }), // Izquierdo (-X)
        new THREE.MeshStandardMaterial({ color: 0xcc2650, roughness: 0.6 }), // Superior (+Y - Rojo SensorTag)
        new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.5 }), // Inferior (-Y)
        new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.5 }), // Frontal (+Z)
        new THREE.MeshStandardMaterial({ color: 0x2d3436, roughness: 0.5 })  // Trasero (-Z)
    ];
    
    const sensorBody = new THREE.Mesh(bodyGeometry, materials);
    sensorBody.castShadow = true;
    scene.add(sensorBody);

    // Funda protectora negra de goma (anillo exterior)
    const rubberGeometry = new THREE.BoxGeometry(3.1, 0.55, 1.6);
    const rubberMaterial = new THREE.MeshStandardMaterial({ color: 0x1e272e, roughness: 0.9 });
    const rubberShield = new THREE.Mesh(rubberGeometry, rubberMaterial);
    sensorBody.add(rubberShield);

    // Botón de encendido (Círculo en la tapa superior)
    const buttonGeom = new THREE.CylinderGeometry(0.15, 0.15, 0.05, 16);
    const buttonMat = new THREE.MeshStandardMaterial({ color: 0xdcdde1, roughness: 0.3, metalness: 0.5 });
    const powerButton = new THREE.Mesh(buttonGeom, buttonMat);
    powerButton.position.set(0.8, 0.26, 0);
    sensorBody.add(powerButton);

    // Flechas de los Ejes Físicos del Sensor
    // Eje X (Rojo) - Apunta a lo ancho (mapeado a Z del mundo)
    const arrowX = new THREE.ArrowHelper(
        new THREE.Vector3(0, 0, 1), 
        new THREE.Vector3(0, 0, 0), 
        1.5, 
        0xff4757, 
        0.3, 
        0.12
    );
    sensorBody.add(arrowX);

    // Eje Y (Verde) - Apunta a lo largo (mapeado a X del mundo)
    const arrowY = new THREE.ArrowHelper(
        new THREE.Vector3(1, 0, 0), 
        new THREE.Vector3(0, 0, 0), 
        2.2, 
        0x2ed573, 
        0.4, 
        0.15
    );
    sensorBody.add(arrowY);

    // Eje Z (Azul) - Apunta perpendicular al plano (mapeado a Y del mundo, hacia arriba)
    const arrowZ = new THREE.ArrowHelper(
        new THREE.Vector3(0, 1, 0), 
        new THREE.Vector3(0, 0, 0), 
        1.2, 
        0x1e90ff, 
        0.2, 
        0.08
    );
    sensorBody.add(arrowZ);

    // Flecha de Aceleración Total en el marco mundial (gris oscuro, para que
    // se distinga bien sobre el fondo azul claro del visor 3D)
    // En reposo, apunta hacia arriba (+Y del mundo) reflejando la fuerza normal
    const gravityArrow = new THREE.ArrowHelper(
        new THREE.Vector3(0, 1, 0),
        new THREE.Vector3(0, 0, 0),
        2.0,
        0x1e293b,
        0.3,
        0.12
    );
    scene.add(gravityArrow);

    // Animación de Three.js (Estática para evitar rotaciones espaciales confusas)
    function animate() {
        requestAnimationFrame(animate);
        controls.update(); // Actualizar amortiguación de controles de cámara
        renderer.render(scene, camera);
    }
    animate();

    // === Configuración de Chart.js ===
    // Configuración común para Gráficos Oscuros Científicos
    const chartOptions = (yLabel) => ({
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            x: {
                grid: { color: varColor("--chart-grid") },
                ticks: { color: varColor("--text-muted"), font: { family: "Outfit" } }
            },
            y: {
                grid: { color: varColor("--chart-grid") },
                ticks: { color: varColor("--text-muted"), font: { family: "Outfit" } },
                title: { display: true, text: yLabel, color: varColor("--text-main"), font: { family: "Outfit", size: 12 } }
            }
        },
        plugins: {
            legend: {
                labels: { color: varColor("--text-main"), font: { family: "Outfit", size: 11 } }
            }
        }
    });

    function varColor(cssVar) {
        return getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
    }

    // Chart Acelerómetro
    const ctxAcc = document.getElementById("chart-acc").getContext("2d");
    const chartAcc = new Chart(ctxAcc, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                { label: "Acc X", data: [], borderColor: "#ef4444", backgroundColor: "rgba(239, 68, 68, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 },
                { label: "Acc Y", data: [], borderColor: "#16a34a", backgroundColor: "rgba(22, 163, 74, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 },
                { label: "Acc Z", data: [], borderColor: "#2563eb", backgroundColor: "rgba(37, 99, 235, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 }
            ]
        },
        options: chartOptions("Aceleración (g)")
    });

    // Chart Giroscopio
    const ctxGyr = document.getElementById("chart-gyr").getContext("2d");
    const chartGyr = new Chart(ctxGyr, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                { label: "α (alpha)", data: [], borderColor: "#ef4444", backgroundColor: "rgba(239, 68, 68, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 },
                { label: "β (beta)", data: [], borderColor: "#16a34a", backgroundColor: "rgba(22, 163, 74, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 },
                { label: "γ (gamma)", data: [], borderColor: "#2563eb", backgroundColor: "rgba(37, 99, 235, 0.1)", borderWidth: 2, pointRadius: 0, tension: 0.1 }
            ]
        },
        options: chartOptions("Velocidad Angular (rad/s)")
    });

    // === Botón de tema claro / oscuro ===
    const THEME_STORAGE_KEY = "imu_visualizer_theme";
    const btnThemeToggle = document.getElementById("btn-theme-toggle");

    function sincronizarBotonTema(tema) {
        if (!btnThemeToggle) return;
        btnThemeToggle.innerHTML = tema === "dark"
            ? `<i class="fa-solid fa-sun"></i>`
            : `<i class="fa-solid fa-moon"></i>`;
        btnThemeToggle.title = tema === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
    }

    function actualizarColoresGraficas() {
        const gridColor = varColor("--chart-grid");
        const textMuted = varColor("--text-muted");
        const textMain = varColor("--text-main");
        [chartAcc, chartGyr].forEach(chart => {
            chart.options.scales.x.grid.color = gridColor;
            chart.options.scales.x.ticks.color = textMuted;
            chart.options.scales.y.grid.color = gridColor;
            chart.options.scales.y.ticks.color = textMuted;
            chart.options.scales.y.title.color = textMain;
            chart.options.plugins.legend.labels.color = textMain;
            chart.update();
        });
    }

    function cambiarTema(tema) {
        document.documentElement.setAttribute("data-theme", tema);
        try {
            localStorage.setItem(THEME_STORAGE_KEY, tema);
        } catch (e) { /* localStorage no disponible, el tema no persiste */ }
        sincronizarBotonTema(tema);
        actualizarColoresGraficas();
    }

    // El <head> ya aplicó el tema guardado (para evitar parpadeo); aquí solo
    // sincronizamos el icono del botón con lo que quedó activo.
    sincronizarBotonTema(document.documentElement.getAttribute("data-theme") || "light");

    if (btnThemeToggle) {
        btnThemeToggle.addEventListener("click", () => {
            const actual = document.documentElement.getAttribute("data-theme") || "light";
            cambiarTema(actual === "dark" ? "light" : "dark");
        });
    }

    // === Lógica del Algoritmo de Orientación ===
    // (alimenta el cubo 3D del Dashboard: filtro complementario Roll/Pitch,
    //  integracion de Yaw; ya no hay pestaña de graficas de deriva dedicada)
    function resetOrientation() {
        angleRollAcc = 0; anglePitchAcc = 0;
        angleRollGyro = 0; anglePitchGyro = 0; angleYawGyro = 0;
        angleRollFilter = 0; anglePitchFilter = 0; angleYawFilter = 0;
        lastTimestamp = null;
        
        // Reset de gráficos si estamos en Live
        if (isConnected || isSimulating) {
            chartAcc.data.labels = [];
            chartAcc.data.datasets.forEach(d => d.data = []);
            chartGyr.data.labels = [];
            chartGyr.data.datasets.forEach(d => d.data = []);
        }
    }

    function processIMUData(data, isLive = true) {
        const ax = data.acc_x;
        const ay = data.acc_y;
        const az = data.acc_z;
        const gx = data.gyr_x;
        const gy = data.gyr_y;
        const gz = data.gyr_z;
        
        // Calcular dT (paso de tiempo)
        let dt = 0.1; // Default 10Hz
        if (lastTimestamp !== null) {
            dt = data.timestamp - lastTimestamp;
            // Evitar pasos de tiempo irreales debido a reconexiones
            if (dt <= 0 || dt > 1.0) dt = 0.1;
        }
        lastTimestamp = data.timestamp;

        // 1. Orientación basada UNICAMENTE en Acelerómetro (Gravedad)
        // Roll (alrededor de X) y Pitch (alrededor de Y)
        angleRollAcc = Math.atan2(ay, az);
        anglePitchAcc = Math.atan2(-ax, Math.sqrt(ay * ay + az * az));

        // 2. Orientación basada UNICAMENTE en Giroscopio (Integración de velocidad angular)
        // Descontar sesgo (bias) antes de integrar (por defecto es 0 si no se calibra)
        const gx_corrected = gx - gyroBias.x;
        const gy_corrected = gy - gyroBias.y;
        const gz_corrected = gz - gyroBias.z;

        angleRollGyro += gx_corrected * dt;
        anglePitchGyro += gy_corrected * dt;
        angleYawGyro += gz_corrected * dt;

        // 3. Fusión de sensores mediante Filtro Complementario
        // Para el primer paso, inicializar con el acelerómetro para estabilización rápida
        if (angleRollFilter === 0 && anglePitchFilter === 0 && isLive && chartAcc.data.labels.length === 1) {
            angleRollFilter = angleRollAcc;
            anglePitchFilter = anglePitchAcc;
        } else {
            angleRollFilter = alpha * (angleRollFilter + gx_corrected * dt) + (1 - alpha) * angleRollAcc;
            anglePitchFilter = alpha * (anglePitchFilter + gy_corrected * dt) + (1 - alpha) * anglePitchAcc;
        }
        angleYawFilter = angleYawGyro; // No hay gravedad de referencia para Yaw en Z, es solo integracion

        // Conversión a grados para visualización
        const rollDeg = angleRollFilter * (180 / Math.PI);
        const pitchDeg = anglePitchFilter * (180 / Math.PI);
        const yawDeg = angleYawFilter * (180 / Math.PI);
        
        const rollAccDeg = angleRollAcc * (180 / Math.PI);
        const pitchAccDeg = anglePitchAcc * (180 / Math.PI);
        const rollGyroDeg = angleRollGyro * (180 / Math.PI);
        const pitchGyroDeg = anglePitchGyro * (180 / Math.PI);
        const yawGyroDeg = angleYawGyro * (180 / Math.PI);

        // === Actualizar UI Telemetría ===
        valAx.innerText = ax.toFixed(3);
        valAy.innerText = ay.toFixed(3);
        valAz.innerText = az.toFixed(3);
        valGx.innerText = gx.toFixed(3);
        valGy.innerText = gy.toFixed(3);
        valGz.innerText = gz.toFixed(3);

        // Barras de progreso de telemetría (escaladas a rangos de visualización razonables)
        // Aceleración: max 2g, Giroscopio: max 5 rad/s
        setProgressBarWidth(barAx, ax, 2.0);
        setProgressBarWidth(barAy, ay, 2.0);
        setProgressBarWidth(barAz, az, 2.0);
        setProgressBarWidth(barGx, gx, 3.0);
        setProgressBarWidth(barGy, gy, 3.0);
        setProgressBarWidth(barGz, gz, 3.0);

        valRoll.innerText = `${rollDeg.toFixed(1)}°`;
        valPitch.innerText = `${pitchDeg.toFixed(1)}°`;
        valYaw.innerText = `${yawDeg.toFixed(1)}°`;

        // === Actualizar Modelo 3D ===
        // Aplicar rotaciones en los ejes correspondientes:
        // Roll (alrededor del eje Z de Three.js / X del sensor)
        // Yaw (alrededor del eje Y de Three.js / Z del sensor)
        // Pitch (alrededor del eje X de Three.js / Y del sensor)
        sensorBody.rotation.set(-anglePitchFilter, -angleYawFilter, angleRollFilter, 'YXZ');

        // Calcular el vector de aceleración en coordenadas mundiales
        // Mapeamos los ejes del sensor a Three.js:
        // Sensor X -> World Z, Sensor Y -> World X, Sensor Z -> World Y
        const accLocal = new THREE.Vector3(ay, az, ax);
        // Rotar este vector por la orientación del sensor para obtenerlo en el marco del mundo
        const accWorld = accLocal.clone().applyQuaternion(sensorBody.quaternion);
        gravityArrow.setDirection(accWorld.clone().normalize());
        
        const accMag = Math.sqrt(ax*ax + ay*ay + az*az);
        gravityArrow.setLength(Math.max(0.5, Math.min(3.0, accMag * 1.5)));

        // === Alimentar Gráficos ===
        const tLabel = isLive ? new Date().toLocaleTimeString().slice(-8) : data.timestamp.toFixed(1) + "s";
        
        if (isLive) {
            // Modo Live: Desplazar gráficos
            appendChartData(chartAcc, tLabel, [ax, ay, az], 50);
            appendChartData(chartGyr, tLabel, [gx, gy, gz], 50);
        }
    }

    function setProgressBarWidth(barElement, value, maxVal) {
        // Mapear un valor de -maxVal a +maxVal en un porcentaje de 0% a 100%
        let percent = ((value + maxVal) / (2 * maxVal)) * 100;
        percent = Math.max(0, Math.min(100, percent));
        barElement.style.width = `${percent}%`;
        
        // Cambiar color si está cerca del límite
        if (Math.abs(value) > maxVal * 0.85) {
            barElement.style.backgroundColor = "var(--danger)";
        } else {
            barElement.style.backgroundColor = "";
        }
    }

    function appendChartData(chart, label, values, maxLength) {
        chart.data.labels.push(label);
        for (let i = 0; i < values.length; i++) {
            chart.data.datasets[i].data.push(values[i]);
        }
        
        if (chart.data.labels.length > maxLength) {
            chart.data.labels.shift();
            for (let i = 0; i < values.length; i++) {
                chart.data.datasets[i].data.shift();
            }
        }
        chart.update("none"); // Actualizar sin animaciones para mayor velocidad
    }

    // === Manejo del Canal SSE (Tiempo Real) ===
    function startSSE() {
        if (sseSource) {
            sseSource.close();
        }
        
        resetOrientation();
        
        sseSource = new EventSource("/api/stream");
        
        sseSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.heartbeat) return;
            
            processIMUData(data, true);
            actualizarTelemetriaCalibrada(data);
            actualizarTelemetriaNivelada(data);
        };
        
        sseSource.onerror = (err) => {
            console.error("[SSE] Error en la conexion del flujo de datos:", err);
            stopSSE();
        };
    }

    function stopSSE() {
        if (sseSource) {
            sseSource.close();
            sseSource = null;
        }
    }

    // === Polling del Estado del Servidor ===
    function checkServerStatus() {
        fetch("/api/status")
            .then(res => res.json())
            .then(data => {
                // Actualizar Estado BLE
                bleStatusDot.className = "status-dot";
                
                if (data.ble_status === "connected") {
                    bleStatusDot.classList.add("connected");
                    bleStatusText.innerText = "Conectado";
                    btnConnect.classList.add("hidden");
                    btnDisconnect.classList.remove("hidden");
                    btnSimulate.classList.add("hidden");
                    btnStopSimulate.classList.add("hidden");
                    btnRecord.disabled = false;
                    sourceBadge.className = "sensor-mode-badge live";
                    sourceBadge.innerText = "Modo: En Vivo (SensorTag)";
                    setFreqSelectorEnabled(false);

                    if (!isConnected) {
                        isConnected = true;
                        isSimulating = false;
                        stopPlayback();
                        startSSE();
                    }
                } else if (data.ble_status === "connecting" || data.ble_status === "scanning") {
                    bleStatusDot.classList.add("connecting");
                    bleStatusText.innerText = data.ble_status === "scanning" ? "Escaneando..." : "Conectando...";
                    btnConnect.disabled = true;
                    setFreqSelectorEnabled(false);
                } else if (data.is_simulating) {
                    bleStatusDot.classList.add("simulating");
                    bleStatusText.innerText = "Simulando";
                    btnConnect.classList.add("hidden");
                    btnDisconnect.classList.add("hidden");
                    btnSimulate.classList.add("hidden");
                    btnStopSimulate.classList.remove("hidden");
                    btnRecord.disabled = false;
                    sourceBadge.className = "sensor-mode-badge simulation";
                    sourceBadge.innerText = "Modo: Simulación Activa";
                    setFreqSelectorEnabled(false);

                    if (!isSimulating) {
                        isSimulating = true;
                        isConnected = false;
                        stopPlayback();
                        startSSE();
                    }
                } else {
                    bleStatusDot.classList.add("disconnected");
                    bleStatusText.innerText = data.ble_status === "error" ? "Error BLE" : "Desconectado";
                    btnConnect.classList.remove("hidden");
                    btnConnect.disabled = false;
                    btnDisconnect.classList.add("hidden");
                    btnSimulate.classList.remove("hidden");
                    btnStopSimulate.classList.add("hidden");
                    btnRecord.disabled = true;
                    setFreqSelectorEnabled(true);

                    if (isConnected || isSimulating) {
                        isConnected = false;
                        isSimulating = false;
                        stopSSE();
                        sourceBadge.className = "sensor-mode-badge";
                        sourceBadge.innerText = "Modo: Esperando Datos";
                    }
                }

                // === Fs objetivo vs Fs real medida ===
                // Al conectar al SensorTag de verdad, el firmware puede no honrar
                // la Fs solicitada (ver nota en visualizador_server.py). Por eso
                // siempre mostramos lo medido, no solo lo pedido.
                if (data.sample_rate_target_hz) {
                    activeSampleRateHz = data.sample_rate_actual_hz || data.sample_rate_target_hz;
                    freqLiveBadge.classList.remove("hidden");
                    freqTargetVal.innerText = data.sample_rate_target_hz;
                    freqActualVal.innerText = data.sample_rate_actual_hz != null ? data.sample_rate_actual_hz : "midiendo...";

                    if (data.sample_rate_warning) {
                        freqWarningBox.classList.remove("hidden");
                        freqWarningText.innerText = data.sample_rate_warning;
                    } else {
                        freqWarningBox.classList.add("hidden");
                    }
                } else {
                    freqLiveBadge.classList.add("hidden");
                    freqWarningBox.classList.add("hidden");
                }

                // Sincronizar grabación
                isRecording = data.is_recording;
                if (isRecording) {
                    btnRecord.className = "btn btn-danger";
                    btnRecord.innerHTML = `<i class="fa-solid fa-stop"></i> Detener Grabación`;
                    recStatus.classList.remove("hidden");
                    recCount.innerText = data.recorded_samples;
                    recFilename.disabled = true;
                } else {
                    btnRecord.className = "btn btn-success";
                    btnRecord.innerHTML = `<i class="fa-solid fa-circle-dot"></i> Iniciar Grabación`;
                    recStatus.classList.add("hidden");
                    recFilename.disabled = false;
                }
            })
            .catch(err => console.error("Error al obtener estado del backend:", err));
    }

    // Iniciar el polling del estado cada 1 segundo
    setInterval(checkServerStatus, 1000);
    checkServerStatus();

    // === Selector de Frecuencia de Muestreo ===
    freqButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            if (btn.disabled) return;
            selectedFreqHz = parseInt(btn.getAttribute("data-freq"), 10);
            freqButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
        });
    });

    function setFreqSelectorEnabled(enabled) {
        freqButtons.forEach(b => { b.disabled = !enabled; });
    }

    // === Pestaña de Calibración del Acelerómetro ===
    if (calibFreqSelector) {
        calibFreqSelector.querySelectorAll(".freq-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                calibFreqHz = parseInt(btn.getAttribute("data-freq"), 10);
                calibFreqSelector.querySelectorAll(".freq-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
            });
        });
    }

    calibFolderInput.addEventListener("change", () => {
        // Solo nos interesan los .csv dentro de la carpeta seleccionada
        calibArchivosSeleccionados = Array.from(calibFolderInput.files)
            .filter(f => f.name.toLowerCase().endsWith(".csv"));

        if (calibArchivosSeleccionados.length === 0) {
            calibFolderLista.innerHTML = `<span class="calib-folder-vacia">La carpeta no contiene archivos .csv.</span>`;
            btnCalibProcesar.disabled = true;
            return;
        }

        calibFolderLista.innerHTML = calibArchivosSeleccionados
            .map(f => `<div class="calib-folder-item"><i class="fa-solid fa-file-csv"></i> ${f.name}</div>`)
            .join("");
        btnCalibProcesar.disabled = false;
        calibErrorBox.classList.add("hidden");
    });

    function mostrarErrorCalibracion(mensaje) {
        calibErrorText.innerText = mensaje;
        calibErrorBox.classList.remove("hidden");
        calibResultadoCard.classList.add("hidden");
        calibVerificacionCard.classList.add("hidden");
        calibSustitucionCard.classList.add("hidden");
    }

    function formatearNumero(n) {
        return Number(n).toFixed(6);
    }

    function renderizarResultadoCalibracion(resultado) {
        calibErrorBox.classList.add("hidden");
        ultimoResultadoCalibracion = resultado;

        // Matriz C (3x3)
        let filasC = "";
        for (let i = 0; i < 3; i++) {
            filasC += "<tr>" + resultado.C[i].map(v => `<td>${formatearNumero(v)}</td>`).join("") + "</tr>";
        }
        calibMatrixC.innerHTML = filasC;

        // Vector b (3x1), en m/s^2
        const etiquetasEjes = ["x", "y", "z"];
        let filasB = resultado.b_a.map((v, i) => `<tr><td>b_${etiquetasEjes[i]}</td><td>${formatearNumero(v)}</td></tr>`).join("");
        calibVectorB.innerHTML = filasB;

        calibResultadoCard.classList.remove("hidden");
        calibToggleVivo.checked = false;  // el usuario decide activarla explícitamente

        // Verificación (fórmula de pares)
        const verif = resultado.verificacion_formula_pares;
        let filasV = "<tr><th>Eje</th><th>Escala</th><th>Bias (m/s²)</th></tr>";
        for (const eje of ["x", "y", "z"]) {
            filasV += `<tr><td>${eje}</td><td>${formatearNumero(verif[eje].escala)}</td><td>${formatearNumero(verif[eje].bias_ms2)}</td></tr>`;
        }
        calibVerificacionTabla.innerHTML = filasV;
        calibVerificacionCard.classList.remove("hidden");

        // Verificación por sustitución (C y b aplicados de vuelta a los datos crudos)
        const sust = resultado.verificacion_sustitucion;
        let filasS = "<tr><th>Posición</th><th>Calibrado (m/s²)</th><th>Ideal (m/s²)</th><th>Error (m/s²)</th></tr>";
        for (const pos of ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]) {
            const v = sust[pos];
            const fmt3 = arr => arr.map(x => x.toFixed(4)).join(", ");
            filasS += `<tr><td>${pos}</td><td>${fmt3(v.calibrado_ms2)}</td><td>${fmt3(v.ideal_ms2)}</td><td>${fmt3(v.error_ms2)}</td></tr>`;
        }
        calibSustitucionTabla.innerHTML = filasS;
        calibSustitucionCard.classList.remove("hidden");
    }

    btnCalibProcesar.addEventListener("click", () => {
        if (calibArchivosSeleccionados.length === 0) {
            mostrarErrorCalibracion("Selecciona primero la carpeta con los 6 CSV.");
            return;
        }

        const formData = new FormData();
        calibArchivosSeleccionados.forEach(f => formData.append("archivos", f, f.name));
        formData.append("fs", calibFreqHz);

        btnCalibProcesar.disabled = true;
        btnCalibProcesar.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Procesando...`;

        fetch("/api/calibracion/procesar", { method: "POST", body: formData })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    mostrarErrorCalibracion(data.error || "Error desconocido al procesar la calibración.");
                    return;
                }
                renderizarResultadoCalibracion(data);
            })
            .catch(err => mostrarErrorCalibracion("Error de conexión: " + err))
            .finally(() => {
                btnCalibProcesar.disabled = false;
                btnCalibProcesar.innerHTML = `<i class="fa-solid fa-calculator"></i> Procesar Calibración`;
            });
    });

    btnCalibDescargar.addEventListener("click", () => {
        if (!ultimoResultadoCalibracion) return;
        const payload = {
            C: ultimoResultadoCalibracion.C,
            b_a: ultimoResultadoCalibracion.b_a,
            unidad: "m/s^2",
            fs_hz: ultimoResultadoCalibracion.fs_hz,
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "calibracion.json";
        a.click();
        URL.revokeObjectURL(url);
    });

    // Activar/desactivar que la vista en vivo muestre datos ya calibrados
    calibToggleVivo.addEventListener("change", () => {
        const activar = calibToggleVivo.checked;
        fetch("/api/calibracion/aplicar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ activar }),
        })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    calibToggleVivo.checked = false;
                    mostrarErrorCalibracion(data.error || "No se pudo activar la calibración en vivo.");
                    return;
                }
                actualizarBadgeCalibracionVivo(data.aplicar_calibracion_en_vivo);
            });
    });

    function actualizarBadgeCalibracionVivo(activa) {
        if (activa) {
            calibLiveBadge.innerText = "Calibración aplicada";
            calibLiveBadge.className = "sensor-mode-badge live";
        } else {
            calibLiveBadge.innerText = "Sin calibración aplicada";
            calibLiveBadge.className = "sensor-mode-badge";
            valAxCal.innerText = "0.000";
            valAyCal.innerText = "0.000";
            valAzCal.innerText = "0.000";
        }
    }

    function actualizarTelemetriaCalibrada(data) {
        if (data.acc_x_cal === undefined) {
            if (calibLiveBadge.innerText !== "Sin calibración aplicada") {
                actualizarBadgeCalibracionVivo(false);
            }
            return;
        }
        if (calibLiveBadge.innerText !== "Calibración aplicada") {
            actualizarBadgeCalibracionVivo(true);
        }
        valAxCal.innerText = data.acc_x_cal.toFixed(3);
        valAyCal.innerText = data.acc_y_cal.toFixed(3);
        valAzCal.innerText = data.acc_z_cal.toFixed(3);
    }

    function renderizarResultadoBasico(C, b_a, fs_hz) {
        ultimoResultadoCalibracion = { C, b_a, fs_hz };

        let filasC = "";
        for (let i = 0; i < 3; i++) {
            filasC += "<tr>" + C[i].map(v => `<td>${formatearNumero(v)}</td>`).join("") + "</tr>";
        }
        calibMatrixC.innerHTML = filasC;

        const etiquetasEjes = ["x", "y", "z"];
        calibVectorB.innerHTML = b_a.map((v, i) => `<tr><td>b_${etiquetasEjes[i]}</td><td>${formatearNumero(v)}</td></tr>`).join("");

        calibResultadoCard.classList.remove("hidden");
        // La verificación (fórmula de pares / sustitución) solo está disponible
        // justo después de procesar; en una calibración cargada de disco no se
        // recalcula, así que esas dos tarjetas se dejan ocultas.
    }

    // Al cargar la página, reflejar si el servidor ya tiene una calibración activa
    // (persistida en disco) — no hace falta volver a subir los 6 CSV.
    fetch("/api/calibracion/estado")
        .then(res => res.json())
        .then(data => {
            if (data.tiene_calibracion) {
                renderizarResultadoBasico(data.C, data.b_a, data.fs_hz);
                calibToggleVivo.checked = !!data.aplicar_calibracion_en_vivo;
                actualizarBadgeCalibracionVivo(!!data.aplicar_calibracion_en_vivo);
            }
        })
        .catch(() => {});

    // === Pestaña de Calibración: Nivelación de montaje (fórmula de Rodrigues) ===
    nivelArchivoInput.addEventListener("change", () => {
        const f = nivelArchivoInput.files[0];
        nivelArchivoSeleccionado = f || null;
        nivelArchivoNombre.innerHTML = f
            ? `<div class="calib-folder-item"><i class="fa-solid fa-file-csv"></i> ${f.name}</div>`
            : "Ningún archivo seleccionado.";
        btnNivelProcesar.disabled = !f;
        nivelErrorBox.classList.add("hidden");
    });

    function mostrarErrorNivelacion(mensaje) {
        nivelErrorText.innerText = mensaje;
        nivelErrorBox.classList.remove("hidden");
        nivelResultadoCard.classList.add("hidden");
        nivelVerificacionCard.classList.add("hidden");
    }

    function renderizarResultadoNivelacion(resultado) {
        nivelErrorBox.classList.add("hidden");
        ultimoResultadoNivelacion = resultado;

        let filasR = "";
        for (let i = 0; i < 3; i++) {
            filasR += "<tr>" + resultado.R[i].map(v => `<td>${formatearNumero(v)}</td>`).join("") + "</tr>";
        }
        nivelMatrixR.innerHTML = filasR;
        nivelResultadoCard.classList.remove("hidden");
        nivelToggleVivo.checked = false;  // el usuario decide activarla explícitamente

        const g = resultado.g_rotado_ms2;
        nivelVerificacionTabla.innerHTML = `
            <tr><th>Cantidad</th><th>Valor</th></tr>
            <tr><td>Gravedad rotada (m/s²)</td><td>${g.map(v => v.toFixed(4)).join(", ")}</td></tr>
            <tr><td>Magnitud |g| (m/s²)</td><td>${resultado.magnitud_g_ms2.toFixed(4)}</td></tr>
            <tr><td>Roll inicial</td><td>${resultado.roll_deg.toFixed(2)}°</td></tr>
            <tr><td>Pitch inicial</td><td>${resultado.pitch_deg.toFixed(2)}°</td></tr>
        `;
        nivelVerificacionCard.classList.remove("hidden");
    }

    btnNivelProcesar.addEventListener("click", () => {
        if (!nivelArchivoSeleccionado) {
            mostrarErrorNivelacion("Selecciona primero el CSV con el sensor en reposo.");
            return;
        }

        const formData = new FormData();
        formData.append("archivo", nivelArchivoSeleccionado, nivelArchivoSeleccionado.name);
        formData.append("fs", nivelFsInput.value || 10);
        formData.append("segundos", nivelSegundosInput.value || 2);

        btnNivelProcesar.disabled = true;
        btnNivelProcesar.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Calculando...`;

        fetch("/api/nivelacion/procesar", { method: "POST", body: formData })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    mostrarErrorNivelacion(data.error || "Error desconocido al calcular la nivelación.");
                    return;
                }
                renderizarResultadoNivelacion(data);
            })
            .catch(err => mostrarErrorNivelacion("Error de conexión: " + err))
            .finally(() => {
                btnNivelProcesar.disabled = false;
                btnNivelProcesar.innerHTML = `<i class="fa-solid fa-compass"></i> Calcular R`;
            });
    });

    btnNivelDescargar.addEventListener("click", () => {
        if (!ultimoResultadoNivelacion) return;
        const payload = { R: ultimoResultadoNivelacion.R };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "nivelacion.json";
        a.click();
        URL.revokeObjectURL(url);
    });

    // Activar/desactivar que la vista en vivo muestre datos en el marco del cuerpo
    nivelToggleVivo.addEventListener("change", () => {
        const activar = nivelToggleVivo.checked;
        fetch("/api/nivelacion/aplicar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ activar }),
        })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) {
                    nivelToggleVivo.checked = false;
                    mostrarErrorNivelacion(data.error || "No se pudo activar la nivelación en vivo.");
                    return;
                }
                actualizarBadgeNivelacionVivo(data.aplicar_nivelacion_en_vivo);
            });
    });

    function actualizarBadgeNivelacionVivo(activa) {
        if (activa) {
            nivelLiveBadge.innerText = "Nivelación aplicada";
            nivelLiveBadge.className = "sensor-mode-badge live";
        } else {
            nivelLiveBadge.innerText = "Sin nivelación aplicada";
            nivelLiveBadge.className = "sensor-mode-badge";
            valAxBody.innerText = "0.000";
            valAyBody.innerText = "0.000";
            valAzBody.innerText = "0.000";
            valGxBody.innerText = "0.000";
            valGyBody.innerText = "0.000";
            valGzBody.innerText = "0.000";
        }
    }

    function actualizarTelemetriaNivelada(data) {
        if (data.acc_x_body === undefined) {
            if (nivelLiveBadge.innerText !== "Sin nivelación aplicada") {
                actualizarBadgeNivelacionVivo(false);
            }
            return;
        }
        if (nivelLiveBadge.innerText !== "Nivelación aplicada") {
            actualizarBadgeNivelacionVivo(true);
        }
        valAxBody.innerText = data.acc_x_body.toFixed(3);
        valAyBody.innerText = data.acc_y_body.toFixed(3);
        valAzBody.innerText = data.acc_z_body.toFixed(3);
        valGxBody.innerText = data.gyr_x_body.toFixed(3);
        valGyBody.innerText = data.gyr_y_body.toFixed(3);
        valGzBody.innerText = data.gyr_z_body.toFixed(3);
    }

    // Al cargar la página, reflejar si el servidor ya tiene una nivelación
    // activa (persistida en disco) — no hace falta volver a subir el CSV.
    fetch("/api/nivelacion/estado")
        .then(res => res.json())
        .then(data => {
            if (data.tiene_nivelacion) {
                ultimoResultadoNivelacion = { R: data.R };
                let filasR = "";
                for (let i = 0; i < 3; i++) {
                    filasR += "<tr>" + data.R[i].map(v => `<td>${formatearNumero(v)}</td>`).join("") + "</tr>";
                }
                nivelMatrixR.innerHTML = filasR;
                nivelResultadoCard.classList.remove("hidden");
                nivelToggleVivo.checked = !!data.aplicar_nivelacion_en_vivo;
                actualizarBadgeNivelacionVivo(!!data.aplicar_nivelacion_en_vivo);
            }
        })
        .catch(() => {});

    // ========================================================================
    // Pestaña: Comparación 3D de la Nivelación de Montaje (fórmula de Rodrigues)
    // ========================================================================
    let nivel3dInicializado = false;
    let nivel3dSceneRefs = null;
    let nivel3dAnimando = false;

    const nivel3dBadge = document.getElementById("nivel3d-badge");
    const nivel3dVacio = document.getElementById("nivel3d-vacio");
    const nivel3dDatosDiv = document.getElementById("nivel3d-datos");
    const nivel3dTablaComparacion = document.getElementById("nivel3d-tabla-comparacion");
    const nivel3dTablaEje = document.getElementById("nivel3d-tabla-eje");
    const nivel3dTablaR = document.getElementById("nivel3d-tabla-r");
    const nivel3dSlider = document.getElementById("nivel3d-slider");
    const nivel3dPorcentaje = document.getElementById("nivel3d-porcentaje");
    const btnNivel3dPlay = document.getElementById("btn-nivel3d-play");
    const btnNivel3dReset = document.getElementById("btn-nivel3d-reset");

    // Convierte un vector [x,y,z] en coordenadas del sensor al sistema de
    // coordenadas de Three.js — mismo mapeo que usa el cubo del Dashboard
    // (sensor X -> mundo Z, sensor Y -> mundo X, sensor Z -> mundo Y/arriba).
    function sensorAMundo(v) {
        return new THREE.Vector3(v[1], v[2], v[0]);
    }

    // Construye un cubo "estilo SensorTag" simplificado, con sus 3 flechas de
    // ejes (X rojo, Y verde, Z azul). opacidad < 1 lo deja semitransparente,
    // usado para representar la orientación "cruda" del sensor.
    function crearCuboSensorSimple(colorHex, opacidad) {
        const grupo = new THREE.Group();
        const bodyGeometry = new THREE.BoxGeometry(3, 0.5, 1.5);
        const material = new THREE.MeshStandardMaterial({
            color: colorHex, roughness: 0.6, transparent: opacidad < 1, opacity: opacidad
        });
        const body = new THREE.Mesh(bodyGeometry, material);
        grupo.add(body);

        const arrowX = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 0), 1.5, 0xff4757, 0.3, 0.12);
        const arrowY = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 0), 2.0, 0x2ed573, 0.35, 0.14);
        const arrowZ = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 0), 1.2, 0x1e90ff, 0.25, 0.1);
        if (opacidad < 1) {
            [arrowX, arrowY, arrowZ].forEach(a => {
                a.line.material.transparent = true;
                a.line.material.opacity = 0.45;
                a.cone.material.transparent = true;
                a.cone.material.opacity = 0.45;
            });
        }
        grupo.add(arrowX, arrowY, arrowZ);
        return grupo;
    }

    function inicializarEscenaNivel3D() {
        const container = document.getElementById("nivel3d-container");
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xd6e9fb);

        const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
        camera.position.set(5, 4, 7);
        camera.lookAt(0, 0, 0);

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        container.appendChild(renderer.domElement);

        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.minDistance = 2;
        controls.maxDistance = 15;

        scene.add(new THREE.AmbientLight(0xffffff, 0.6));
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.7);
        dirLight.position.set(5, 10, 7);
        scene.add(dirLight);

        const gridHelper = new THREE.GridHelper(12, 12, 0x3f51b5, 0x1a237e);
        gridHelper.position.y = -2;
        scene.add(gridHelper);

        // Cubo "nivelado" (marco del cuerpo): referencia fija, sin rotación extra
        const cuboNivelado = crearCuboSensorSimple(0x1e293b, 0.95);
        scene.add(cuboNivelado);

        // Cubo "crudo" (orientación real de montaje): se anima con el slider
        const cuboCrudo = crearCuboSensorSimple(0x64748b, 0.45);
        scene.add(cuboCrudo);

        // Eje de rotación k: línea punteada que atraviesa el origen
        const ejeKGeom = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, 0)
        ]);
        const ejeKMat = new THREE.LineDashedMaterial({ color: 0x22d3ee, dashSize: 0.2, gapSize: 0.12, linewidth: 2 });
        const ejeKLinea = new THREE.Line(ejeKGeom, ejeKMat);
        scene.add(ejeKLinea);

        // Flecha de la gravedad medida (fija, no se anima con el slider)
        const flechaGravedad = new THREE.ArrowHelper(
            new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 0), 2.2, 0xf59e0b, 0.35, 0.15
        );
        scene.add(flechaGravedad);

        function animar() {
            requestAnimationFrame(animar);
            controls.update();
            renderer.render(scene, camera);
        }
        animar();

        nivel3dSceneRefs = { scene, camera, renderer, controls, container, cuboCrudo, cuboNivelado, ejeKLinea, flechaGravedad };
        nivel3dInicializado = true;
    }

    // Reconstruye las rotaciones (quaternion "crudo" <-> "nivelado") y los
    // vectores fijos (eje k, gravedad medida) a partir de los datos del backend
    function actualizarEscenaNivel3D(datos) {
        if (!nivel3dSceneRefs) return;
        const { ejeKLinea, flechaGravedad } = nivel3dSceneRefs;

        const ejeMundo = sensorAMundo(datos.eje_k).normalize();
        const thetaRad = datos.theta_deg * Math.PI / 180;

        // qCorreccion equivale a la rotacion R actuando sobre vectores medidos;
        // su inversa representa la inclinacion FISICA real del montaje del sensor
        const qCorreccion = new THREE.Quaternion().setFromAxisAngle(ejeMundo, thetaRad);
        nivel3dSceneRefs.qCrudo = qCorreccion.clone().invert();
        nivel3dSceneRefs.qNivelado = new THREE.Quaternion(); // identidad

        const puntos = [ejeMundo.clone().multiplyScalar(-3), ejeMundo.clone().multiplyScalar(3)];
        ejeKLinea.geometry.setFromPoints(puntos);
        ejeKLinea.computeLineDistances();

        const uMundo = sensorAMundo(datos.g_promedio_calibrado_ms2).normalize();
        flechaGravedad.setDirection(uMundo);

        aplicarProgresoNivel3D(parseInt(nivel3dSlider.value, 10));
    }

    function aplicarProgresoNivel3D(porcentaje) {
        nivel3dPorcentaje.innerText = `${porcentaje}%`;
        if (!nivel3dSceneRefs || !nivel3dSceneRefs.qCrudo) return;
        const t = porcentaje / 100;
        nivel3dSceneRefs.cuboCrudo.quaternion.slerpQuaternions(nivel3dSceneRefs.qCrudo, nivel3dSceneRefs.qNivelado, t);
    }

    function pintarDatosNivel3D(datos) {
        nivel3dVacio.classList.add("hidden");
        nivel3dDatosDiv.classList.remove("hidden");
        nivel3dBadge.innerText = "Nivelación calculada";
        nivel3dBadge.className = "sensor-mode-badge live";

        nivel3dTablaComparacion.innerHTML = `
            <tr><th>Cantidad</th><th>Antes</th><th>Después</th></tr>
            <tr><td>Roll</td><td>${datos.roll_antes_deg.toFixed(2)}°</td><td>${datos.roll_deg.toFixed(2)}°</td></tr>
            <tr><td>Pitch</td><td>${datos.pitch_antes_deg.toFixed(2)}°</td><td>${datos.pitch_deg.toFixed(2)}°</td></tr>
            <tr><td>Gravedad (m/s²)</td>
                <td>${datos.g_promedio_calibrado_ms2.map(v => v.toFixed(3)).join(", ")}</td>
                <td>${datos.g_rotado_ms2.map(v => v.toFixed(3)).join(", ")}</td></tr>
        `;

        nivel3dTablaEje.innerHTML = `
            <tr><td>Eje k</td><td>${datos.eje_k.map(v => v.toFixed(4)).join(", ")}</td></tr>
            <tr><td>Ángulo θ</td><td>${datos.theta_deg.toFixed(2)}°</td></tr>
            <tr><td>|g|</td><td>${datos.magnitud_g_ms2.toFixed(4)} m/s²</td></tr>
        `;

        let filasR = "";
        for (let i = 0; i < 3; i++) {
            filasR += "<tr>" + datos.R[i].map(v => `<td>${formatearNumero(v)}</td>`).join("") + "</tr>";
        }
        nivel3dTablaR.innerHTML = filasR;
    }

    function cargarNivel3D() {
        fetch("/api/nivelacion/estado")
            .then(res => res.json())
            .then(datos => {
                if (!datos.tiene_nivelacion) {
                    nivel3dVacio.classList.remove("hidden");
                    nivel3dDatosDiv.classList.add("hidden");
                    nivel3dBadge.innerText = "Sin nivelación calculada";
                    nivel3dBadge.className = "sensor-mode-badge";
                    return;
                }
                nivel3dSlider.value = 0;
                pintarDatosNivel3D(datos);
                actualizarEscenaNivel3D(datos);
            })
            .catch(() => {});
    }

    nivel3dSlider.addEventListener("input", () => aplicarProgresoNivel3D(parseInt(nivel3dSlider.value, 10)));

    btnNivel3dReset.addEventListener("click", () => {
        nivel3dSlider.value = 0;
        aplicarProgresoNivel3D(0);
    });

    btnNivel3dPlay.addEventListener("click", () => {
        if (nivel3dAnimando) return;
        nivel3dAnimando = true;
        const valorActual = parseInt(nivel3dSlider.value, 10);
        const inicio = valorActual >= 100 ? 0 : valorActual;
        nivel3dSlider.value = inicio;
        aplicarProgresoNivel3D(inicio);

        const duracionMs = 1500;
        const t0 = performance.now();
        function paso(ahora) {
            const frac = Math.min(1, (ahora - t0) / duracionMs);
            const valor = Math.round(inicio + frac * (100 - inicio));
            nivel3dSlider.value = valor;
            aplicarProgresoNivel3D(valor);
            if (frac < 1) {
                requestAnimationFrame(paso);
            } else {
                nivel3dAnimando = false;
            }
        }
        requestAnimationFrame(paso);
    });

    // === Controladores de Eventos del Sensor ===
    btnConnect.addEventListener("click", () => {
        fetch("/api/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ freq: selectedFreqHz })
        })
            .then(res => res.json())
            .then(() => checkServerStatus());
    });

    btnDisconnect.addEventListener("click", () => {
        fetch("/api/disconnect", { method: "POST" })
            .then(res => res.json())
            .then(() => checkServerStatus());
    });

    btnSimulate.addEventListener("click", () => {
        fetch("/api/start_simulation", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ freq: selectedFreqHz })
        })
            .then(res => res.json())
            .then(() => checkServerStatus());
    });

    btnStopSimulate.addEventListener("click", () => {
        fetch("/api/stop_simulation", { method: "POST" })
            .then(res => res.json())
            .then(() => checkServerStatus());
    });

    btnRecord.addEventListener("click", () => {
        if (!isRecording) {
            // Empezar grabación
            const filename = recFilename.value.trim() || "Prueba.csv";
            fetch("/api/start_recording", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename })
            })
            .then(res => res.json())
            .then(() => {
                checkServerStatus();
                btnDownloadExcel.classList.add("hidden");
                // Iniciar cuenta regresiva visual
                let secondsLeft = RECORDING_DURATION_S;
                recCountdown.textContent = `${secondsLeft}s`;
                recCountdown.classList.remove("hidden");
                recordingTimer = setInterval(() => {
                    secondsLeft--;
                    recCountdown.textContent = `${secondsLeft}s`;
                    if (secondsLeft <= 0) {
                        clearInterval(recordingTimer);
                        recordingTimer = null;
                        // Auto-detener grabación
                        stopRecordingAndSave();
                    }
                }, 1000);
            });
        } else {
            // Detener grabación manualmente
            if (recordingTimer) { clearInterval(recordingTimer); recordingTimer = null; }
            recCountdown.classList.add("hidden");
            stopRecordingAndSave();
        }
    });

    function stopRecordingAndSave() {
        fetch("/api/stop_recording", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                recCountdown.classList.add("hidden");
                if (data.samples > 0) {
                    // Mostrar botón de descarga Excel
                    btnDownloadExcel.classList.remove("hidden");
                    btnDownloadExcel.dataset.filename = data.filename;
                    btnDownloadExcel.dataset.freq = data.sample_rate_target_hz || 10;

                    let msg = `✅ Grabación completada\nArchivo CSV: ${data.filename}\nMuestras: ${data.samples}\nDuración: ${data.duration.toFixed(1)} s`;
                    if (data.sample_rate_target_hz) {
                        msg += `\nFs objetivo: ${data.sample_rate_target_hz} Hz | Fs real medida: ${data.sample_rate_actual_hz} Hz`;
                        if (Math.abs(data.sample_rate_actual_hz - data.sample_rate_target_hz) > 1) {
                            msg += `\n⚠️ La Fs real no coincide con la solicitada. Revisa el aviso en el panel de conexión.`;
                        }
                    }
                    alert(msg);

                    // Preseleccionar la Fs correcta en el selector de reproducción
                    if (data.sample_rate_target_hz) {
                        csvFsSelect.value = String(data.sample_rate_target_hz);
                    }
                } else {
                    alert("No se capturaron muestras.");
                }
                checkServerStatus();
                loadCsvFilesList();
            });
    }

    // Botón de descarga Excel
    btnDownloadExcel.addEventListener("click", () => {
        const filename = btnDownloadExcel.dataset.filename;
        const freq = btnDownloadExcel.dataset.freq || 10;
        if (filename) {
            window.location.href = `/api/download_excel/${encodeURIComponent(filename)}?fs=${freq}`;
        }
    });

    // === Carga e Ingesta de Archivos CSV (Offline) ===
    function loadCsvFilesList() {
        fetch("/api/csv_files")
            .then(res => res.json())
            .then(files => {
                csvSelect.innerHTML = `<option value="">-- Seleccionar Ensayo --</option>`;
                files.forEach(f => {
                    csvSelect.innerHTML += `<option value="${f}">${f}</option>`;
                });
            })
            .catch(err => console.error("Error cargando archivos CSV:", err));
    }
    loadCsvFilesList();
    btnRefreshCsv.addEventListener("click", loadCsvFilesList);

    csvSelect.addEventListener("change", () => {
        const filename = csvSelect.value;
        if (!filename) {
            playbackControlsBar.classList.add("hidden");
            stopPlayback();
            csvData = [];
            return;
        }

        // Si estamos en vivo o simulando, preguntar confirmación o desconectar automáticamente
        if (isConnected || isSimulating) {
            if (confirm("Se detendrá el flujo de datos en vivo para reproducir el archivo. ¿Continuar?")) {
                if (isConnected) {
                    fetch("/api/disconnect", { method: "POST" });
                } else {
                    fetch("/api/stop_simulation", { method: "POST" });
                }
            } else {
                csvSelect.value = "";
                return;
            }
        }

        loadSelectedCsv(filename);
    });

    // Si el usuario cambia la Fs de reproducción con un archivo ya cargado,
    // recargar para reconstruir el eje de tiempo correctamente. Los CSV
    // crudos no guardan su Fs de captura, así que esto es necesario para
    // que un archivo grabado a 50Hz no se interprete como si fuera de 10Hz.
    csvFsSelect.addEventListener("change", () => {
        if (csvSelect.value) {
            loadSelectedCsv(csvSelect.value);
        }
    });

    function loadSelectedCsv(filename) {
        const fs = csvFsSelect.value || 10;
        // Cargar los datos del CSV
        fetch(`/api/csv_data/${filename}?fs=${fs}`)
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    alert("Error al cargar datos: " + data.error);
                    return;
                }
                
                csvData = data;
                playbackIndex = 0;
                
                // Configurar controles de reproducción
                playbackControlsBar.classList.remove("hidden");
                playbackScrubber.max = csvData.length - 1;
                playbackScrubber.value = 0;
                
                const duracionTotal = csvData[csvData.length - 1].timestamp - csvData[0].timestamp;
                timeCurrent.innerText = "0.0s";
                timeTotal.innerText = `${duracionTotal.toFixed(1)}s`;
                
                sourceBadge.className = "sensor-mode-badge playback";
                sourceBadge.innerText = `Reproduciendo: ${filename}`;
                
                // Detener cualquier reproducción previa
                stopPlayback();
                
                // Mostrar gráficos completos de una vez
                plotWholeOfflineData();
                
                updateOfflineUI();
            })
            .catch(err => alert("Error cargando archivo: " + err));
    }

    // === Visualización Offline y Fusión en Bloque ===
    function plotWholeOfflineData() {
        const timestamps = csvData.map((d, i) => {
            // Eje X como el tiempo transcurrido
            const t = d.timestamp - csvData[0].timestamp;
            return t.toFixed(2) + "s";
        });
        
        // Gráficos de Acelerómetro
        chartAcc.data.labels = timestamps;
        chartAcc.data.datasets[0].data = csvData.map(d => d.acc_x);
        chartAcc.data.datasets[1].data = csvData.map(d => d.acc_y);
        chartAcc.data.datasets[2].data = csvData.map(d => d.acc_z);
        chartAcc.update();

        // Gráficos de Giroscopio
        chartGyr.data.labels = timestamps;
        chartGyr.data.datasets[0].data = csvData.map(d => d.gyr_x);
        chartGyr.data.datasets[1].data = csvData.map(d => d.gyr_y);
        chartGyr.data.datasets[2].data = csvData.map(d => d.gyr_z);
        chartGyr.update();
    }

    // === Control de la Línea de Reproducción (Cursor) ===
    function updateChartsPlaybackLine(index) {
        const timeLabel = (csvData[index].timestamp - csvData[0].timestamp).toFixed(2) + "s";
        
        // Agregar configuración de línea vertical para Chart.js
        [chartAcc, chartGyr].forEach(chart => {
            if (!chart.config.options.plugins.verticalLine) {
                chart.config.options.plugins.verticalLine = {};
            }
            chart.config.options.plugins.verticalLine.xVal = timeLabel;
            chart.update("none");
        });
    }

    // === Ciclo de Reproducción ===
    function startPlayback() {
        if (isPlaying) return;
        
        isPlaying = true;
        btnPlay.innerHTML = `<i class="fa-solid fa-pause"></i>`;
        
        // El fps de reproducción se deriva del espaciado real entre muestras
        // del archivo cargado (que depende de la Fs elegida en "Fs grabación"),
        // en vez de asumir siempre 10Hz. Así un archivo a 50Hz se reproduce
        // a su velocidad real y no 5x más lento de lo que debería.
        let targetFps = 10;
        if (csvData.length >= 2) {
            const dtDatos = csvData[1].timestamp - csvData[0].timestamp;
            if (dtDatos > 0) targetFps = 1 / dtDatos;
        }
        const intervalMs = (1000 / targetFps) / playbackSpeed;
        
        playbackInterval = setInterval(() => {
            if (playbackIndex >= csvData.length) {
                stopPlayback();
                playbackIndex = 0;
                playbackScrubber.value = 0;
                return;
            }
            
            playbackScrubber.value = playbackIndex;
            updateOfflineUI();
            playbackIndex++;
        }, intervalMs);
    }

    function stopPlayback() {
        isPlaying = false;
        btnPlay.innerHTML = `<i class="fa-solid fa-play"></i>`;
        if (playbackInterval) {
            clearInterval(playbackInterval);
            playbackInterval = null;
        }
    }

    function updateOfflineUI() {
        if (playbackIndex >= csvData.length) return;
        
        const currentSample = csvData[playbackIndex];
        const tZero = csvData[0].timestamp;
        
        timeCurrent.innerText = `${(currentSample.timestamp - tZero).toFixed(1)}s`;
        
        // Alimentar algoritmo de orientación para simular la posición 3D
        // Usamos una función dedicada para la muestra actual que actualiza el objeto Three.js
        // de forma instantánea sin acumular derivas temporales repetidas, o usando los valores precalculados.
        // Un enfoque muy simple es recalcular los ángulos acumulando desde el principio del archivo
        // hasta el playbackIndex actual:
        calculateAnglesUpToIndex(playbackIndex);
        
        // Actualizar la línea de los gráficos
        updateChartsPlaybackLine(playbackIndex);
    }

    // Recalcular los ángulos desde 0 hasta el índice de playback para representar la orientación correcta
    function calculateAnglesUpToIndex(index) {
        let currentRollAcc = 0, currentPitchAcc = 0;
        let currentRollGyro = 0, currentPitchGyro = 0, currentYawGyro = 0;
        let currentRollFilter = 0, currentPitchFilter = 0;
        
        const d0 = csvData[0];
        currentRollAcc = Math.atan2(d0.acc_y, d0.acc_z);
        currentPitchAcc = Math.atan2(-d0.acc_x, Math.sqrt(d0.acc_y * d0.acc_y + d0.acc_z * d0.acc_z));
        currentRollFilter = currentRollAcc;
        currentPitchFilter = currentPitchAcc;

        for (let i = 1; i <= index; i++) {
            const d = csvData[i];
            const dt = d.timestamp - csvData[i-1].timestamp;
            
            currentRollAcc = Math.atan2(d.acc_y, d.acc_z);
            currentPitchAcc = Math.atan2(-d.acc_x, Math.sqrt(d.acc_y * d.acc_y + d.acc_z * d.acc_z));
            
            const gx_val = d.gyr_x - gyroBias.x;
            const gy_val = d.gyr_y - gyroBias.y;
            const gz_val = d.gyr_z - gyroBias.z;
            
            currentRollGyro += gx_val * dt;
            currentPitchGyro += gy_val * dt;
            currentYawGyro += gz_val * dt;
            
            currentRollFilter = alpha * (currentRollFilter + gx_val * dt) + (1 - alpha) * currentRollAcc;
            currentPitchFilter = alpha * (currentPitchFilter + gy_val * dt) + (1 - alpha) * currentPitchAcc;
        }

        // Aplicar rotación
        sensorBody.rotation.set(-currentPitchFilter, -currentYawGyro, currentRollFilter, 'YXZ');
        
        // Actualizar vector gravedad
        const curSample = csvData[index];
        const accLocal = new THREE.Vector3(curSample.acc_y, curSample.acc_z, curSample.acc_x);
        const accWorld = accLocal.clone().applyQuaternion(sensorBody.quaternion);
        gravityArrow.setDirection(accWorld.clone().normalize());
        
        const accMag = Math.sqrt(curSample.acc_x*curSample.acc_x + curSample.acc_y*curSample.acc_y + curSample.acc_z*curSample.acc_z);
        gravityArrow.setLength(Math.max(0.5, Math.min(3.0, accMag * 1.5)));

        // Actualizar telemetría numérica
        valAx.innerText = curSample.acc_x.toFixed(3);
        valAy.innerText = curSample.acc_y.toFixed(3);
        valAz.innerText = curSample.acc_z.toFixed(3);
        valGx.innerText = curSample.gyr_x.toFixed(3);
        valGy.innerText = curSample.gyr_y.toFixed(3);
        valGz.innerText = curSample.gyr_z.toFixed(3);

        setProgressBarWidth(barAx, curSample.acc_x, 2.0);
        setProgressBarWidth(barAy, curSample.acc_y, 2.0);
        setProgressBarWidth(barAz, curSample.acc_z, 2.0);
        setProgressBarWidth(barGx, curSample.gyr_x, 3.0);
        setProgressBarWidth(barGy, curSample.gyr_y, 3.0);
        setProgressBarWidth(barGz, curSample.gyr_z, 3.0);

        valRoll.innerText = `${(currentRollFilter * (180 / Math.PI)).toFixed(1)}°`;
        valPitch.innerText = `${(currentPitchFilter * (180 / Math.PI)).toFixed(1)}°`;
        valYaw.innerText = `${(currentYawGyro * (180 / Math.PI)).toFixed(1)}°`;
    }

    // Play/Pause Botón
    btnPlay.addEventListener("click", () => {
        if (csvData.length === 0) return;
        if (isPlaying) {
            stopPlayback();
        } else {
            startPlayback();
        }
    });

    // Cambiar velocidad de reproducción
    speedSelect.addEventListener("change", (e) => {
        playbackSpeed = parseFloat(e.target.value);
        if (isPlaying) {
            stopPlayback();
            startPlayback();
        }
    });

    // Cambiar scrubber manualmente
    playbackScrubber.addEventListener("input", (e) => {
        if (csvData.length === 0) return;
        playbackIndex = parseInt(e.target.value);
        updateOfflineUI();
    });
});