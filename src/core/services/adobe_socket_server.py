import socketio
import asyncio
from aiohttp import web
from PySide6.QtCore import QThread, Signal
from core.logger.logger_manager import logger

class AdobeSocketServer(QThread):
    # Signals to communicate with the PySide6 UI if needed
    client_connected = Signal(str)
    client_disconnected = Signal(str)
    active_target_changed = Signal(object)

    _instance = None

    def __init__(self, host='127.0.0.1', port=7788):
        super().__init__()
        self.host = host
        self.port = port
        self.loop = None
        self._runner = None
        
        # aiohttp async mode
        self.sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
        self.app = web.Application()
        self.sio.attach(self.app)
        
        self.active_target_sid = None
        self.clients = {}  # sid -> appIdentifier
        
        self._setup_handlers()
        
        # Singleton-like behavior for easy access from outside
        AdobeSocketServer._instance = self

    @classmethod
    def get_instance(cls):
        return cls._instance

    def _setup_handlers(self):
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"[Socket.IO] Client connected: {sid}")
            self.clients[sid] = "unknown"
            self.client_connected.emit(sid)

        @self.sio.event
        async def disconnect(sid):
            logger.info(f"[Socket.IO] Client disconnected: {sid}")
            if self.active_target_sid == sid:
                self.active_target_sid = None
                await self.sio.emit('active_target_update', {'activeTarget': None})
                self.active_target_changed.emit(None)
            
            if sid in self.clients:
                del self.clients[sid]
            self.client_disconnected.emit(sid)

        @self.sio.event
        async def register(sid, data):
            app_id = data.get('appIdentifier', 'unknown')
            logger.info(f"[Socket.IO] Client {sid} registered as {app_id}")
            self.clients[sid] = app_id
            
            # Respond with current active target
            active_app = self.clients.get(self.active_target_sid) if self.active_target_sid else None
            await self.sio.emit('active_target_update', {'activeTarget': active_app}, to=sid)

        @self.sio.event
        async def get_active_target(sid):
            active_app = self.clients.get(self.active_target_sid) if self.active_target_sid else None
            await self.sio.emit('active_target_update', {'activeTarget': active_app}, to=sid)

        @self.sio.event
        async def set_active_target(sid, data):
            self.active_target_sid = sid
            active_app = self.clients.get(sid)
            logger.info(f"[Socket.IO] Active target set to: {active_app} ({sid})")
            
            # Broadcast to everyone
            await self.sio.emit('active_target_update', {'activeTarget': active_app})
            self.active_target_changed.emit(active_app)

        @self.sio.event
        async def clear_active_target(sid):
            if self.active_target_sid == sid:
                self.active_target_sid = None
                logger.info(f"[Socket.IO] Active target cleared by {sid}")
                await self.sio.emit('active_target_update', {'activeTarget': None})
                self.active_target_changed.emit(None)

    def force_active_target(self, app_identifier):
        """Forces the active target to the given app_identifier if it is currently connected."""
        target_sid = None
        for sid, app_id in self.clients.items():
            if app_id == app_identifier:
                target_sid = sid
                break
                
        if target_sid:
            self.active_target_sid = target_sid
            logger.info(f"[Socket.IO] Active target forced to: {app_identifier} ({target_sid})")
            
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.sio.emit('active_target_update', {'activeTarget': app_identifier}),
                    self.loop
                )
            self.active_target_changed.emit(app_identifier)
            return True
        else:
            logger.warning(f"[Socket.IO] Cannot force target to {app_identifier}, not connected.")
            return False

    def send_file_to_adobe(self, file_package):
        """
        Sends a new file package to the active Adobe application.
        This method is called synchronously from the main thread.
        """
        if not self.active_target_sid:
            logger.warning("[Socket.IO] Attempted to send file, but no active target is linked.")
            return False
            
        if not self.loop or not self.loop.is_running():
            logger.error("[Socket.IO] Event loop is not running.")
            return False
            
        logger.info(f"[Socket.IO] Sending file to active target ({self.clients.get(self.active_target_sid)})")
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('new_file', {'filePackage': file_package}, to=self.active_target_sid),
            self.loop
        )
        return True
        
    def send_batch_to_adobe(self, files, target_bin=None):
        """
        Sends a batch of files to the active Adobe application.
        This method is called synchronously from the main thread.
        """
        if not self.active_target_sid:
            logger.warning("[Socket.IO] Attempted to send batch, but no active target is linked.")
            return False
            
        if not self.loop or not self.loop.is_running():
            logger.error("[Socket.IO] Event loop is not running.")
            return False
            
        logger.info(f"[Socket.IO] Sending batch to active target ({self.clients.get(self.active_target_sid)})")
        payload = {'files': files}
        if target_bin:
            payload['targetBin'] = target_bin
            
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('import_files', payload, to=self.active_target_sid),
            self.loop
        )
        return True

    def run(self):
        """
        Runs the aiohttp server in this QThread.
        """
        logger.info(f"[Socket.IO] Starting aiohttp server on {self.host}:{self.port}...")
        
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Setup runner (non-blocking setup for graceful shutdown)
        self._runner = web.AppRunner(self.app, access_log=None)
        self.loop.run_until_complete(self._runner.setup())
        
        site = web.TCPSite(self._runner, self.host, self.port)
        self.loop.run_until_complete(site.start())
        
        try:
            self.loop.run_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Socket.IO] Server error: {e}", exc_info=True)

    def stop(self):
        """
        Stops the QThread and the aiohttp server gracefully.
        """
        logger.info("[Socket.IO] Stopping server...")
        if self.loop and self.loop.is_running():
            # Schedule cleanup
            async def cleanup():
                if self._runner:
                    await self._runner.cleanup()
                self.loop.stop()
                
            asyncio.run_coroutine_threadsafe(cleanup(), self.loop)
        
        try:
            self.wait(2000) # Wait up to 2 seconds for thread to finish
        except BaseException:
            pass
            
        if self.isRunning():
            self.terminate()
            try:
                self.wait()
            except BaseException:
                pass
