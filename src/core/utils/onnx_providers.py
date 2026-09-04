# src/core/utils/onnx_providers.py
"""Selección de execution providers de ONNX Runtime por SO, para Eliminar Fondo IA
(ver core/tabs/image_tools/rembg_engine.py) y cualquier otro motor ONNX futuro.

Windows -> onnxruntime-directml (DmlExecutionProvider): NVIDIA/AMD/Intel sin
depender de un toolkit CUDA instalado aparte (DirectX 12 ya viene con el SO).
macOS -> onnxruntime estándar, que ya trae compilado CoreMLExecutionProvider en
el wheel oficial (usa GPU/Neural Engine solo cuando conviene, sin config extra).
Linux -> CPUExecutionProvider nada más por ahora (sin toolkit CUDA/ROCm que
pedirle al usuario -- decisión de portabilidad, ver memoria de proyecto
"DowP ONNX Runtime GPU strategy"). requirements.txt ya instala el paquete
correcto por SO vía marcadores PEP 508 -- este módulo solo elige qué provider
pedirle a la sesión, nunca instala nada.
"""
import platform

from core.logger.logger_manager import logger

# DirectML: firmas de error conocidas de cuelgue/timeout del driver de GPU --
# 887A0007 es el HRESULT de DXGI_ERROR_DEVICE_HUNG. Confirmadas en producción
# por DowP1 (image_converter.pyc decompilado), que reintentaba por CPU al
# toparse con cualquiera de estas. Vive aquí (no en rembg_engine.py) porque es
# una propiedad del provider DirectML, no del motor de Eliminar Fondo en sí --
# cualquier motor ONNX futuro que use DML puede reusar esta misma lista.
DML_FAILURE_HINTS = ("DmlFusedNode", "887A0007", "Non-zero status")


def get_execution_providers(use_gpu: bool) -> list[str]:
    """Lista de providers a pedirle a onnxruntime.InferenceSession, con
    CPUExecutionProvider siempre al final como fallback nativo de ONNX Runtime
    (si el primero no puede correr un nodo, cae solo al siguiente de la lista)."""
    if not use_gpu:
        return ["CPUExecutionProvider"]

    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except Exception as e:
        logger.warning(f"onnx_providers: no se pudo consultar onnxruntime, usando CPU: {e}")
        return ["CPUExecutionProvider"]

    system = platform.system()
    if system == "Windows" and "DmlExecutionProvider" in available:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    if system == "Darwin" and "CoreMLExecutionProvider" in available:
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


# Nombre corto de cada provider de GPU, para poder decirle al usuario QUÉ
# aceleración se detectó en vez de un "sí/no" a secas.
_GPU_PROVIDER_LABELS = {
    "DmlExecutionProvider": "DirectML",
    "CoreMLExecutionProvider": "CoreML",
}


def get_gpu_provider() -> str | None:
    """El provider de GPU realmente utilizable en este equipo, o None si solo
    hay CPU. No es una detección de hardware aparte: se le pregunta a
    get_execution_providers() (la misma función que arma la sesión de verdad), así
    que la UI no puede afirmar algo distinto de lo que va a pasar al procesar.

    En la práctica: Windows con un equipo DirectX 12 -> DirectML; macOS -> CoreML;
    Linux -> None siempre, porque ahí no instalamos onnxruntime-gpu a propósito
    (ver la nota de arriba). Un Windows sin GPU compatible tampoco expone
    DmlExecutionProvider, así que también cae en None."""
    providers = get_execution_providers(use_gpu=True)
    primary = providers[0] if providers else None
    return primary if primary and primary != "CPUExecutionProvider" else None


def get_gpu_provider_label() -> str | None:
    """Nombre presentable del provider de GPU detectado ("DirectML", "CoreML"),
    o None si no hay."""
    provider = get_gpu_provider()
    if provider is None:
        return None
    return _GPU_PROVIDER_LABELS.get(provider, provider)


def has_gpu_acceleration() -> bool:
    return get_gpu_provider() is not None


def build_session_options(providers: list[str]):
    """SessionOptions afinado según el provider principal -- portado de DowP1
    (image_converter.pyc), que llegó a esta configuración específica para evitar
    cuelgues reales de driver con DirectML en producción:
      - DirectML: enable_mem_pattern=False (workaround conocido de DML) +
        ejecución secuencial de un solo hilo -- corre menos rápido en el papel,
        pero es lo que dejó de colgar el driver de GPU en los equipos de los
        usuarios de DowP1.
      - CPU: al revés, ejecución paralela + todas las optimizaciones de grafo,
        no hay ningún driver de por medio que se pueda colgar.
      - CoreML (macOS): sin tuning propio todavía -- no hay evidencia de que
        necesite el mismo workaround que DirectML (nunca corrió en producción
        ahí), se deja el SessionOptions por defecto."""
    import onnxruntime as ort
    opts = ort.SessionOptions()
    primary = providers[0] if providers else None

    if primary == "DmlExecutionProvider":
        opts.enable_mem_pattern = False
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
    elif primary == "CPUExecutionProvider":
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL

    return opts
