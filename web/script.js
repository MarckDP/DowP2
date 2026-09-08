document.addEventListener('DOMContentLoaded', () => {
    const btnText = document.getElementById('btn-text');
    const mainBtn = document.getElementById('main-download-btn');
    const altLinks = document.querySelectorAll('.alt-links a');

    // Detección simple del sistema operativo
    let osName = "Unknown";
    const userAgent = window.navigator.userAgent;
    const platform = window.navigator.platform;
    const macosPlatforms = ['Macintosh', 'MacIntel', 'MacPPC', 'Mac68K'];
    const windowsPlatforms = ['Win32', 'Win64', 'Windows', 'WinCE'];

    if (macosPlatforms.indexOf(platform) !== -1 || userAgent.includes("Mac")) {
        osName = 'Mac';
    } else if (windowsPlatforms.indexOf(platform) !== -1 || userAgent.includes("Win")) {
        osName = 'Windows';
    } else if (/Linux/.test(platform) || userAgent.includes("Linux")) {
        osName = 'Linux';
    }

    // Configurar el botón principal de acuerdo al sistema operativo detectado
    if (osName === 'Windows') {
        btnText.textContent = 'Descargar para Windows';
        mainBtn.href = '#download-windows'; // TODO: Reemplazar con URL de GitHub Releases
    } else if (osName === 'Mac') {
        btnText.textContent = 'Descargar para macOS';
        mainBtn.href = '#download-mac'; // TODO: Reemplazar con URL de GitHub Releases
    } else if (osName === 'Linux') {
        btnText.textContent = 'Descargar para Linux';
        mainBtn.href = '#download-linux'; // TODO: Reemplazar con URL de GitHub Releases
    } else {
        btnText.textContent = 'Descargar DowP';
        mainBtn.href = '#download-all';
    }

    // Atenuar el enlace de la plataforma actual en la sección "Otras plataformas"
    altLinks.forEach(link => {
        if (link.dataset.os === osName) {
            link.style.opacity = '0.3';
            link.style.pointerEvents = 'none'; // Desactiva el click
            link.title = 'Este es tu sistema actual';
        }
    });
});
