"""
Public API Routes
Endpoints for wheel display and spin functionality
"""

import logging
from datetime import date, datetime
from flask import Blueprint, request, jsonify, current_app
from ..services import SpinService
from ..models import Prize, PrizeCategory, SpecialEvent
from ..database import get_setting

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)

# Fallback default theme (used if database has no theme)
# Neon Magenta - dark maroon/black base with a hot-pink glow
FALLBACK_DEFAULT_THEME = {
    "name": "default",
    "background": {
        "type": "gradient",
        "colors": ["#E50065", "#09070A", "#650A2C"],
        "style": "radial"
    },
    "wheel": {
        "colors": ["#1B0510", "#E50065", "#2A0716", "#FF4FA3", "#22040F", "#FF2B86"],
        "borderColor": "#FF2B86",
        "textColor": "#FFFFFF"
    },
    "header": {
        "backgroundColor": "#16050D",
        "gradientEnd": "#650A2C",
        "textColor": "#FFFFFF",
        "title": "SPIN & WIN",
        "subtitle": "Win Exciting Prizes!"
    },
    "floatingElements": ["🎁", "✨", "💫", "🎊", "🏆", "⭐", "🎈", "🎉"]
}


def get_default_theme():
    """Get default theme from database or fallback"""
    try:
        db_theme = get_setting('default_theme')
        if db_theme:
            return db_theme
    except Exception as e:
        logger.warning(f"Could not load default theme from database: {e}")
    return FALLBACK_DEFAULT_THEME.copy()


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '2.0.0'
    })


@api_bp.route('/prizes/wheel-display', methods=['GET'])
def get_wheel_display_prizes():
    """
    Get ALL prizes for wheel display (including disabled).
    Disabled prizes are shown but wheel won't land on them.
    """
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        # Get date from query param or use today
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        prizes = SpinService.get_wheel_prizes(event_id, target_date)
        
        return jsonify({
            'success': True,
            'prizes': prizes,
            'total_items': len(prizes),
            'date': target_date.isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting wheel prizes: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/prizes/available', methods=['GET'])
def get_available_prizes():
    """
    Get prizes available for winning (enabled + has inventory).
    Used for spin selection logic.
    """
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        prizes = SpinService.get_available_prizes(event_id, target_date)
        
        return jsonify({
            'success': True,
            'prizes': prizes,
            'available_count': len(prizes),
            'date': target_date.isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting available prizes: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all prize categories"""
    try:
        categories = PrizeCategory.get_all()
        return jsonify({
            'success': True,
            'categories': categories
        })
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/pre-spin', methods=['POST'])
def pre_spin_selection():
    """
    Pre-select a winning prize before wheel animation.
    Returns the prize and target segment index.
    """
    try:
        data = request.get_json() or {}
        user_identifier = data.get('user_id') or request.remote_addr
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = data.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        result = SpinService.pre_spin(user_identifier, event_id, target_date)
        
        if not result['success']:
            return jsonify(result), 400
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in pre-spin: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/spin', methods=['POST'])
def spin_wheel():
    """
    Execute the spin - consume prize and record transaction.
    Called after wheel animation completes.
    Handles guaranteed wins if provided.
    """
    try:
        data = request.get_json() or {}
        user_identifier = data.get('user_id') or request.remote_addr
        prize_id = data.get('selected_prize_id') or data.get('prize_id')
        guaranteed_win_id = data.get('guaranteed_win_id')  # From pre-spin if guaranteed
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        if not prize_id:
            return jsonify({
                'success': False,
                'error': 'Prize ID is required'
            }), 400
        
        target_date_str = data.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        result = SpinService.execute_spin(prize_id, user_identifier, event_id, target_date, guaranteed_win_id)
        
        if not result['success']:
            return jsonify(result), 400
        
        # Get wheel prizes for segment calculation
        wheel_prizes = SpinService.get_wheel_prizes(event_id, target_date)
        sector_index = next(
            (i for i, p in enumerate(wheel_prizes) if p['prize_id'] == prize_id),
            0
        )
        sector_angle = 360 / len(wheel_prizes) if wheel_prizes else 360
        sector_center = sector_index * sector_angle + (sector_angle / 2)
        
        return jsonify({
            'success': True,
            'prize': result['prize'],
            'transaction_id': result['transaction_id'],
            'sector_index': sector_index,
            'sector_center': sector_center,
            'total_segments': len(wheel_prizes),
            'user_id': user_identifier,
            'date': target_date.isoformat(),
            'was_guaranteed': result.get('was_guaranteed', False)
        })
    except Exception as e:
        logger.error(f"Error in spin: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get daily statistics"""
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        stats = SpinService.get_daily_stats(event_id, target_date)
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/daily-prizes-log', methods=['GET'])
def get_daily_prizes_log():
    """Get today's prizes won log for display"""
    try:
        from ..models import Transaction
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        prizes_won = Transaction.get_today_wins(target_date)
        
        return jsonify({
            'success': True,
            'prizes_won': prizes_won,
            'total_count': len(prizes_won),
            'date': target_date.isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting daily prizes log: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/config', methods=['GET'])
def get_frontend_config():
    """
    Get unified frontend configuration including:
    - All prizes from database
    - Active theme (from special event or default)
    - Active special event (if any)
    - General settings
    """
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        target_date = date.today()
        
        # Check if force default theme is enabled
        force_default = current_app.config.get('FORCE_DEFAULT_THEME', False)
        
        # Get all prizes for wheel display
        prizes = SpinService.get_wheel_prizes(event_id, target_date)
        
        # Get currently active special events
        active_events = SpecialEvent.get_active_now()
        
        # Determine active theme - get from database
        active_theme = get_default_theme()
        active_event = None
        
        # Only apply event theme if force_default is not enabled
        if not force_default and active_events:
            active_event = active_events[0]  # Use first active event
            # If event has theme_config, use it
            if active_event.get('theme_config') and isinstance(active_event['theme_config'], dict):
                # Merge with default theme (event theme overrides default)
                event_theme = active_event['theme_config']
                for key in event_theme:
                    if isinstance(event_theme[key], dict) and key in active_theme:
                        active_theme[key] = {**active_theme[key], **event_theme[key]}
                    else:
                        active_theme[key] = event_theme[key]
        
        # Get categories
        categories = PrizeCategory.get_all()
        
        return jsonify({
            'success': True,
            'prizes': prizes,
            'total_prizes': len(prizes),
            'theme': active_theme,
            'event': {
                'id': active_event['id'] if active_event else None,
                'name': active_event['name'] if active_event else None,
                'type': active_event['event_type'] if active_event else None,
                'is_active': active_event is not None
            },
            'categories': categories,
            'settings': {
                'date': target_date.isoformat(),
                'event_id': event_id,
                'force_default_theme': force_default,
                'realtime_updates_enabled': current_app.config.get('REALTIME_WHEEL_UPDATES', True)
            }
        })
    except Exception as e:
        logger.error(f"Error getting frontend config: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/theme/default', methods=['GET'])
def get_default_theme_route():
    """Get the default theme configuration from database"""
    return jsonify({
        'success': True,
        'theme': get_default_theme()
    })
