(function () {
    if (typeof JSON === "undefined" || typeof JSON.stringify === "undefined" || typeof JSON.parse === "undefined") {

        var LocalJSON = {};

        if (typeof JSON === "undefined") {
            JSON = {};
        }

        if (typeof JSON.stringify !== "function") {
            JSON.stringify = function (obj) {
                try {
                    if (obj === null) return "null";
                    if (obj === undefined) return "null";
                    if (typeof obj === "string") return '"' + obj.replace(/"/g, '\\"').replace(/\\/g, '\\\\') + '"';
                    if (typeof obj === "number") {
                        if (isNaN(obj) || !isFinite(obj)) return "null";
                        return obj.toString();
                    }
                    if (typeof obj === "boolean") return obj.toString();
                    if (obj instanceof Array) {
                        var arr = [];
                        for (var i = 0; i < obj.length; i++) {
                            arr.push(JSON.stringify(obj[i]));
                        }
                        return "[" + arr.join(",") + "]";
                    }
                    if (typeof obj === "object") {
                        var props = [];
                        for (var key in obj) {
                            if (obj.hasOwnProperty(key) && obj[key] !== undefined) {
                                props.push('"' + key.replace(/"/g, '\\"') + '":' + JSON.stringify(obj[key]));
                            }
                        }
                        return "{" + props.join(",") + "}";
                    }
                    return "null";
                } catch (e) {
                    return "null";
                }
            };
        }

        if (typeof JSON.parse !== "function") {
            JSON.parse = function (str) {
                try {
                    if (typeof str !== "string") return null;
                    if (str === "" || str === "undefined") return null;

                    str = str.replace(/^\s+|\s+$/g, '');
                    if (str === "") return null;

                    if (!/^[\[\{"]/.test(str) && !/^-?\d/.test(str) && !/^(true|false|null)$/.test(str)) {
                        console.error("JSON no válido, rechazando para seguridad");
                        return null;
                    }

                    try {
                        return new Function("return (" + str + ")")();
                    } catch (e) {
                        console.error("Error al parsear JSON:", e);
                        return null;
                    }
                } catch (e) {
                    return null;
                }
            };
        }
    }
})();

function getHostAppName() {
    try {
        if (typeof app !== 'undefined' && app.appName && app.appName.indexOf("After Effects") > -1) {
            return "Adobe After Effects";
        } else if (typeof $ !== 'undefined' && $.global && $.global.app && $.global.app.isDocumentOpen && $.global.app.isDocumentOpen()) {
            return "Adobe Premiere Pro";
        } else {
            return "unknown";
        }
    } catch (e) {
        return "unknown";
    }
}

function isMacOS() {
    try {
        return $.os.indexOf("Windows") === -1;
    } catch (e) {
        return false;
    }
}

function selectDowPExecutable() {
    try {
        if (isMacOS()) {
            // En macOS DowP es un bundle (DowP.app), que a nivel de sistema de
            // archivos es un directorio. File.openDialog puede devolverlo, pero
            // segun la version de ExtendScript el usuario acaba entrando dentro
            // del paquete; por eso se ofrece primero el selector de carpetas y
            // se repliega al binario interno si eso es lo que eligio.
            var folder = Folder.selectDlg("Selecciona DowP.app");
            if (folder) {
                var fpath = folder.fsName;
                var idx = fpath.indexOf(".app/Contents/MacOS");
                if (idx !== -1) { fpath = fpath.substring(0, idx + 4); }
                return fpath;
            }
            return "cancel";
        }

        var file = File.openDialog("Selecciona el ejecutable de DowP (DowP.exe)");
        if (file) { return file.fsName; }
        return "cancel";
    } catch (e) {
        return "cancel";
    }
}

function executeDowP(path, appIdentifier) {
    // NOTA: esta funcion es el ULTIMO recurso. El lanzamiento normal ocurre en
    // la capa CEP (js/platform.js), que usa Node child_process o
    // cep.process.createProcess y funciona igual en Windows y macOS.
    // ExtendScript solo puede lanzar procesos de forma muy limitada, y en macOS
    // no tiene ninguna via que acepte argumentos.
    $.writeln("DEBUG: executeDowP llamado (fallback)");
    $.writeln("  - Ruta: " + path);
    $.writeln("  - App: " + appIdentifier);

    try {
        if (!isMacOS()) {
            var exeFile = new File(path);
            if (!exeFile.exists) {
                $.writeln("ERROR: No existe: " + path);
                return "Error: no se encontro DowP en la ruta especificada: " + path;
            }

            var scriptFile = new File(Folder.temp.fsName + "/launch_dowp_temp.bat");
            var scriptContent = '@echo off\n' +
                'start "" "' + path + '" "' + appIdentifier + '"\n';

            scriptFile.open("w");
            scriptFile.encoding = "UTF-8";
            scriptFile.write(scriptContent);
            scriptFile.close();

            $.writeln("DEBUG: Ejecutando script batch: " + scriptFile.fsName);
            scriptFile.execute();
            return "success";
        }

        // ── macOS ──
        var isBundle = /\.app$/i.test(path);
        var bundle = isBundle ? new Folder(path) : null;
        var binary = isBundle ? null : new File(path);

        if (isBundle && !bundle.exists) {
            $.writeln("ERROR: No existe el bundle: " + path);
            return "Error: no se encontro DowP.app en: " + path;
        }
        if (!isBundle && !binary.exists) {
            $.writeln("ERROR: No existe: " + path);
            return "Error: no se encontro DowP en: " + path;
        }

        // 2a. After Effects expone system.callSystem(), que si ejecuta shell.
        //     Premiere Pro no lo tiene, de ahi el fallback siguiente.
        try {
            if (typeof system !== "undefined" && system && typeof system.callSystem === "function") {
                var quoted = path.replace(/'/g, "'\\''");
                var cmd = isBundle
                    ? "/usr/bin/open -a '" + quoted + "' --args " + appIdentifier
                    : "'" + quoted + "' " + appIdentifier + " &";
                $.writeln("DEBUG: system.callSystem -> " + cmd);
                system.callSystem(cmd);
                return "success";
            }
        } catch (eSys) {
            $.writeln("DEBUG: system.callSystem fallo: " + eSys.toString());
        }

        // 2b. Folder.execute() sobre un bundle: LaunchServices lo reconoce como
        //     aplicacion y la abre. No admite argumentos, pero DowP no los
        //     necesita para arrancar (el panel se registra despues por socket).
        if (isBundle) {
            $.writeln("DEBUG: Folder.execute() sobre el bundle");
            if (bundle.execute()) { return "success"; }
            return "Error: macOS bloqueo la apertura de DowP.app. Abrelo manualmente una vez para autorizarlo.";
        }

        $.writeln("DEBUG: File.execute() sobre el binario");
        if (binary.execute()) { return "success"; }
        return "Error: no se pudo ejecutar DowP en macOS.";

    } catch (e) {
        $.writeln("ERROR en executeDowP: " + e.toString());
        return "Error al intentar ejecutar DowP: " + e.toString();
    }
}

function getActiveTimelineInfo() {
    var info = {
        hasActiveTimeline: false,
        playheadTime: 0,
        playheadTicks: "0"
    };

    try {
        var host = getHostAppName();
        if (host === "Adobe Premiere Pro") {
            if (app.project && app.project.activeSequence) {
                var sequence = app.project.activeSequence;
                info.hasActiveTimeline = true;
                info.playheadTime = sequence.getPlayerPosition().seconds;
                info.playheadTicks = sequence.getPlayerPosition().ticks;
            }
        } else if (host === "Adobe After Effects") {
            if (app.project && app.project.activeItem && app.project.activeItem instanceof CompItem) {
                var comp = app.project.activeItem;
                try {
                    var currentTime = comp.time;
                    if (comp.width > 0 && comp.height > 0) {
                        info.hasActiveTimeline = true;
                        info.playheadTime = currentTime;
                    }
                } catch (e) {
                    info.hasActiveTimeline = false;
                }
            }
        }
    } catch (e) {
    }

    try {
        return JSON.stringify(info);
    } catch (e) {
        return '{"hasActiveTimeline":false,"playheadTime":0}';
    }
}

function clearCacheForExistingItems(filePath, targetBin) {
    try {
        if (!filePath || !app.project) return;

        for (var i = 1; i <= app.project.numItems; i++) {
            var item = app.project.item(i);
            if (item && item.file && item.file.fsName === filePath) {
                item.replace(item.file);
            }
        }
    } catch (e) {
    }
}

function isFileRecentlyModified(filePath, thresholdMinutes) {
    try {
        var file = new File(filePath);
        if (!file.exists) return false;

        var now = new Date();
        var fileModified = new Date(file.modified);
        var diffMinutes = (now.getTime() - fileModified.getTime()) / (1000 * 60);

        return diffMinutes < (thresholdMinutes || 5);
    } catch (e) {
        return false;
    }
}

function importFiles(fileListJSON, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        var filePaths = null;

        if (!fileListJSON || fileListJSON === "undefined" || fileListJSON === "") {
            return "Error: La lista de archivos está vacía o es inválida.";
        }

        try {
            filePaths = JSON.parse(fileListJSON);
        } catch (e) {
            return "Error: JSON inválido - " + e.toString();
        }

        if (!filePaths || !filePaths.length || filePaths.length === 0) {
            return "Error: La lista de archivos está vacía.";
        }

        var host = getHostAppName();
        if (host === "Adobe After Effects") {
            return importForAfterEffects(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName);
        } else if (host === "Adobe Premiere Pro") {
            return importForPremiere(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName);
        } else {
            return "Error: Aplicación no soportada.";
        }
    } catch (error) {
        return "Error crítico en ExtendScript: " + error.toString();
    }
}

function logToDowP(msg, level) {
    try {
        var xmpLib = new ExternalObject("lib:PlugPlugExternalObject");
        if (xmpLib) {
            var eventObj = new CSXSEvent();
            eventObj.type = "com.dowp.log";
            eventObj.data = JSON.stringify({ message: msg, level: level });
            eventObj.dispatch();
        }
    } catch(e) {}
}

function importSubclips(filePath, subclipsJSON, addToTimeline, playheadTime, playheadTicks) {
    var host = getHostAppName();
    if (host === "Adobe After Effects") {
        return importSubclipsForAfterEffects(filePath, subclipsJSON, addToTimeline, playheadTime);
    } else if (host === "Adobe Premiere Pro") {
        return importSubclipsForPremiere(filePath, subclipsJSON, addToTimeline, playheadTime);
    } else {
        return "Error: Aplicación no soportada.";
    }
}

// --- Recorte de subclips en la línea de tiempo de After Effects ---
// AE no tiene equivalente a ProjectItem.createSubclip() (eso es exclusivo del DOM de Premiere).
// En cambio, se importa el footage completo UNA sola vez y, por cada subclip pedido,
// se crea una capa nueva a partir del mismo FootageItem, recortada con inPoint/outPoint.
function importSubclipsForAfterEffects(filePath, subclipsJSON, addToTimeline, playheadTime) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en After Effects.";

        var subclips = JSON.parse(subclipsJSON);
        if (!subclips || !subclips.length) return "Error: Lista de subclips vacía.";

        // El recorte de subclips solo tiene sentido a nivel de capa en una
        // composición. Si no se pide timeline (o no hay comp activa), no se
        // descarta el medio: se importa completo al bin DowP Imports, igual
        // que un archivo normal, y ahí se queda para uso manual.
        var comp = app.project.activeItem;
        var canTrimOnTimeline = addToTimeline && comp && (comp instanceof CompItem);

        app.beginUndoGroup("Importar subclips desde DowP");

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item.name === mainBinName && item instanceof FolderItem) {
                mainBin = item;
                break;
            }
        }
        if (mainBin === null) {
            mainBin = project.items.addFolder(mainBinName);
        }

        // Importar el footage base una sola vez (todas las capas de subclip
        // se generan a partir de este mismo FootageItem)
        var importedItem = null;
        try {
            var importOptions = new ImportOptions(new File(filePath));
            if (importOptions.canImportAs && importOptions.canImportAs(ImportAsType.FOOTAGE)) {
                importOptions.importAs = ImportAsType.FOOTAGE;
            }
            importOptions.sequence = false;
            importedItem = project.importFile(importOptions);
        } catch (eImp) {
            app.endUndoGroup();
            return "Error importando el archivo base: " + eImp.toString();
        }

        if (!importedItem) {
            app.endUndoGroup();
            return "Error: No se pudo importar el archivo base.";
        }

        var lowerPath = filePath.toLowerCase();
        var folderName = "Video";
        if (/\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(lowerPath)) {
            folderName = "Imágenes";
        } else if (/\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath) || (importedItem.hasAudio && !importedItem.hasVideo)) {
            folderName = "Audio";
        }
        var subFolder = getOrCreateSubFolder(mainBin, folderName);
        importedItem.parentFolder = subFolder;

        if (importedItem.file && importedItem.file.exists) {
            try { importedItem.replace(importedItem.file); } catch (e_rep) { }
        }

        // Sin timeline activa (o sin comp activa): el medio ya quedó
        // importado completo en DowP Imports. No se recorta nada, pero
        // tampoco se descarta.
        if (!canTrimOnTimeline) {
            app.endUndoGroup();
            return "success";
        }

        var cursorTime = playheadTime || 0;
        var createdCount = 0;

        for (var s = 0; s < subclips.length; s++) {
            var sc = subclips[s];
            var inPt = sc["in"] || 0;
            var outPt = sc["out"] || 0;
            var duration = outPt - inPt;

            if (duration <= 0) continue;

            try {
                var newLayer = comp.layers.add(importedItem);

                // startTime es solo el punto de referencia teórico (frame 0 del
                // source); el recorte visible real lo definen inPoint/outPoint.
                newLayer.startTime = cursorTime - inPt;
                newLayer.inPoint = cursorTime;
                newLayer.outPoint = cursorTime + duration;

                if (sc.name) {
                    try { newLayer.name = sc.name; } catch (eName) { }
                }

                createdCount++;
                cursorTime += duration; // siguiente subclip, sin encimarse
            } catch (errLayer) {
                $.writeln("[AE Subclips] Error creando capa para subclip " + s + ": " + errLayer.toString());
            }
        }

        try { comp.openInViewer(); } catch (eView) { }

        app.endUndoGroup();

        if (createdCount === 0) {
            // El footage ya se importó igual; no lo tratamos como fallo total.
            return "success";
        }
        return "success";
    } catch (err) {
        try { app.endUndoGroup(); } catch (e) { }
        return "Error creando subclips en After Effects: " + err.toString();
    }
}

function importSubclipsForPremiere(filePath, subclipsJSON, addToTimeline, playheadTime, playheadTicks) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en Premiere Pro.";
        
        logToDowP("Iniciando importSubclipsForPremiere", "info");

        var subclips = JSON.parse(subclipsJSON);
        if (!subclips || !subclips.length) return "Error: Lista de subclips vacía.";

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 0; i < project.rootItem.children.numItems; i++) {
            var item = project.rootItem.children[i];
            if (item.name === mainBinName && item.type === ProjectItemType.BIN) {
                mainBin = item;
                break;
            }
        }
        if (!mainBin) {
            mainBin = project.rootItem.createBin(mainBinName);
        }

        var uidsBefore = getItemUIDs(mainBin);
        project.importFiles([filePath], true, mainBin, false);

        var importedMainItem = null;
        for (var j = 0; j < mainBin.children.numItems; j++) {
            var it = mainBin.children[j];
            if (!uidsBefore.hasOwnProperty(it.nodeId)) {
                importedMainItem = it;
                break;
            }
        }
        if (!importedMainItem) {
            var fname = filePath.substring(Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\')) + 1);
            for (var k = 0; k < mainBin.children.numItems; k++) {
                if (mainBin.children[k].name === fname) {
                    importedMainItem = mainBin.children[k];
                    break;
                }
            }
        }

        if (!importedMainItem) return "Error: No se pudo importar el archivo base.";

        var createdCount = 0;
        var accumulatedTicks = 0;
        var TICKS_PER_SECOND = 254016000000;
        
        var basePlayheadTicks = playheadTicks ? parseInt(playheadTicks, 10) : Math.round(playheadTime * TICKS_PER_SECOND);
        logToDowP("Base Playhead Ticks: " + basePlayheadTicks, "info");

        // Determinar la pista destino UNA SOLA VEZ para todos los subclips
        var targetVideoTrackIndex = -1;
        var targetAudioTrackIndex = -1;
        var firstClipForDetection = importedMainItem;
        
        for (var s = 0; s < subclips.length; s++) {
            var sc = subclips[s];
            var scName = sc.name || ("Subclip_" + (s + 1));
            var inPt = sc.in || 0;
            var outPt = sc.out || 0;

            // Calcular la duración real de ESTE subclip en ticks
            var subclipDurationTicks = Math.round((outPt - inPt) * TICKS_PER_SECOND);

            try {
                var subclipItem = importedMainItem.createSubclip(scName, inPt, outPt, 1, 1, 1);
                if (subclipItem) {
                    createdCount++;
                    if (addToTimeline && project.activeSequence) {
                        var pTime = new Time();
                        var currentInsertTicks = basePlayheadTicks + accumulatedTicks;
                        pTime.ticks = String(currentInsertTicks);
                        logToDowP("Subclip " + s + " inserting at ticks: " + currentInsertTicks, "info");

                        // Para el primer subclip, encontrar la pista. Para los siguientes, reutilizar.
                        if (s === 0) {
                            var avDetection = detectAVviaXMP(subclipItem);
                            if (avDetection.video && avDetection.audio) {
                                // Buscar par AV, pero usando duración real del subclip
                                targetVideoTrackIndex = findAvailableAVPairWithDuration(project.activeSequence, pTime, outPt - inPt);
                                if (targetVideoTrackIndex >= 0) {
                                    logToDowP("Subclips: Pista AV seleccionada = V" + (targetVideoTrackIndex + 1), "info");
                                    project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(subclipItem, pTime);
                                } else {
                                    // Crear pista nueva
                                    handleMixedClipInsert(project.activeSequence, pTime, subclipItem);
                                    // Averiguar en qué pista quedó
                                    targetVideoTrackIndex = findTrackContainingClipAt(project.activeSequence, pTime);
                                    logToDowP("Subclips: Pista AV nueva = V" + (targetVideoTrackIndex + 1), "info");
                                }
                            } else if (avDetection.video) {
                                var vTrack = findAvailableVideoTrack(project.activeSequence, pTime, subclipItem);
                                if (vTrack) {
                                    vTrack.overwriteClip(subclipItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.videoTracks.numTracks; ti++) {
                                        if (project.activeSequence.videoTracks[ti] === vTrack) { targetVideoTrackIndex = ti; break; }
                                    }
                                }
                            } else if (avDetection.audio) {
                                var aTrack = findAvailableAudioTrack(project.activeSequence, pTime, subclipItem);
                                if (aTrack) {
                                    aTrack.overwriteClip(subclipItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.audioTracks.numTracks; ti++) {
                                        if (project.activeSequence.audioTracks[ti] === aTrack) { targetAudioTrackIndex = ti; break; }
                                    }
                                }
                            }
                        } else {
                            // Subclips posteriores: usar la misma pista
                            if (targetVideoTrackIndex >= 0 && project.activeSequence.videoTracks[targetVideoTrackIndex]) {
                                logToDowP("Subclip " + s + " -> misma pista V" + (targetVideoTrackIndex + 1), "info");
                                project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(subclipItem, pTime);
                            } else if (targetAudioTrackIndex >= 0 && project.activeSequence.audioTracks[targetAudioTrackIndex]) {
                                logToDowP("Subclip " + s + " -> misma pista A" + (targetAudioTrackIndex + 1), "info");
                                project.activeSequence.audioTracks[targetAudioTrackIndex].overwriteClip(subclipItem, pTime);
                            } else {
                                // Fallback: buscar pista como antes
                                handleMixedClipInsert(project.activeSequence, pTime, subclipItem);
                            }
                        }
                    }
                }
            } catch (errSub) {
                try {
                    importedMainItem.setInPoint(inPt, 4);
                    importedMainItem.setOutPoint(outPt, 4);
                    if (addToTimeline && project.activeSequence) {
                        var pTime = new Time();
                        var currentInsertTicks = basePlayheadTicks + accumulatedTicks;
                        pTime.ticks = String(currentInsertTicks);
                        logToDowP("Subclip " + s + " (fallback) inserting at ticks: " + currentInsertTicks, "info");

                        if (s === 0) {
                            var avDetection = detectAVviaXMP(importedMainItem);
                            if (avDetection.video && avDetection.audio) {
                                targetVideoTrackIndex = findAvailableAVPairWithDuration(project.activeSequence, pTime, outPt - inPt);
                                if (targetVideoTrackIndex >= 0) {
                                    logToDowP("Subclips (fallback): Pista AV seleccionada = V" + (targetVideoTrackIndex + 1), "info");
                                    project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(importedMainItem, pTime);
                                } else {
                                    handleMixedClipInsert(project.activeSequence, pTime, importedMainItem);
                                    targetVideoTrackIndex = findTrackContainingClipAt(project.activeSequence, pTime);
                                    logToDowP("Subclips (fallback): Pista AV nueva = V" + (targetVideoTrackIndex + 1), "info");
                                }
                            } else if (avDetection.video) {
                                var vTrack = findAvailableVideoTrack(project.activeSequence, pTime, importedMainItem);
                                if (vTrack) {
                                    vTrack.overwriteClip(importedMainItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.videoTracks.numTracks; ti++) {
                                        if (project.activeSequence.videoTracks[ti] === vTrack) { targetVideoTrackIndex = ti; break; }
                                    }
                                }
                            } else if (avDetection.audio) {
                                var aTrack = findAvailableAudioTrack(project.activeSequence, pTime, importedMainItem);
                                if (aTrack) {
                                    aTrack.overwriteClip(importedMainItem, pTime);
                                    for (var ti = 0; ti < project.activeSequence.audioTracks.numTracks; ti++) {
                                        if (project.activeSequence.audioTracks[ti] === aTrack) { targetAudioTrackIndex = ti; break; }
                                    }
                                }
                            }
                        } else {
                            if (targetVideoTrackIndex >= 0 && project.activeSequence.videoTracks[targetVideoTrackIndex]) {
                                logToDowP("Subclip " + s + " (fallback) -> misma pista V" + (targetVideoTrackIndex + 1), "info");
                                project.activeSequence.videoTracks[targetVideoTrackIndex].overwriteClip(importedMainItem, pTime);
                            } else if (targetAudioTrackIndex >= 0 && project.activeSequence.audioTracks[targetAudioTrackIndex]) {
                                logToDowP("Subclip " + s + " (fallback) -> misma pista A" + (targetAudioTrackIndex + 1), "info");
                                project.activeSequence.audioTracks[targetAudioTrackIndex].overwriteClip(importedMainItem, pTime);
                            } else {
                                handleMixedClipInsert(project.activeSequence, pTime, importedMainItem);
                            }
                        }
                    }
                    createdCount++;
                } catch (e2) { }
            }
            
            var addedTicks = Math.round((outPt - inPt) * TICKS_PER_SECOND);
            if (subclipItem) {
                try {
                    var iT = subclipItem.getInPoint();
                    var oT = subclipItem.getOutPoint();
                    if (iT && oT) addedTicks = parseInt(oT.ticks, 10) - parseInt(iT.ticks, 10);
                } catch(e) {}
            } else if (importedMainItem) {
                try {
                    var iT2 = importedMainItem.getInPoint();
                    var oT2 = importedMainItem.getOutPoint();
                    if (iT2 && oT2) addedTicks = parseInt(oT2.ticks, 10) - parseInt(iT2.ticks, 10);
                } catch(e) {}
            }
            logToDowP("Subclip " + s + " addedTicks: " + addedTicks, "info");
            accumulatedTicks += addedTicks;
        }

        // ── Limpieza post-inserción: eliminar fotogramas fantasma ──
        if (addToTimeline && project.activeSequence && targetVideoTrackIndex >= 0) {
            try {
                var expectedEndTicks = basePlayheadTicks + accumulatedTicks;
                var expectedEndSeconds = expectedEndTicks / TICKS_PER_SECOND;
                var cleanupTrack = project.activeSequence.videoTracks[targetVideoTrackIndex];
                var FRAME_THRESHOLD = 0.12; // ~3 fotogramas a 29.97fps

                logToDowP("Limpieza: Buscando fantasmas después de " + expectedEndSeconds + "s en V" + (targetVideoTrackIndex + 1), "info");

                // Recorrer clips del track de atrás hacia adelante para poder eliminar sin romper índices
                for (var c = cleanupTrack.clips.numItems - 1; c >= 0; c--) {
                    var tlClip = cleanupTrack.clips[c];
                    var clipStart = tlClip.start.seconds;
                    var clipDur = tlClip.end.seconds - clipStart;

                    // Solo buscar clips que empiecen en o después de la zona esperada de fin
                    if (clipStart >= expectedEndSeconds - FRAME_THRESHOLD && clipDur < FRAME_THRESHOLD) {
                        logToDowP("Limpieza: Eliminando fantasma '" + tlClip.name + "' (dur: " + clipDur.toFixed(4) + "s) en " + clipStart.toFixed(4) + "s", "info");
                        tlClip.remove(true, true);
                    }
                }

                // También limpiar la pista de audio correspondiente
                if (targetVideoTrackIndex < project.activeSequence.audioTracks.numTracks) {
                    var cleanupAudioTrack = project.activeSequence.audioTracks[targetVideoTrackIndex];
                    for (var c = cleanupAudioTrack.clips.numItems - 1; c >= 0; c--) {
                        var tlClip = cleanupAudioTrack.clips[c];
                        var clipStart = tlClip.start.seconds;
                        var clipDur = tlClip.end.seconds - clipStart;

                        if (clipStart >= expectedEndSeconds - FRAME_THRESHOLD && clipDur < FRAME_THRESHOLD) {
                            logToDowP("Limpieza Audio: Eliminando fantasma '" + tlClip.name + "' (dur: " + clipDur.toFixed(4) + "s)", "info");
                            tlClip.remove(true, true);
                        }
                    }
                }
            } catch (cleanupErr) {
                logToDowP("Limpieza: Error - " + cleanupErr.toString(), "error");
            }
        }

        return "success";
    } catch (err) {
        return "Error creando subclips en Premiere: " + err.toString();
    }
}

function getTrackIndex(trackCollection, track) {
    try {
        for (var i = 0; i < trackCollection.numTracks; i++) {
            if (trackCollection[i] === track) {
                return i;
            }
        }
    } catch (e) {
    }
    return -1;
}

function importForPremiere(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en Premiere Pro.";

        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 0; i < project.rootItem.children.numItems; i++) {
            var item = project.rootItem.children[i];
            if (item.name === mainBinName && item.type === ProjectItemType.BIN) {
                mainBin = item;
                break;
            }
        }

        if (mainBin === null) {
            mainBin = project.rootItem.createBin(mainBinName);
        }

        var targetBin = mainBin;

        // Ignoramos targetBinName para evitar carpetas redundantes

        var importSucceeded = false;
        var maxRetries = 3;
        var retryDelay = 750; // 0.75 segundos de espera entre reintentos

        // Guardar los UIDs *antes* de cualquier intento
        var uidsBeforeImport = getItemUIDs(targetBin);

        for (var attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                // Pausa preventiva. Aumenta en cada intento.
                // Intento 1: 500ms (para sumar al cooldown de Python)
                // Intento 2: 750ms
                // Intento 3: 1500ms
                var currentDelay = (attempt === 1) ? 500 : (retryDelay * (attempt - 1));
                $.sleep(currentDelay);

                $.writeln("[Premiere] Intento de importación en lote " + attempt + "/" + maxRetries + " (Pausa: " + currentDelay + "ms)");

                // El comando de importación en lote (el que queremos conservar)
                project.importFiles(filePaths, true, targetBin, false);

                // Si no lanzó una excepción, ¡éxito!
                importSucceeded = true;
                $.writeln("[Premiere] ¡Importación en lote exitosa en el intento " + attempt + "!");
                break; // Salir del bucle de reintento

            } catch (e) {
                $.writeln("[Premiere ERROR] Intento " + attempt + " falló: " + e.toString());
                if (attempt === maxRetries) {
                    // Si fallan todos los reintentos, lanzamos el error
                    throw new Error("Fallaron todos los reintentos de importación. Error: " + e.toString());
                }
                // Si no es el último intento, el bucle continuará y reintentará.
            }
        }

        if (!importSucceeded) {
            return "Error: La importación en lote falló después de " + maxRetries + " intentos.";
        }

        // 1. Identificar nuevos elementos importados
        var newItems = [];
        for (var k = 0; k < targetBin.children.numItems; k++) {
            var item = targetBin.children[k];
            if (!uidsBeforeImport.hasOwnProperty(item.nodeId)) {
                newItems.push(item);
            }
        }

        // 2. Insertar en Timeline (si se solicitó)
        if (addToTimeline && newItems.length > 0) {
            var sequence = app.project.activeSequence;
            if (sequence) {
                var playheadTimeObject = new Time();
                playheadTimeObject.seconds = playheadTime || 0;

                for (var n = 0; n < newItems.length; n++) {
                    var currentItem = newItems[n];
                    var avDetection = detectAVviaXMP(currentItem);

                    var mediaPath = "";
                    try { mediaPath = currentItem.getMediaPath().toLowerCase(); } catch (e) { mediaPath = ""; }
                    var isAudioFile = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(mediaPath);
                    var isImage = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(mediaPath);

                    if (avDetection.video && avDetection.audio) {
                        handleMixedClipInsert(sequence, playheadTimeObject, currentItem);
                    } else if (avDetection.video && !avDetection.audio) {
                        if (!importImagesToTimeline && isImage) {
                            continue;
                        }
                        var vTrack = findAvailableVideoTrack(sequence, playheadTimeObject, currentItem);
                        if (vTrack) {
                            vTrack.insertClip(currentItem, playheadTimeObject);
                        }
                    } else if (!avDetection.video && avDetection.audio) {
                        var aTrack = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                        if (aTrack) {
                            aTrack.insertClip(currentItem, playheadTimeObject);
                        }
                    } else if (!avDetection.video && !avDetection.audio) {
                        if (isAudioFile) {
                            var aTrack = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                            if (aTrack) {
                                aTrack.insertClip(currentItem, playheadTimeObject);
                            }
                        } else if (!isImage) {
                            var vTrack = findAvailableVideoTrack(sequence, playheadTimeObject, currentItem);
                            if (vTrack) {
                                vTrack.insertClip(currentItem, playheadTimeObject);
                            } else {
                                var aTrack2 = findAvailableAudioTrack(sequence, playheadTimeObject, currentItem);
                                if (aTrack2) {
                                    aTrack2.insertClip(currentItem, playheadTimeObject);
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. Organizar en subcarpetas inteligentes directamente en la raíz de DowP
        for (var m = 0; m < newItems.length; m++) {
            var itemToMove = newItems[m];
            var type = "Video";
            var av = detectAVviaXMP(itemToMove);

            var mPath = "";
            try { mPath = itemToMove.getMediaPath().toLowerCase(); } catch (e) { mPath = ""; }

            var isImageFile = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(mPath);
            var isAudioExt = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(mPath);

            if (isImageFile) {
                type = "Imágenes";
            } else if (isAudioExt || (av.audio && !av.video)) {
                type = "Audio";
            } else if (av.video) {
                type = "Video";
            }

            var subBin = getOrCreateSubBin(mainBin, type);
            if (subBin && subBin !== itemToMove.parentBin) {
                itemToMove.moveBin(subBin);
            }
        }

        return "success";
    } catch (error) {
        return "Error en importForPremiere: " + error.toString();
    }
}

function findAvailableVideoTrack(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        for (var i = 0; i < sequence.videoTracks.numTracks; i++) {
            var currentTrack = sequence.videoTracks[i];
            var isRangeFree = true;
            for (var j = 0; j < currentTrack.clips.numItems; j++) {
                var currentClip = currentTrack.clips[j];
                var EPSILON = 0.04; // Aumentado a 40ms (1 fotograma)
                if (!(clipEndTime <= currentClip.start.seconds + EPSILON || playheadTimeObject.seconds >= currentClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión Video V" + (i + 1) + " con clip '" + currentClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + currentClip.end.seconds + ")", "info");
                    isRangeFree = false;
                    break;
                }
            }
            if (isRangeFree) {
                logToDowP("findAvailableVideoTrack: Asignando a pista V" + (i + 1), "info");
                return currentTrack;
            } else {
                logToDowP("findAvailableVideoTrack: Pista V" + (i + 1) + " ocupada por colisión.", "info");
            }
        }

        var qeSequence = qe.project.getActiveSequence();
        if (qeSequence) {
            var currentVideoTrackCount = sequence.videoTracks.numTracks;
            qeSequence.addTracks(1, currentVideoTrackCount, 0, 0, 0);
            app.project.activeSequence = app.project.activeSequence;
            return sequence.videoTracks[currentVideoTrackCount];
        }
    } catch (e) {
        return null;
    }

    return null;
}

function findAvailableAVPairWithDuration(sequence, playheadTimeObject, durationSeconds) {
    try {
        var clipEndTime = playheadTimeObject.seconds + durationSeconds;
        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var maxPairs = Math.min(numV, numA);

        for (var i = 0; i < maxPairs; i++) {
            var vTrack = sequence.videoTracks[i];
            var videoFree = true;
            for (var j = 0; j < vTrack.clips.numItems; j++) {
                var vClip = vTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= vClip.start.seconds + EPSILON || playheadTimeObject.seconds >= vClip.end.seconds - EPSILON)) {
                    logToDowP("findAVPairWD: Colisión V" + (i + 1) + " con '" + vClip.name + "' (ClipEnd:" + clipEndTime + " vs ClipStart:" + vClip.start.seconds + ", Playhead:" + playheadTimeObject.seconds + " vs ClipEnd:" + vClip.end.seconds + ")", "info");
                    videoFree = false;
                    break;
                }
            }
            if (!videoFree) continue;

            var aTrack = sequence.audioTracks[i];
            var audioFree = true;
            if (aTrack) {
                for (var k = 0; k < aTrack.clips.numItems; k++) {
                    var aClip = aTrack.clips[k];
                    var EPSILON = 0.04;
                    if (!(clipEndTime <= aClip.start.seconds + EPSILON || playheadTimeObject.seconds >= aClip.end.seconds - EPSILON)) {
                        logToDowP("findAVPairWD: Colisión A" + (i + 1) + " con '" + aClip.name + "'", "info");
                        audioFree = false;
                        break;
                    }
                }
            }
            if (audioFree) {
                logToDowP("findAVPairWD: Par libre en V" + (i + 1) + "/A" + (i + 1), "info");
                return i;
            }
        }
    } catch (e) {
        logToDowP("findAVPairWD: Error - " + e.toString(), "error");
        return -1;
    }
    logToDowP("findAVPairWD: No se encontró par libre.", "info");
    return -1;
}

function findTrackContainingClipAt(sequence, playheadTimeObject) {
    try {
        var EPSILON = 0.04;
        for (var i = sequence.videoTracks.numTracks - 1; i >= 0; i--) {
            var track = sequence.videoTracks[i];
            for (var j = 0; j < track.clips.numItems; j++) {
                var clip = track.clips[j];
                if (Math.abs(clip.start.seconds - playheadTimeObject.seconds) < EPSILON) {
                    return i;
                }
            }
        }
    } catch (e) {}
    return 0;
}

function detectNeededAudioTracks(projectItem) {
    try {
        var xmp = projectItem.getProjectMetadata() || "";
        var m = xmp.match(/(\d+)\s*(?:canal(es)?|channels?)/i);
        if (m && m[1]) {
            var count = parseInt(m[1], 10);
            if (!isNaN(count) && count > 0) {
                return (count <= 2) ? 1 : Math.ceil(count / 2);
            }
        }
        if (/stereo|estéreo|estereo/i.test(xmp)) return 1;
        if (/mono/i.test(xmp)) return 1;
        if (/5\.1|5.1/i.test(xmp)) return 1;
    } catch (e) {
    }
    return 1;
}

function findAvailableAVPair(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var neededAudioTracks = detectNeededAudioTracks(mediaItem);

        var maxPairs = Math.min(numV, Math.max(0, numA - (neededAudioTracks - 1)));

        for (var i = 0; i < maxPairs; i++) {
            var vTrack = sequence.videoTracks[i];
            var videoFree = true;
            for (var j = 0; j < vTrack.clips.numItems; j++) {
                var vClip = vTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= vClip.start.seconds + EPSILON || playheadTimeObject.seconds >= vClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión AV-Video V" + (i + 1) + " con clip '" + vClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + vClip.end.seconds + ")", "info");
                    videoFree = false;
                    break;
                }
            }
            if (!videoFree) continue;

            var audioOk = true;
            for (var aOff = 0; aOff < neededAudioTracks; aOff++) {
                var ai = i + aOff;
                var aTrack = sequence.audioTracks[ai];
                if (!aTrack) {
                    audioOk = false;
                    break;
                }
                for (var k = 0; k < aTrack.clips.numItems; k++) {
                    var aClip = aTrack.clips[k];
                    var EPSILON = 0.04;
                    if (!(clipEndTime <= aClip.start.seconds + EPSILON || playheadTimeObject.seconds >= aClip.end.seconds - EPSILON)) {
                        logToDowP("Colisión AV-Audio A" + (ai + 1) + " con clip '" + aClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + aClip.end.seconds + ")", "info");
                        audioOk = false;
                        break;
                    }
                }
                if (!audioOk) {
                    logToDowP("findAvailableAVPair: Par AV (V" + (i + 1) + ") ocupado en pistas de audio.", "info");
                    break;
                }
            }
            if (audioOk) {
                logToDowP("findAvailableAVPair: Asignando par AV en V" + (i + 1), "info");
                return i;
            }
        }
    } catch (e) {
        logToDowP("findAvailableAVPair: Error interno - " + e.toString(), "error");
        return -1;
    }

    logToDowP("findAvailableAVPair: No se encontró par libre, se crearán pistas.", "info");
    return -1;
}

function handleMixedClipInsert(sequence, playheadTimeObject, mediaItem) {
    try {
        var qeSequence = null;
        try {
            qeSequence = qe.project.getActiveSequence();
        } catch (e) {
            qeSequence = null;
        }

        var neededAudioTracks = detectNeededAudioTracks(mediaItem);
        var freeIndex = findAvailableAVPair(sequence, playheadTimeObject, mediaItem);

        if (freeIndex >= 0) {
            sequence.videoTracks[freeIndex].insertClip(mediaItem, playheadTimeObject);
            return;
        }

        var numV = sequence.videoTracks.numTracks;
        var numA = sequence.audioTracks.numTracks;
        var desiredIndex = Math.max(numV, numA);

        var needVideoToAdd = Math.max(0, (desiredIndex + 1) - numV);
        var needAudioToAdd = Math.max(0, (desiredIndex + neededAudioTracks) - numA);

        if (qeSequence) {
            if (needVideoToAdd > 0) {
                qeSequence.addTracks(needVideoToAdd, numV, 0, 0, 0);
            }
            if (needAudioToAdd > 0) {
                var baseType = 1;
                var currentAudioCount = sequence.audioTracks.numTracks;
                qeSequence.addTracks(0, 0, needAudioToAdd, baseType, currentAudioCount);
            }
            app.project.activeSequence = app.project.activeSequence;
        }

        var newVIndex = Math.max(desiredIndex, sequence.videoTracks.numTracks - 1);
        sequence.videoTracks[newVIndex].insertClip(mediaItem, playheadTimeObject);
    } catch (e) {
    }
}

function findAvailableAudioTrack(sequence, playheadTimeObject, mediaItem) {
    try {
        var clipDuration = getClipDuration(mediaItem);
        var clipEndTime = playheadTimeObject.seconds + clipDuration;

        for (var i = 0; i < sequence.audioTracks.numTracks; i++) {
            var currentTrack = sequence.audioTracks[i];
            var isRangeFree = true;
            for (var j = 0; j < currentTrack.clips.numItems; j++) {
                var currentClip = currentTrack.clips[j];
                var EPSILON = 0.04;
                if (!(clipEndTime <= currentClip.start.seconds + EPSILON || playheadTimeObject.seconds >= currentClip.end.seconds - EPSILON)) {
                    logToDowP("Colisión Audio A" + (i + 1) + " con clip '" + currentClip.name + "'. (Playhead: " + playheadTimeObject.seconds + ", End: " + currentClip.end.seconds + ")", "info");
                    isRangeFree = false;
                    break;
                }
            }
            if (isRangeFree) {
                logToDowP("findAvailableAudioTrack: Asignando a pista A" + (i + 1), "info");
                return currentTrack;
            } else {
                logToDowP("findAvailableAudioTrack: Pista A" + (i + 1) + " ocupada por colisión.", "info");
            }
        }

        var qeSequence = qe.project.getActiveSequence();
        if (qeSequence) {
            var firstTrack = sequence.audioTracks[0];
            var baseType = firstTrack.audioTrackType;

            var audioTypeMap = {
                "Mono": 0,
                "Stereo": 1,
                "5.1": 2,
                "Adaptive": 3
            };

            var audioType = audioTypeMap[baseType] !== undefined ? audioTypeMap[baseType] : 1;

            var vCount = sequence.videoTracks.numTracks;
            var aCount = sequence.audioTracks.numTracks;

            qeSequence.addTracks(0, vCount, 1, audioType, aCount);

            return sequence.audioTracks[sequence.audioTracks.numTracks - 1];
        }
    } catch (e) {
        return null;
    }

    return null;
}

function importForAfterEffects(filePaths, addToTimeline, playheadTime, importImagesToTimeline, targetBinName) {
    try {
        if (!app.project) return "Error: No hay un proyecto abierto en After Effects.";

        app.beginUndoGroup("Importar desde DowP");
        var project = app.project;
        var mainBinName = "DowP Imports";
        var mainBin = null;

        for (var i = 1; i <= project.numItems; i++) {
            var item = project.item(i);
            if (item.name === mainBinName && item instanceof FolderItem) {
                mainBin = item;
                break;
            }
        }
        if (mainBin === null) {
            mainBin = project.items.addFolder(mainBinName);
        }

        var targetBin = mainBin;

        // Ignoramos targetBinName para evitar carpetas redundantes

        var mediaItems = [];
        var successfullyImportedCount = 0;

        for (var j = 0; j < filePaths.length; j++) {
            var currentPath = filePaths[j];
            var lowerPath = currentPath.toLowerCase();

            if (/\.(srt|vtt|ass|ssa|sub)$/i.test(lowerPath)) continue;

            // --- INICIO DE LA MODIFICACIÓN ---

            var importedItem = null;
            var maxRetries = 3;
            var retryDelay = 500; // Empezar con 500ms (0.5s) de retraso

            for (var attempt = 1; attempt <= maxRetries; attempt++) {
                try {
                    // Limpiar caché en CADA intento
                    clearCacheForExistingItems(currentPath, targetBin);

                    // Pausa preventiva. Aumenta en cada intento.
                    // Intento 1: 250ms
                    // Intento 2: 500ms
                    // Intento 3: 1000ms
                    $.sleep((attempt === 1) ? 250 : (retryDelay * (attempt - 1)));

                    var importOptions = new ImportOptions(new File(currentPath));

                    if (importOptions.canImportAs && importOptions.canImportAs(ImportAsType.FOOTAGE)) {
                        importOptions.importAs = ImportAsType.FOOTAGE;
                    }

                    importOptions.sequence = false;

                    importedItem = project.importFile(importOptions); // <--- Intento de importación

                    if (importedItem) {
                        // Determinar carpeta de destino inteligente directamente en mainBin
                        var folderName = "Video";
                        var isImageExt = /\.(jpg|jpeg|png|gif|bmp|tiff|tif|svg|webp)$/i.test(lowerPath);
                        var isAudioExt = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath);

                        if (isImageExt) {
                            folderName = "Imágenes";
                        } else if (isAudioExt || (importedItem.hasAudio && !importedItem.hasVideo)) {
                            folderName = "Audio";
                        }

                        // Usar siempre mainBin para evitar anidamiento excesivo
                        var subFolder = getOrCreateSubFolder(mainBin, folderName);
                        importedItem.parentFolder = subFolder;

                        // (Lógica de refresco de caché que ya tenías)
                        if (importedItem.file && importedItem.file.exists) {
                            try { importedItem.replace(importedItem.file); } catch (e_rep) { }
                        }

                        $.writeln("Importación exitosa en intento " + attempt + " para: " + currentPath);
                        break; // Salir del bucle de reintento
                    }

                } catch (e) {
                    // Imprime el error real en la consola de ExtendScript
                    $.writeln("[ERROR] Intento " + attempt + " falló para " + currentPath + ": " + e.toString());

                    if (attempt === maxRetries) {
                        // Si fallan todos los reintentos, registrar el error
                        $.writeln("ERROR: Fallaron todos los reintentos de importación para " + currentPath);
                        // 'importedItem' seguirá siendo null
                    }
                }
            } // Fin del bucle for (reintentos)


            // (Esta lógica ahora está FUERA del bloque try/catch de importación)
            if (importedItem) {

                var isImage = /\.(jpg|jpeg|png|gif|bmp|tiff|tif)$/i.test(lowerPath);
                var isAudio = /\.(mp3|m4a|wav|flac|aac|ogg|opus|weba)$/i.test(lowerPath);
                var isVideo = /\.(mp4|mkv|webm|mov|avi|flv|wmv|m4v)$/i.test(lowerPath);

                $.writeln("DEBUG: Importado - " + currentPath);
                $.writeln("  - hasVideo: " + importedItem.hasVideo);
                $.writeln("  - hasAudio: " + importedItem.hasAudio);
                $.writeln("  - isImage: " + isImage);
                $.writeln("  - isAudio: " + isAudio);
                $.writeln("  - isVideo: " + isVideo);

                var isImportable = importedItem.hasVideo || importedItem.hasAudio || isAudio || isVideo || isImage;

                if (importedItem && isImportable) {
                    successfullyImportedCount++; // Aumentamos el contador de archivos importados con éxito

                    if (isImage && !importImagesToTimeline) {
                        $.writeln("  - SALTADO (Timeline): Imagen y 'importImagesToTimeline' está desactivado.");
                        continue;
                    }

                    $.writeln("  - AÑADIDO a mediaItems (para timeline)");
                    mediaItems.push(importedItem);

                } else {
                    $.writeln("  - RECHAZADO: No tiene audio/video y no es extensión reconocida");
                }

            }

        }

        if (addToTimeline && mediaItems.length > 0) {
            var comp = app.project.activeItem;
            if (comp && comp instanceof CompItem) {
                for (var m = 0; m < mediaItems.length; m++) {
                    try {
                        var newLayer = comp.layers.add(mediaItems[m]);
                        newLayer.startTime = playheadTime || 0;
                        newLayer.moveToBeginning();

                        comp.displayStartTime = comp.displayStartTime;
                    } catch (e) {
                        continue;
                    }
                }

                try {
                    comp.openInViewer();
                } catch (e) {
                }
            }
        }

        app.endUndoGroup();

        if (successfullyImportedCount === 0) {
            return "Error: No se pudieron importar archivos. Verifica que los archivos sean válidos.";
        }

        return "success";
    } catch (error) {
        app.endUndoGroup();
        return "Error en importForAfterEffects: " + error.toString();
    }
}

function getClipDuration(mediaItem) {
    try {
        if (mediaItem.getOutPoint && mediaItem.getInPoint) {
            return mediaItem.getOutPoint().seconds - mediaItem.getInPoint().seconds;
        }
        if (mediaItem.duration) {
            return mediaItem.duration.seconds;
        }
        return 10.0;
    } catch (e) {
        return 10.0;
    }
}

function getItemUIDs(bin) {
    var uids = {};
    try {
        for (var i = 0; i < bin.children.numItems; i++) {
            uids[bin.children[i].nodeId] = true;
        }
    } catch (e) {
    }
    return uids;
}

function detectAVviaXMP(projectItem) {
    var hasVideo = false;
    var hasAudio = false;

    try {
        var xmp = projectItem.getProjectMetadata();

        if (xmp) {
            if (xmp.indexOf("VideoInfo") !== -1 ||
                xmp.indexOf("vcodec") !== -1 ||
                xmp.indexOf("width") !== -1 ||
                xmp.indexOf("height") !== -1) {
                hasVideo = true;
            }

            if (xmp.indexOf("AudioInfo") !== -1 ||
                xmp.indexOf("acodec") !== -1 ||
                xmp.indexOf("channels") !== -1 ||
                xmp.indexOf("audio") !== -1) {
                hasAudio = true;
            }

            $.writeln("DEBUG detectAVviaXMP:");
            $.writeln("  - hasVideo: " + hasVideo);
            $.writeln("  - hasAudio: " + hasAudio);
            $.writeln("  - XMP length: " + xmp.length);
            if (xmp.length > 0 && xmp.length < 500) {
                $.writeln("  - XMP content: " + xmp);
            }
        } else {
            $.writeln("DEBUG: No XMP metadata found for " + projectItem.name);
        }
    } catch (e) {
        $.writeln("ERROR in detectAVviaXMP: " + e.toString());
    }

    return { video: hasVideo, audio: hasAudio };
}

function getConfigFilePath() {
    try {
        var userFolder = Folder.userData;
        var configFolder = new Folder(userFolder.fsName + "/DowP_Importer");

        if (!configFolder.exists) {
            configFolder.create();
        }

        return configFolder.fsName + "/config.json";
    } catch (e) {
        return null;
    }
}

function saveConfig(key, value) {
    try {
        var configPath = getConfigFilePath();
        if (!configPath) return "error";

        var configFile = new File(configPath);
        var config = {};

        if (configFile.exists) {
            configFile.open("r");
            var content = configFile.read();
            configFile.close();

            if (content && content !== "") {
                try {
                    config = JSON.parse(content);
                } catch (e) {
                    config = {};
                }
            }
        }

        config[key] = value;

        configFile.open("w");
        configFile.encoding = "UTF-8";
        configFile.write(JSON.stringify(config, null, 2));
        configFile.close();

        return "success";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function loadConfig(key) {
    try {
        var configPath = getConfigFilePath();
        if (!configPath) return null;

        var configFile = new File(configPath);

        if (!configFile.exists) {
            return null;
        }

        configFile.open("r");
        var content = configFile.read();
        configFile.close();

        if (!content || content === "") {
            return null;
        }

        var config = JSON.parse(content);
        return config[key] || null;
    } catch (e) {
        return null;
    }
}

function findDowPExecutable() {
    try {
        if (isMacOS()) {
            // Folder.userData en macOS = ~/Library/Application Support
            var appSupport = Folder.userData;
            var homeMac = appSupport.parent.parent;  // ~/Library -> ~

            var macCandidates = [
                "/Applications/DowP.app",
                homeMac.fsName + "/Applications/DowP.app",
                appSupport.fsName + "/DowP/DowP.app"
            ];

            for (var i = 0; i < macCandidates.length; i++) {
                // Un .app es un directorio: hay que comprobarlo como Folder,
                // File.exists devolveria false siempre.
                var bundle = new Folder(macCandidates[i]);
                if (bundle.exists) {
                    return bundle.fsName;
                }
            }

            return "not_found";
        }

        // ── Windows ──
        var userFolder = Folder.userData;            // %APPDATA% (Roaming)
        var localAppData = userFolder.parent.fsName + "\\Local";

        var winCandidates = [
            localAppData + "\\DowP\\DowP.exe",
            localAppData + "\\Programs\\DowP\\DowP.exe",
            "C:\\Program Files\\DowP\\DowP.exe"
        ];

        for (var j = 0; j < winCandidates.length; j++) {
            var exe = new File(winCandidates[j]);
            if (exe.exists) {
                return exe.fsName;
            }
        }

        return "not_found";
    } catch (e) {
        return "error: " + e.toString();
    }
}

function getSelectedFilePathsFromAdobe() {
    var filePaths = [];
    var foundPathsObj = {};
    var debugMessages = [];

    // ✅ NUEVO: Crear archivo de log
    var logFile = new File(Folder.temp.fsName + "/dowp_debug.txt");

    function logDebug(msg) {
        debugMessages.push(msg);
        $.writeln(msg);
        // Escribir también a archivo
        try {
            logFile.open("a");
            logFile.writeln(msg);
            logFile.close();
        } catch (e) { }
    }

    // Limpiar log anterior
    try {
        logFile.open("w");
        logFile.writeln("=== NUEVO DEBUG SESSION ===");
        logFile.writeln("Timestamp: " + new Date().toString());
        logFile.close();
    } catch (e) { }

    function addPath(path) {
        if (path && path.length > 0) {
            var f = new File(path);
            if (f.exists) {
                if (!foundPathsObj[f.fsName]) {
                    filePaths.push(f.fsName);
                    foundPathsObj[f.fsName] = true;
                    logDebug("✓ Agregado: " + f.fsName);
                }
            } else {
                logDebug("✗ No existe: " + path);
            }
        }
    }

    try {
        var host = getHostAppName();
        logDebug("Host detectado: " + host);

        if (host === "Adobe Premiere Pro") {
            logDebug("=== PREMIERE PRO ===");

            // 1. Buscar en la Línea de Tiempo Activa
            if (app.project && app.project.activeSequence) {
                try {
                    var trackItems = app.project.activeSequence.getSelection();
                    logDebug("Clips en timeline: " + trackItems.length);

                    for (var k = 0; k < trackItems.length; k++) {
                        try {
                            var clip = trackItems[k];
                            if (clip.projectItem && clip.projectItem.getMediaPath) {
                                var path = clip.projectItem.getMediaPath();
                                logDebug("Timeline clip path: " + path);
                                addPath(path);
                            }
                        } catch (clipError) {
                            logDebug("Error en clip " + k + ": " + clipError.toString());
                        }
                    }
                } catch (timelineError) {
                    logDebug("Error timeline: " + timelineError.toString());
                }
            } else {
                logDebug("No hay secuencia activa");
            }

            // 2. Buscar en el Panel de Proyecto (Bin)
            logDebug("--- Buscando en Panel de Proyecto ---");
            if (app.project) {
                try {
                    var selection = app.project.getSelection();
                    logDebug("Items en proyecto: " + selection.length);

                    if (selection.length === 0) {
                        logDebug("⚠️ La selección está vacía - asegúrate de seleccionar clips en el proyecto");
                    }

                    for (var i = 0; i < selection.length; i++) {
                        try {
                            var item = selection[i];
                            if (!item) {
                                logDebug("  Item " + i + " es null/undefined");
                                continue;
                            }

                            // Debug: nombre del item
                            logDebug("  Item " + i + ": " + (item.name || "sin nombre"));

                            // Debug: tipo de item
                            var itemType = "unknown";
                            try {
                                if (item.type === ProjectItemType.BIN) {
                                    itemType = "BIN";
                                    logDebug("    Tipo: BIN (carpeta) - SALTADO");
                                    continue;
                                } else if (item.type === ProjectItemType.CLIP) {
                                    itemType = "CLIP";
                                } else if (item.type === ProjectItemType.FILE) {
                                    itemType = "FILE";
                                } else {
                                    itemType = "type=" + item.type;
                                }
                                logDebug("    Tipo: " + itemType);
                            } catch (e) {
                                logDebug("    Tipo: ERROR - " + e.toString());
                            }

                            // Intentar obtener la ruta
                            var path = "";

                            // Método 1: getMediaPath()
                            try {
                                if (typeof item.getMediaPath === "function") {
                                    path = item.getMediaPath();
                                    logDebug("    getMediaPath() = '" + path + "'");
                                } else {
                                    logDebug("    getMediaPath NO es función");
                                }
                            } catch (e) {
                                logDebug("    getMediaPath() ERROR: " + e.toString());
                            }

                            // Método 2: mediaPath propiedad
                            if (!path || path === "") {
                                try {
                                    if (item.mediaPath) {
                                        path = item.mediaPath;
                                        logDebug("    mediaPath = '" + path + "'");
                                    } else {
                                        logDebug("    mediaPath está vacío o undefined");
                                    }
                                } catch (e) {
                                    logDebug("    mediaPath ERROR: " + e.toString());
                                }
                            }

                            // Método 3: filePath
                            if (!path || path === "") {
                                try {
                                    if (item.filePath) {
                                        path = item.filePath;
                                        logDebug("    filePath = '" + path + "'");
                                    } else {
                                        logDebug("    filePath está vacío o undefined");
                                    }
                                } catch (e) {
                                    logDebug("    filePath ERROR: " + e.toString());
                                }
                            }

                            // Intentar agregar
                            if (path && path !== "" && path !== "undefined") {
                                logDebug("    ➜ Intentando agregar: " + path);
                                addPath(path);
                            } else {
                                logDebug("    ✗ No se pudo obtener ruta válida");
                            }

                        } catch (itemError) {
                            logDebug("  ERROR procesando item " + i + ": " + itemError.toString());
                        }
                    }
                } catch (projectError) {
                    logDebug("ERROR obteniendo selección: " + projectError.toString());
                }
            } else {
                logDebug("✗ app.project no existe");
            }

        } else if (host === "Adobe After Effects") {
            debugMessages.push("=== AFTER EFFECTS ===");

            // 1. Buscar en la Composición Activa (Capas seleccionadas)
            if (app.project && app.project.activeItem && app.project.activeItem instanceof CompItem) {
                try {
                    var selectedLayers = app.project.activeItem.selectedLayers;
                    debugMessages.push("Capas seleccionadas: " + selectedLayers.length);

                    for (var m = 0; m < selectedLayers.length; m++) {
                        try {
                            var layer = selectedLayers[m];
                            if (layer.source && layer.source.file) {
                                debugMessages.push("Layer path: " + layer.source.file.fsName);
                                addPath(layer.source.file.fsName);
                            }
                        } catch (layerError) {
                            debugMessages.push("Error en layer " + m + ": " + layerError.toString());
                        }
                    }
                } catch (compError) {
                    debugMessages.push("Error comp: " + compError.toString());
                }
            } else {
                debugMessages.push("No hay comp activa");
            }

            // 2. Buscar en el Panel de Proyecto
            if (app.project && app.project.selection) {
                try {
                    var selection = app.project.selection;
                    debugMessages.push("Items seleccionados en proyecto: " + selection.length);

                    for (var i = 0; i < selection.length; i++) {
                        try {
                            var item = selection[i];
                            if (item instanceof FootageItem && item.file) {
                                debugMessages.push("Proyecto item path: " + item.file.fsName);
                                addPath(item.file.fsName);
                            } else if (item instanceof FolderItem) {
                                debugMessages.push("  (saltado: es un folder)");
                            }
                        } catch (itemError) {
                            debugMessages.push("Error en item " + i + ": " + itemError.toString());
                        }
                    }
                } catch (projectError) {
                    debugMessages.push("Error proyecto: " + projectError.toString());
                }
            }
        }

        logDebug("=== RESULTADO FINAL ===");
        logDebug("Total archivos encontrados: " + filePaths.length);

        // Escribir resumen final
        try {
            logFile.open("a");
            logFile.writeln("\n=== ARCHIVOS FINALES ===");
            for (var f = 0; f < filePaths.length; f++) {
                logFile.writeln(filePaths[f]);
            }
            logFile.writeln("Total: " + filePaths.length);
            logFile.writeln("=== FIN ===\n");
            logFile.close();
        } catch (e) { }

        return JSON.stringify(filePaths);

    } catch (e) {
        logDebug("ERROR CRÍTICO: " + e.toString());
        return JSON.stringify([]);
    }
}

// FUNCIÓN DE DIAGNÓSTICO - Eliminar después de resolver el problema
function debugProjectSelection() {
    var report = [];

    try {
        if (!app.project) {
            return "ERROR: No hay proyecto abierto";
        }

        var selection = app.project.getSelection();
        report.push("=== DIAGNÓSTICO DE SELECCIÓN ===");
        report.push("Total items seleccionados: " + selection.length);
        report.push("");

        for (var i = 0; i < selection.length; i++) {
            var item = selection[i];
            report.push("--- Item " + i + " ---");
            report.push("name: " + (item.name || "undefined"));
            report.push("nodeId: " + (item.nodeId || "undefined"));

            // Tipo
            try {
                report.push("type: " + item.type);
            } catch (e) {
                report.push("type: ERROR - " + e.toString());
            }

            // Listar todas las propiedades disponibles
            report.push("Propiedades disponibles:");
            for (var prop in item) {
                try {
                    var value = item[prop];
                    var valueType = typeof value;
                    if (valueType === "function") {
                        report.push("  - " + prop + "() [función]");
                    } else {
                        report.push("  - " + prop + " = " + value + " [" + valueType + "]");
                    }
                } catch (e) {
                    report.push("  - " + prop + " [error al leer]");
                }
            }

            // Intentar todos los métodos conocidos para obtener ruta
            report.push("Intentos de obtener ruta:");

            try {
                if (item.getMediaPath) {
                    report.push("  getMediaPath(): " + item.getMediaPath());
                }
            } catch (e) {
                report.push("  getMediaPath(): ERROR - " + e.toString());
            }

            try {
                if (item.mediaPath) {
                    report.push("  mediaPath: " + item.mediaPath);
                }
            } catch (e) {
                report.push("  mediaPath: ERROR");
            }

            try {
                if (item.filePath) {
                    report.push("  filePath: " + item.filePath);
                }
            } catch (e) {
                report.push("  filePath: ERROR");
            }

            report.push("");
        }

        return report.join("\n");

    } catch (e) {
        return "ERROR CRÍTICO: " + e.toString();
    }
}

function getOrCreateSubBin(parentBin, binName) {
    try {
        if (!parentBin || !parentBin.children) return null;
        for (var i = 0; i < parentBin.children.numItems; i++) {
            var item = parentBin.children[i];
            if (item.name === binName && item.type === ProjectItemType.BIN) {
                return item;
            }
        }
        return parentBin.createBin(binName);
    } catch (e) {
        return parentBin;
    }
}

function getOrCreateSubFolder(parentFolder, folderName) {
    try {
        if (!parentFolder || !app.project) return null;
        for (var i = 1; i <= app.project.numItems; i++) {
            var item = app.project.item(i);
            if (item.name === folderName && item instanceof FolderItem && item.parentFolder === parentFolder) {
                return item;
            }
        }
        var newFolder = app.project.items.addFolder(folderName);
        newFolder.parentFolder = parentFolder;
        return newFolder;
    } catch (e) {
        return parentFolder;
    }
}