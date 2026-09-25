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
    
    # Event settings
    DEFAULT_EVENT_ID = 1
    
    # Socket.IO settings
    SOCKETIO_MESSAGE_QUEUE = os.environ.get('SOCKETIO_MESSAGE_QUEUE', None)
    
    # Feature flags
    REALTIME_WHEEL_UPDATES = os.environ.get('REALTIME_WHEEL_UPDATES', 'true').lower() == 'true'


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
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    DB_NAME = 'pickerwheel_test'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
