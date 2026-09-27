"""
WebSocket Handlers
Real-time event handlers for Socket.IO
"""

import logging
from flask import session
from flask_socketio import emit, join_room, leave_room
from ..services.realtime_service import set_socketio, _json_safe
from ..models import Prize

logger = logging.getLogger(__name__)


def _is_admin_authenticated():
    """
    Same session-cookie check the HTTP admin routes use (require_admin_auth
    in routes/admin.py). Flask-SocketIO copies the Flask session in from the
    connecting request's cookie at connect time, so this reflects whatever
    admin.html's earlier POST /api/admin/login already established - no
    password needs to be re-sent over the socket.
    """
    return bool(session.get('admin_authenticated'))


def register_handlers(socketio):
    """Register all WebSocket event handlers"""

    # Set socketio instance for RealtimeService
    set_socketio(socketio)

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        logger.info(f"Client connected")
        emit('connected', {'status': 'connected'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info(f"Client disconnected")
    
    @socketio.on('join')
    def handle_join(data):
        """Handle room join requests"""
        room = data.get('room', 'wheel')
        join_room(room)
        logger.info(f"Client joined room: {room}")
        emit('joined', {'room': room})
    
    @socketio.on('leave')
    def handle_leave(data):
        """Handle room leave requests"""
        room = data.get('room', 'wheel')
        leave_room(room)
        logger.info(f"Client left room: {room}")
    
    @socketio.on('admin:join')
    def handle_admin_join(data=None):
        """Handle admin panel connection"""
        if not _is_admin_authenticated():
            emit('admin:error', {'message': 'Invalid admin password'})
            return
        join_room('admin')
        logger.info("Admin client joined admin room")
        emit('admin:joined', {'status': 'connected to admin room'})
    
    @socketio.on('admin:leave')
    def handle_admin_leave():
        """Handle admin panel disconnection"""
        leave_room('admin')
        logger.info("Admin client left admin room")
    
    @socketio.on('request:prizes')
    def handle_request_prizes():
        """Handle request for current prize list"""
        try:
            prizes = Prize.get_all()
            emit('prizes:updated', _json_safe({'prizes': prizes}))
        except Exception as e:
            logger.error(f"Error getting prizes: {e}")
            emit('error', {'message': 'Failed to get prizes'})
    
    @socketio.on('admin:add_prize')
    def handle_admin_add_prize(data):
        """Handle admin adding a new prize"""
        if not _is_admin_authenticated():
            emit('admin:error', {'message': 'Invalid admin password'})
            return
        try:
            name = data.get('name')
            emoji = data.get('emoji', '🎁')
            description = data.get('description')
            budget_tier = data.get('budget_tier', 'budget')

            if not name:
                emit('admin:error', {'message': 'Name is required'})
                return

            # category_id is derived from budget_tier (BUDGET_TIER_TO_CATEGORY_ID)
            prize = Prize.create(name, None, emoji, description, budget_tier=budget_tier)
            
            if prize:
                # Get updated prize list
                prizes = Prize.get_all()
                # Broadcast to ALL clients
                socketio.emit('prizes:updated', _json_safe({'prizes': prizes}))
                socketio.emit('prize:added', _json_safe({'prize': prize}))
                emit('admin:success', {'message': f'Prize "{name}" added successfully'})
                logger.info(f"Admin added prize via WebSocket: {name}")
            else:
                emit('admin:error', {'message': 'Failed to create prize'})
        except Exception as e:
            logger.error(f"Error adding prize: {e}")
            emit('admin:error', {'message': str(e)})
    
    @socketio.on('admin:remove_prize')
    def handle_admin_remove_prize(data):
        """Handle admin removing a prize"""
        if not _is_admin_authenticated():
            emit('admin:error', {'message': 'Invalid admin password'})
            return
        try:
            prize_id = data.get('prize_id')
            
            if not prize_id:
                emit('admin:error', {'message': 'Prize ID is required'})
                return
            
            result = Prize.delete(prize_id)
            
            if result:
                # Get updated prize list
                prizes = Prize.get_all()
                # Broadcast to ALL clients
                socketio.emit('prizes:updated', _json_safe({'prizes': prizes}))
                socketio.emit('prize:removed', _json_safe({'prize_id': prize_id, 'prize_name': result.get('name')}))
                emit('admin:success', {'message': f'Prize removed successfully'})
                logger.info(f"Admin removed prize via WebSocket: {prize_id}")
            else:
                emit('admin:error', {'message': 'Prize not found'})
        except Exception as e:
            logger.error(f"Error removing prize: {e}")
            emit('admin:error', {'message': str(e)})
    
    @socketio.on('admin:toggle_prize')
    def handle_admin_toggle_prize(data):
        """Handle admin enabling/disabling a prize"""
        if not _is_admin_authenticated():
            emit('admin:error', {'message': 'Invalid admin password'})
            return
        try:
            prize_id = data.get('prize_id')
            is_enabled = data.get('is_enabled')
            
            if prize_id is None or is_enabled is None:
                emit('admin:error', {'message': 'Prize ID and enabled status are required'})
                return
            
            result = Prize.toggle_enabled(prize_id, is_enabled)
            
            if result:
                # Get updated prize list
                prizes = Prize.get_all()
                # Broadcast to ALL clients
                socketio.emit('prizes:updated', _json_safe({'prizes': prizes}))
                socketio.emit('prize:enabled_changed', _json_safe({
                    'prize_id': prize_id,
                    'is_enabled': is_enabled,
                    'prize_name': result.get('name')
                }))
                status = 'enabled' if is_enabled else 'disabled'
                emit('admin:success', {'message': f'Prize {status} successfully'})
                logger.info(f"Admin toggled prize via WebSocket: {prize_id} -> {is_enabled}")
            else:
                emit('admin:error', {'message': 'Prize not found'})
        except Exception as e:
            logger.error(f"Error toggling prize: {e}")
            emit('admin:error', {'message': str(e)})
    
    @socketio.on('ping')
    def handle_ping():
        """Handle ping for keepalive"""
        emit('pong')
    
    logger.info("WebSocket handlers registered")
