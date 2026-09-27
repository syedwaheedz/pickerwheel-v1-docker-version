"""
PickerWheel Backend Application
Flask app factory with Socket.IO for real-time updates
"""

import os
import logging
from datetime import datetime, date
from flask import Flask, redirect, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from flask_socketio import SocketIO

# Initialize Socket.IO globally for access from other modules
socketio = SocketIO()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ISOJSONProvider(DefaultJSONProvider):
    """
    Flask's DefaultJSONProvider serializes datetime/date as an RFC 1123
    HTTP-date string ("Sat, 26 Sep 2026 10:37:21 GMT"), not ISO 8601.
    Every admin update route that added an updated_at field for
    optimistic-concurrency checking sends that value straight back to
    the client to echo on its next request - and every place in this
    codebase that parses a client-supplied datetime uses
    datetime.fromisoformat(), which can't read Flask's own default
    output. Without this, round-tripping updated_at would always 400.
    """
    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def create_app(config_name=None):
    """Create and configure the Flask application"""
    app = Flask(__name__,
                static_folder='../../frontend',
                static_url_path='')
    app.json = ISOJSONProvider(app)

    # Load configuration
    from .config import config, validate_production_config
    config_name = config_name or os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config[config_name])
    validate_production_config(app, config_name)

    allowed_origins = [o.strip() for o in app.config['ALLOWED_ORIGINS'].split(',') if o.strip()]

    # Enable CORS
    CORS(app, resources={
        r"/api/*": {"origins": allowed_origins},
        r"/socket.io/*": {"origins": allowed_origins}
    })

    # Initialize Socket.IO
    socketio.init_app(app,
                      cors_allowed_origins=allowed_origins,
                      async_mode='threading',
                      logger=True,
                      engineio_logger=True)
    
    # Initialize database
    from .database import init_db
    init_db(app)
    
    # Register blueprints
    from .routes.api import api_bp
    from .routes.admin import admin_bp
    
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    
    # Register WebSocket handlers
    from .routes import websocket
    websocket.register_handlers(socketio)
    
    # Register static file routes
    @app.route('/')
    def serve_index():
        # Requests that reach this app via Cloudflare (the public
        # pickerwheel.mytmobiles.com path, gated by Access) always carry
        # this header; direct LAN/localhost requests never do, since they
        # never touch Cloudflare's edge. The public domain's primary use
        # is admin access - the customer wheel is meant to be used from
        # the local network instead, where it isn't tunnel-latency-bound -
        # so bare '/' over the public domain goes to /admin, while local
        # access keeps serving the wheel here exactly as before.
        if request.headers.get('CF-Connecting-IP'):
            return redirect('/admin')
        return app.send_static_file('index.html')

    @app.route('/app')
    def serve_app():
        return app.send_static_file('index.html')

    @app.route('/admin')
    def serve_admin():
        return app.send_static_file('admin.html')
    
    @app.route('/<path:filename>')
    def serve_static(filename):
        return app.send_static_file(filename)
    
    logger.info(f"PickerWheel app created with config: {config_name}")
    
    return app
