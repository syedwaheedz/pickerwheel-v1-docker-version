"""
PickerWheel Configuration
Environment-based configuration management
"""

import os
from datetime import timedelta


class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'pickerwheel-secret-key-change-in-production')
    
    # PostgreSQL Database
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'pickerwheel')
    DB_USER = os.environ.get('DB_USER', 'pickerwheel')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'pickerwheel123')
    
    DATABASE_URL = os.environ.get(
        'DATABASE_URL',
        f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    )
    
    # Connection pool settings
    DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '10'))
    DB_MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW', '20'))
    DB_POOL_TIMEOUT = int(os.environ.get('DB_POOL_TIMEOUT', '30'))
    
    # Admin settings
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'myTAdmin2025')

    # Admin session cookie: SECURE is intentionally not forced on here, since
    # this stack is also accessed over plain HTTP on the LAN/localhost - a
    # Secure-only cookie would silently fail to be sent there. It still works
    # fine over the HTTPS Cloudflare Tunnel (Secure only restricts, never
    # requires, HTTP). Revisit alongside the rest of PRODUCTION_HARDENING.md.
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get('ADMIN_SESSION_HOURS', '12')))

    # CORS - comma-separated list of allowed origins. Defaults cover the app's
    # own same-origin dev serving (Flask serves admin.html/index.html itself,
    # so CORS barely matters for the primary UI - this only gates OTHER
    # origins calling the API/WebSocket directly).
    ALLOWED_ORIGINS = os.environ.get(
        'ALLOWED_ORIGINS', 'http://localhost:9080,http://127.0.0.1:9080'
    )

    # Event settings
    DEFAULT_EVENT_ID = 1

    # Socket.IO settings
    SOCKETIO_MESSAGE_QUEUE = os.environ.get('SOCKETIO_MESSAGE_QUEUE', None)

    # Feature flags
    REALTIME_WHEEL_UPDATES = os.environ.get('REALTIME_WHEEL_UPDATES', 'true').lower() == 'true'


# Known-insecure default literals that must never be used once FLASK_ENV=production -
# both are committed in docker-compose.yml/this file for local dev convenience, so
# they're effectively public and would otherwise be silently accepted in production.
_INSECURE_SECRET_KEY_DEFAULT = 'pickerwheel-secret-key-change-in-production'
_INSECURE_ADMIN_PASSWORD_DEFAULT = 'myTAdmin2025'


def validate_production_config(app, config_name):
    """
    Fail fast at startup if running with FLASK_ENV=production but still
    carrying a known-insecure default secret. Deliberately does nothing for
    development/testing - both configs are expected to use these exact
    bootstrap values (see TestingConfig / docker-compose.yml), so gating
    this to production only is what keeps local dev and the test suite
    working unchanged.
    """
    if config_name != 'production':
        return

    if app.config.get('SECRET_KEY') == _INSECURE_SECRET_KEY_DEFAULT:
        raise RuntimeError(
            'SECRET_KEY is unset or still the insecure default. '
            'Set a long random SECRET_KEY before running with FLASK_ENV=production.'
        )
    if app.config.get('ADMIN_PASSWORD') == _INSECURE_ADMIN_PASSWORD_DEFAULT:
        raise RuntimeError(
            'ADMIN_PASSWORD is unset or still the insecure default. '
            'Set a real ADMIN_PASSWORD before running with FLASK_ENV=production.'
        )


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    # Use stricter settings in production
    DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '20'))


class TestingConfig(Config):
    """
    Testing configuration.

    NOTE: DATABASE_URL on the base Config is a plain string computed once
    from Config's own DB_NAME - overriding DB_NAME alone on a subclass
    does NOT change it, since Python class attributes aren't re-derived
    for subclasses. DATABASE_URL must be overridden explicitly here too,
    or tests would silently run against the same database as
    development/production.
    """
    DEBUG = True
    TESTING = True
    DB_NAME = 'pickerwheel_test'
    DATABASE_URL = os.environ.get(
        'TEST_DATABASE_URL',
        f'postgresql://{Config.DB_USER}:{Config.DB_PASSWORD}@{Config.DB_HOST}:{Config.DB_PORT}/{DB_NAME}'
    )


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
