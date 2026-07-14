# src/core/setup/ffmpeg_setup.py
import os
import requests
import zipfile
import tarfile
import shutil
import platform
import stat
from core.logger.logger_manager import logger

# Versión fija de FFmpeg (8.0.1) para Windows
FFMPEG_VERSION = "8.0.1"

def get_platform_info(version=None):
    """Determines the correct FFmpeg download strategy based on the OS."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "windows":
        if version == "latest":
            api_url = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
        else:
            v = version if version else FFMPEG_VERSION
            api_url = f"https://api.github.com/repos/GyanD/codexffmpeg/releases/tags/{v}"
            
        return {
            "os": "windows",
            "api_url": api_url,
            "binary_name": "ffmpeg.exe",
            "extract_method": "zip_gyand"
        }
    elif system == "darwin":
        # Mac uses Evermeet JSON API to get the correct zip URL
        return {
            "os": "mac",
            "api_url": "https://evermeet.cx/ffmpeg/info/ffmpeg/release",
            "binary_name": "ffmpeg",
            "extract_method": "zip_direct"
        }
    elif system == "linux":
        # Linux uses BtbN latest master builds
        arch = "linuxarm64" if machine in ["arm64", "aarch64"] else "linux64"
        return {
            "os": "linux",
            "download_url": f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-{arch}-gpl.tar.xz",
            "binary_name": "ffmpeg",
            "extract_method": "tarxz_btbn"
        }
    else:
        # Fallback to Linux x86_64
        return {
            "os": "linux",
            "download_url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
            "binary_name": "ffmpeg",
            "extract_method": "tarxz_btbn"
        }

def get_ffmpeg_dir():
    """Returns the directory path for ffmpeg."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    ffmpeg_dir = os.path.join(base_dir, "bin", "dependences", "ffmpeg")
    if not os.path.exists(ffmpeg_dir):
        logger.info(f"Creating directory: {ffmpeg_dir}")
        os.makedirs(ffmpeg_dir)
    return ffmpeg_dir

_ffmpeg_checked = False

def check_ffmpeg():
    """Verifies if the ffmpeg binary exists in the ffmpeg folder."""
    global _ffmpeg_checked
    info = get_platform_info()
    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
    exists = os.path.exists(ffmpeg_exe)
    if not _ffmpeg_checked:
        logger.debug(f"Checking {info['binary_name']} existence: {exists}")
        _ffmpeg_checked = True
    return exists

def download_ffmpeg(version=None, progress_callback=None):
    """Downloads, extracts, and cleans up ffmpeg."""
    try:
        info = get_platform_info(version=version)
        download_url = info.get("download_url")

        # Resolve download URL if using API (Windows or Mac)
        if not download_url and info.get("api_url"):
            logger.info(f"Fetching latest ffmpeg release info from {info['api_url']}")
            response = requests.get(info["api_url"])
            response.raise_for_status()
            data = response.json()
            
            if info["os"] == "windows":
                for asset in data.get("assets", []):
                    if "essentials_build.zip" in asset["name"]:
                        download_url = asset["browser_download_url"]
                        break
            elif info["os"] == "mac":
                download_url = data.get("download", {}).get("zip", {}).get("url")
            
            if not download_url:
                logger.error("FFmpeg package URL not found in API response")
                return False, "FFmpeg package URL not found."

        ffmpeg_dir = get_ffmpeg_dir()
        is_tar = download_url.endswith(".tar.xz")
        temp_file = os.path.join(ffmpeg_dir, "ffmpeg_temp.tar.xz" if is_tar else "ffmpeg_temp.zip")
        extract_path = os.path.join(ffmpeg_dir, "temp_extract")
        
        # 1. Download
        logger.info(f"Downloading FFmpeg from {download_url}")
        r = requests.get(download_url, stream=True)
        r.raise_for_status()
        
        total_size = int(r.headers.get('content-length', 0))
        downloaded = 0
        
        with open(temp_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        progress_callback(percent)
        
        # 2. Temporary extraction
        logger.info("Extracting FFmpeg package...")
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)
        os.makedirs(extract_path)
        
        if is_tar:
            with tarfile.open(temp_file, 'r:xz') as tar_ref:
                tar_ref.extractall(extract_path)
        else:
            with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
        
        # 3. Find executable and move to ffmpeg folder
        logger.info("Locating executable file...")
        exe_found = False
        target_bin = info["binary_name"]
        
        for root, dirs, files in os.walk(extract_path):
            for file in files:
                # In macOS direct zip, file is 'ffmpeg'. In GyanD, it's 'ffmpeg.exe'. In BtbN, it's 'ffmpeg'
                if file == target_bin or (info["os"] == "windows" and file.endswith(".exe") and "ffmpeg" in file.lower()):
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(ffmpeg_dir, target_bin)
                    if os.path.exists(dst_file):
                        os.remove(dst_file)
                    logger.debug(f"Moving {file} to {ffmpeg_dir}")
                    shutil.move(src_file, dst_file)
                    exe_found = True
                    break
            if exe_found:
                break
        
        # 4. Unix Permissions
        final_exe = os.path.join(ffmpeg_dir, target_bin)
        if exe_found and info["os"] != "windows":
            logger.info("Setting executable permissions for FFmpeg binary...")
            st = os.stat(final_exe)
            os.chmod(final_exe, st.st_mode | stat.S_IEXEC)

        # 5. Cleanup
        logger.info("Cleaning up temporary files...")
        os.remove(temp_file)
        shutil.rmtree(extract_path)
        
        if not exe_found:
            logger.error(f"Executable '{target_bin}' not found in the FFmpeg package")
            return False, f"Executable '{target_bin}' not found in FFmpeg package."

        logger.info("FFmpeg setup completed successfully.")
        return True, "FFmpeg downloaded and configured."
    except Exception as e:
        logger.error(f"Error setting up FFmpeg: {e}")
        return False, str(e)

import subprocess
import re
from core.utils.config_manager import get_config, save_config

def get_local_version(force_check=False):
    """Runs the local ffmpeg to get its version, caching it in config.json to avoid lag."""
    if not check_ffmpeg():
        return None
        
    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "ffmpeg" in versions:
        return versions["ffmpeg"]
        
    try:
        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [ffmpeg_exe, "-version"], 
            capture_output=True, text=True, check=True, creationflags=flags
        )
        # Expected output format: 'ffmpeg version 8.0.1-essentials_build...'
        first_line = result.stdout.strip().split('\n')[0]
        # Regex to extract something that looks like a version (e.g., 7.0.1, or N-113007-g...)
        match = re.search(r'version\s+([^\s]+)', first_line)
        if match:
            version = match.group(1)
        else:
            version = first_line.split()[2]
            
        # Save to config
        versions["ffmpeg"] = version
        config["dependency_versions"] = versions
        save_config(config)
        
        return version
    except Exception as e:
        logger.error(f"Error getting local FFmpeg version: {e}")
        return None

def get_latest_remote_version():
    """Fetches the latest version string from the respective source."""
    info = get_platform_info()
    try:
        if info["os"] == "windows":
            # Check GyanD latest
            url = "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("tag_name", "").lstrip("v")
        elif info["os"] == "mac":
            url = "https://evermeet.cx/ffmpeg/info/ffmpeg/release"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("version", "")
        else:
            # Linux BtbN
            url = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            # BtbN uses "latest" as tag, we can look at the release name which usually contains the date or version
            return data.get("name", "latest")
    except Exception as e:
        logger.error(f"Error getting remote FFmpeg version: {e}")
        return None

if __name__ == "__main__":
    if not check_ffmpeg():
        success, msg = download_ffmpeg()
        logger.info(msg)
    else:
        logger.info("FFmpeg is already configured.")

