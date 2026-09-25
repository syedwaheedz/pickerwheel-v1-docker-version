"""
PickerWheel Database Module
PostgreSQL connection pool and session management
"""

import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# Global database engine and session factory
engine = None
Session = None


def init_db(app):
    """Initialize database connection pool"""
    global engine, Session
    
    database_url = app.config['DATABASE_URL']
    pool_size = app.config.get('DB_POOL_SIZE', 10)
    max_overflow = app.config.get('DB_MAX_OVERFLOW', 20)
    pool_timeout = app.config.get('DB_POOL_TIMEOUT', 30)
    
    logger.info(f"Initializing database connection to {database_url.split('@')[1] if '@' in database_url else database_url}")
    
    engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,  # Enable connection health checks
        echo=app.config.get('DEBUG', False)
    )
    
    # Create scoped session factory
    session_factory = sessionmaker(bind=engine)
    Session = scoped_session(session_factory)
    
    logger.info("Database connection pool initialized successfully")
    
    return engine


def get_session():
    """Get a database session"""
    if Session is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    return Session()


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database transaction error: {e}")
        raise
    finally:
        session.close()


def execute_sql(sql, params=None):
    """Execute raw SQL and return results"""
    with session_scope() as session:
        result = session.execute(text(sql), params or {})
        if result.returns_rows:
            return [dict(row._mapping) for row in result]
        return None


def execute_function(func_name, *args):
    """Execute a PostgreSQL function"""
    with session_scope() as session:
        placeholders = ', '.join([f':arg{i}' for i in range(len(args))])
        params = {f'arg{i}': arg for i, arg in enumerate(args)}
        
        sql = f"SELECT * FROM {func_name}({placeholders})"
        result = session.execute(text(sql), params)
        
        if result.returns_rows:
            return [dict(row._mapping) for row in result]
        return None


class DatabaseManager:
    """Database manager for direct queries"""
    
    @staticmethod
    def get_connection():
        """Get a raw connection from the pool"""
        if engine is None:
            raise RuntimeError("Database not initialized")
        return engine.connect()
    
    @staticmethod
    def execute_with_transaction(queries):
        """Execute multiple queries in a single transaction"""
        with session_scope() as session:
            results = []
            for sql, params in queries:
                result = session.execute(text(sql), params or {})
                if result.returns_rows:
                    results.append([dict(row._mapping) for row in result])
                else:
                    results.append(None)
            return results

