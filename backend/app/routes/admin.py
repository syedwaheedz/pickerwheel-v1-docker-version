"""
Admin API Routes
Endpoints for prize management (add, remove, enable/disable)
"""

import logging
from datetime import date, datetime
from flask import Blueprint, request, jsonify, current_app
from functools import wraps
from ..models import Prize, PrizeCategory, Inventory, Transaction, SpecialEvent, DailyPrizeTemplate, DateTemplateAssignment, GuaranteedWin
from ..services import InventoryService, SpinService, RealtimeService

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)


def require_admin_auth(f):
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for password in request body or headers
        data = request.get_json(silent=True) or {}
        password = data.get('admin_password') or request.headers.get('X-Admin-Password')
        
        expected_password = current_app.config.get('ADMIN_PASSWORD', 'myTAdmin2025')
        
        if password != expected_password:
            return jsonify({
                'success': False,
                'error': 'Invalid admin password'
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function


# =====================================================
# PRIZE MANAGEMENT
# =====================================================

@admin_bp.route('/prizes', methods=['GET'])
@require_admin_auth
def list_prizes():
    """List all prizes with inventory status"""
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        inventory_status = InventoryService.get_inventory_status(event_id, target_date)
        
        return jsonify({
            'success': True,
            **inventory_status
        })
    except Exception as e:
        logger.error(f"Error listing prizes: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/prizes', methods=['POST'])
@require_admin_auth
def add_prize():
    """Add a new prize"""
    try:
        data = request.get_json() or {}
        
        name = data.get('name')
        category_id = data.get('category_id')
        emoji = data.get('emoji', '🎁')
        description = data.get('description')
        display_order = data.get('display_order', 0)
        initial_quantity = data.get('initial_quantity', 10)
        daily_limit = data.get('daily_limit', 5)
        budget_tier = data.get('budget_tier', 'budget')

        if not name or not category_id:
            return jsonify({
                'success': False,
                'error': 'Name and category_id are required'
            }), 400

        if budget_tier not in ('budget', 'mid_budget', 'high_end'):
            return jsonify({
                'success': False,
                'error': "budget_tier must be one of 'budget', 'mid_budget', 'high_end'"
            }), 400

        # Create prize
        prize = Prize.create(name, category_id, emoji, description, display_order, budget_tier)
        
        if not prize:
            return jsonify({
                'success': False,
                'error': 'Failed to create prize'
            }), 500
        
        # Create inventory for the prize
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        InventoryService.initialize_inventory_for_prize(
            prize['id'], category_id, event_id,
            start_date=date.today(), days=30
        )
        
        # Get full prize with category info
        full_prize = Prize.get_by_id(prize['id'])
        
        # Broadcast to all clients via WebSocket
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)
        RealtimeService.broadcast_prize_added(full_prize)
        
        logger.info(f"Admin added prize: {name} (ID: {prize['id']})")
        
        return jsonify({
            'success': True,
            'prize': full_prize,
            'message': f'Prize "{name}" added successfully'
        })
    except Exception as e:
        logger.error(f"Error adding prize: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/prizes/<int:prize_id>', methods=['DELETE'])
@require_admin_auth
def remove_prize(prize_id):
    """Remove (soft delete) a prize"""
    try:
        result = Prize.delete(prize_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Prize not found'
            }), 404
        
        # Broadcast to all clients via WebSocket
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)
        RealtimeService.broadcast_prize_removed(prize_id, result.get('name'))
        
        logger.info(f"Admin removed prize: {result.get('name')} (ID: {prize_id})")
        
        return jsonify({
            'success': True,
            'message': f'Prize "{result.get("name")}" removed successfully'
        })
    except Exception as e:
        logger.error(f"Error removing prize: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/prizes/<int:prize_id>/toggle', methods=['POST'])
@require_admin_auth
def toggle_prize(prize_id):
    """Enable or disable a prize"""
    try:
        data = request.get_json() or {}
        is_enabled = data.get('is_enabled')
        
        if is_enabled is None:
            return jsonify({
                'success': False,
                'error': 'is_enabled is required'
            }), 400
        
        result = Prize.toggle_enabled(prize_id, is_enabled)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Prize not found'
            }), 404
        
        # Broadcast to all clients via WebSocket
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)
        RealtimeService.broadcast_prize_enabled_changed(prize_id, is_enabled, result.get('name'))
        
        status = 'enabled' if is_enabled else 'disabled'
        logger.info(f"Admin {status} prize: {result.get('name')} (ID: {prize_id})")
        
        return jsonify({
            'success': True,
            'prize': result,
            'message': f'Prize "{result.get("name")}" {status}'
        })
    except Exception as e:
        logger.error(f"Error toggling prize: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/prizes/<int:prize_id>', methods=['PUT'])
@require_admin_auth
def update_prize(prize_id):
    """Update prize details"""
    try:
        data = request.get_json() or {}
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}

        if 'budget_tier' in update_data and update_data['budget_tier'] not in ('budget', 'mid_budget', 'high_end'):
            return jsonify({
                'success': False,
                'error': "budget_tier must be one of 'budget', 'mid_budget', 'high_end'"
            }), 400

        result = Prize.update(prize_id, **update_data)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Prize not found or no valid fields to update'
            }), 404
        
        # Broadcast to all clients
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'prize': result,
            'message': 'Prize updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating prize: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# INVENTORY MANAGEMENT
# =====================================================

@admin_bp.route('/inventory', methods=['GET'])
@require_admin_auth
def get_inventory():
    """Get inventory status for all prizes"""
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        status = InventoryService.get_inventory_status(event_id, target_date)
        
        return jsonify({
            'success': True,
            **status
        })
    except Exception as e:
        logger.error(f"Error getting inventory: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/inventory/<int:prize_id>/set', methods=['POST'])
@require_admin_auth
def set_inventory(prize_id):
    """Set inventory quantity and/or daily limit for a prize"""
    try:
        data = request.get_json() or {}
        quantity = data.get('quantity')
        daily_limit = data.get('daily_limit')
        
        if quantity is None and daily_limit is None:
            return jsonify({
                'success': False,
                'error': 'quantity or daily_limit is required'
            }), 400
        
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = data.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        result = None
        
        # Update inventory quantity if provided
        if quantity is not None:
            result = InventoryService.set_quantity(prize_id, quantity, event_id, target_date)
            if not result:
                return jsonify({
                    'success': False,
                    'error': 'Inventory not found'
                }), 404
        
        # Update daily limit if provided
        if daily_limit is not None:
            try:
                daily_limit = int(daily_limit)
            except (TypeError, ValueError):
                daily_limit = -1
            if daily_limit < 0:
                return jsonify({
                    'success': False,
                    'error': 'daily_limit must be a non-negative integer'
                }), 400

            # The date's inventory row is what the admin table shows and what
            # spins enforce (consume_prize / get_available_prizes)
            result = Inventory.update_quantity(
                prize_id, event_id, target_date, daily_limit=daily_limit
            )
            if not result:
                return jsonify({
                    'success': False,
                    'error': 'Inventory not found'
                }), 404

            # Keep the default template in step so future dates populated
            # from it use the same limit. Only the limit changes - the
            # template's quantity and enabled flag are left as configured.
            default_template = DailyPrizeTemplate.get_default()
            if default_template:
                DailyPrizeTemplate.set_prize_daily_limit(
                    default_template['id'], prize_id, daily_limit
                )

            logger.info(f"Updated daily_limit for prize {prize_id} on {target_date} to {daily_limit}")
        
        # Broadcast update
        if quantity is not None:
            RealtimeService.broadcast_prize_update(prize_id, quantity)
        
        prizes = SpinService.get_wheel_prizes(event_id, target_date)
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'inventory': result,
            'message': f'Inventory updated'
        })
    except Exception as e:
        logger.error(f"Error setting inventory: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/inventory/replenish', methods=['POST'])
@require_admin_auth
def replenish_all():
    """Replenish all inventory to initial quantities"""
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        data = request.get_json() or {}
        target_date_str = data.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        results = InventoryService.replenish_all(event_id, target_date)
        
        # Broadcast full prize update
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'replenished_count': len(results),
            'message': f'Replenished {len(results)} prizes'
        })
    except Exception as e:
        logger.error(f"Error replenishing inventory: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# STATISTICS & TRANSACTIONS
# =====================================================

@admin_bp.route('/stats', methods=['GET'])
@require_admin_auth
def get_admin_stats():
    """Get detailed statistics for admin"""
    try:
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        
        target_date_str = request.args.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        
        stats = SpinService.get_daily_stats(event_id, target_date)
        inventory = InventoryService.get_inventory_status(event_id, target_date)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'inventory_summary': inventory['summary']
        })
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/transactions', methods=['GET'])
@require_admin_auth
def get_transactions():
    """Get recent transactions"""
    try:
        target_date_str = request.args.get('date')
        limit = request.args.get('limit', 100, type=int)
        
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            transactions = Transaction.get_for_date(target_date, limit=limit)
        else:
            transactions = Transaction.get_recent(limit=limit)
        
        return jsonify({
            'success': True,
            'transactions': transactions,
            'count': len(transactions)
        })
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# CATEGORIES
# =====================================================

@admin_bp.route('/categories', methods=['GET'])
@require_admin_auth
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


# =====================================================
# SPECIAL EVENTS MANAGEMENT
# =====================================================

@admin_bp.route('/special-events', methods=['GET'])
@require_admin_auth
def list_special_events():
    """List all special events"""
    try:
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        events = SpecialEvent.get_all(include_inactive=include_inactive)
        
        # Get active events (currently running)
        active_now = SpecialEvent.get_active_now()
        
        return jsonify({
            'success': True,
            'events': events,
            'active_now': active_now,
            'total_count': len(events)
        })
    except Exception as e:
        logger.error(f"Error listing special events: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events', methods=['POST'])
@require_admin_auth
def create_special_event():
    """Create a new special event (festival/promotion)"""
    try:
        data = request.get_json() or {}
        
        name = data.get('name')
        start_datetime = data.get('start_datetime')
        end_datetime = data.get('end_datetime')
        event_type = data.get('event_type', 'promotion')
        description = data.get('description')
        prize_ids = data.get('prize_ids', [])
        theme_config = data.get('theme_config', {})
        
        if not name or not start_datetime or not end_datetime:
            return jsonify({
                'success': False,
                'error': 'name, start_datetime, and end_datetime are required'
            }), 400
        
        # Parse datetime strings
        try:
            start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        except ValueError as e:
            return jsonify({
                'success': False,
                'error': f'Invalid datetime format: {e}'
            }), 400
        
        # Create the event
        event = SpecialEvent.create(name, start_dt, end_dt, event_type, description)
        
        if not event:
            return jsonify({
                'success': False,
                'error': 'Failed to create special event'
            }), 500
        
        # Update theme config if provided
        if theme_config:
            SpecialEvent.update_theme_config(event['id'], theme_config)
        
        # Add prizes to the event
        for prize_id in prize_ids:
            SpecialEvent.add_prize(event['id'], prize_id)
        
        # Get full event with prizes
        full_event = SpecialEvent.get_by_id(event['id'])
        
        logger.info(f"Admin created special event: {name} (ID: {event['id']})")
        
        return jsonify({
            'success': True,
            'event': full_event,
            'message': f'Special event "{name}" created successfully'
        })
    except Exception as e:
        logger.error(f"Error creating special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>', methods=['GET'])
@require_admin_auth
def get_special_event(event_id):
    """Get a specific special event with prizes"""
    try:
        event = SpecialEvent.get_by_id(event_id)
        
        if not event:
            return jsonify({
                'success': False,
                'error': 'Special event not found'
            }), 404
        
        return jsonify({
            'success': True,
            'event': event
        })
    except Exception as e:
        logger.error(f"Error getting special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>', methods=['PUT'])
@require_admin_auth
def update_special_event(event_id):
    """Update a special event"""
    try:
        data = request.get_json() or {}
        
        # Handle datetime parsing
        if 'start_datetime' in data:
            try:
                data['start_datetime'] = datetime.fromisoformat(
                    data['start_datetime'].replace('Z', '+00:00')
                )
            except ValueError:
                pass
        
        if 'end_datetime' in data:
            try:
                data['end_datetime'] = datetime.fromisoformat(
                    data['end_datetime'].replace('Z', '+00:00')
                )
            except ValueError:
                pass
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}
        
        result = SpecialEvent.update(event_id, **update_data)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Special event not found or no valid fields to update'
            }), 404
        
        return jsonify({
            'success': True,
            'event': result,
            'message': 'Special event updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>', methods=['DELETE'])
@require_admin_auth
def delete_special_event(event_id):
    """Delete a special event"""
    try:
        result = SpecialEvent.delete(event_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Special event not found'
            }), 404
        
        logger.info(f"Admin deleted special event: {result.get('name')} (ID: {event_id})")
        
        return jsonify({
            'success': True,
            'message': f'Special event "{result.get("name")}" deleted successfully'
        })
    except Exception as e:
        logger.error(f"Error deleting special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>/toggle', methods=['POST'])
@require_admin_auth
def toggle_special_event(event_id):
    """Toggle active status of a special event"""
    try:
        data = request.get_json() or {}
        is_active = data.get('is_active')
        
        if is_active is None:
            return jsonify({
                'success': False,
                'error': 'is_active is required'
            }), 400
        
        result = SpecialEvent.toggle_active(event_id, is_active)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Special event not found'
            }), 404
        
        status = 'activated' if is_active else 'deactivated'
        logger.info(f"Admin {status} special event: {result.get('name')} (ID: {event_id})")
        
        return jsonify({
            'success': True,
            'event': result,
            'message': f'Special event "{result.get("name")}" {status}'
        })
    except Exception as e:
        logger.error(f"Error toggling special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>/theme', methods=['PUT'])
@require_admin_auth
def update_event_theme(event_id):
    """Update theme configuration for a special event"""
    try:
        data = request.get_json() or {}
        theme_config = data.get('theme_config', {})
        
        if not theme_config:
            return jsonify({
                'success': False,
                'error': 'theme_config is required'
            }), 400
        
        result = SpecialEvent.update_theme_config(event_id, theme_config)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Special event not found'
            }), 404
        
        logger.info(f"Admin updated theme for event: {result.get('name')} (ID: {event_id})")
        
        return jsonify({
            'success': True,
            'event': result,
            'message': 'Theme configuration updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating event theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>/theme', methods=['DELETE'])
@require_admin_auth
def reset_event_theme(event_id):
    """Reset theme configuration for a special event to empty (use default)"""
    try:
        # Set theme_config to empty dict to reset to default
        result = SpecialEvent.update_theme_config(event_id, {})
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Special event not found'
            }), 404
        
        logger.info(f"Admin reset theme for event: {result.get('name')} (ID: {event_id})")
        
        return jsonify({
            'success': True,
            'event': result,
            'message': 'Theme configuration reset to default'
        })
    except Exception as e:
        logger.error(f"Error resetting event theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>/prizes', methods=['POST'])
@require_admin_auth
def add_prize_to_event(event_id):
    """Add a prize to a special event"""
    try:
        data = request.get_json() or {}
        
        prize_id = data.get('prize_id')
        boost_enabled = data.get('boost_enabled', True)
        weight_multiplier = data.get('weight_multiplier', 1.5)
        quantity_override = data.get('quantity_override')
        
        if not prize_id:
            return jsonify({
                'success': False,
                'error': 'prize_id is required'
            }), 400
        
        result = SpecialEvent.add_prize(event_id, prize_id, boost_enabled, weight_multiplier, quantity_override)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Failed to add prize to event'
            }), 500
        
        return jsonify({
            'success': True,
            'event_prize': result,
            'message': 'Prize added to special event'
        })
    except Exception as e:
        logger.error(f"Error adding prize to event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/<int:event_id>/prizes/<int:prize_id>', methods=['DELETE'])
@require_admin_auth
def remove_prize_from_event(event_id, prize_id):
    """Remove a prize from a special event"""
    try:
        result = SpecialEvent.remove_prize(event_id, prize_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Prize not found in this event'
            }), 404
        
        return jsonify({
            'success': True,
            'message': 'Prize removed from special event'
        })
    except Exception as e:
        logger.error(f"Error removing prize from event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/special-events/active', methods=['GET'])
def get_active_special_events():
    """Get currently active special events (public endpoint)"""
    try:
        events = SpecialEvent.get_active_now()
        
        return jsonify({
            'success': True,
            'events': events,
            'count': len(events)
        })
    except Exception as e:
        logger.error(f"Error getting active special events: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# THEME SETTINGS
# =====================================================

@admin_bp.route('/settings/force-default-theme', methods=['GET'])
def get_force_default_theme():
    """Get current force default theme setting"""
    force_default = current_app.config.get('FORCE_DEFAULT_THEME', False)
    return jsonify({
        'success': True,
        'force_default_theme': force_default
    })


@admin_bp.route('/settings/force-default-theme', methods=['POST'])
@require_admin_auth
def toggle_force_default_theme():
    """Toggle force default theme setting"""
    try:
        data = request.get_json() or {}
        force_default = data.get('force_default_theme')
        
        if force_default is None:
            return jsonify({
                'success': False,
                'error': 'force_default_theme is required'
            }), 400
        
        # Update the config setting (runtime only)
        current_app.config['FORCE_DEFAULT_THEME'] = bool(force_default)
        
        status = 'enabled' if force_default else 'disabled'
        logger.info(f"Admin {status} force default theme")
        
        return jsonify({
            'success': True,
            'force_default_theme': bool(force_default),
            'message': f'Force default theme {status}'
        })
    except Exception as e:
        logger.error(f"Error toggling force default theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/settings/default-theme', methods=['GET'])
def get_default_theme_setting():
    """Get the current default theme configuration"""
    from ..database import get_setting
    try:
        theme = get_setting('default_theme')
        if not theme:
            # Return fallback if no theme in database
            theme = {
                "name": "default",
                "background": {"type": "gradient", "colors": ["#E20074", "#FFF5F8", "#FF4D9F"], "style": "radial"},
                "wheel": {"colors": ["#E20074", "#FF4D9F", "#B8005D", "#FF80B5", "#9E0052", "#FF66A3"], "borderColor": "#B8005D", "textColor": "#FFFFFF"},
                "header": {"backgroundColor": "#E20074", "gradientEnd": "#B8005D", "textColor": "#FFFFFF", "title": "SPIN & WIN", "subtitle": "Win Exciting Prizes!"},
                "floatingElements": ["🎁", "✨", "💫", "🎊", "🏆", "⭐", "🎈", "🎉"]
            }
        return jsonify({
            'success': True,
            'theme': theme
        })
    except Exception as e:
        logger.error(f"Error getting default theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/settings/default-theme', methods=['PUT'])
@require_admin_auth
def update_default_theme():
    """Update the default theme configuration"""
    from ..database import set_setting
    try:
        data = request.get_json() or {}
        theme = data.get('theme')
        
        if not theme:
            return jsonify({
                'success': False,
                'error': 'theme configuration is required'
            }), 400
        
        # Validate required theme structure
        required_keys = ['background', 'wheel', 'header']
        for key in required_keys:
            if key not in theme:
                return jsonify({
                    'success': False,
                    'error': f'Missing required theme key: {key}'
                }), 400
        
        # Ensure name is set
        theme['name'] = theme.get('name', 'default')
        
        # Save to database
        result = set_setting('default_theme', theme)
        
        if result:
            logger.info("Admin updated default theme")
            return jsonify({
                'success': True,
                'theme': theme,
                'message': 'Default theme updated successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save theme'
            }), 500
            
    except Exception as e:
        logger.error(f"Error updating default theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/settings/default-theme/reset', methods=['POST'])
@require_admin_auth
def reset_default_theme_to_factory():
    """Reset default theme to factory settings (Neon Magenta)"""
    from ..database import set_setting
    try:
        factory_theme = {
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
        
        result = set_setting('default_theme', factory_theme)
        
        if result:
            logger.info("Admin reset default theme to factory settings")
            return jsonify({
                'success': True,
                'theme': factory_theme,
                'message': 'Default theme reset to factory settings'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to reset theme'
            }), 500
            
    except Exception as e:
        logger.error(f"Error resetting default theme: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# PRIZE TEMPLATES
# =====================================================

@admin_bp.route('/templates', methods=['GET'])
@require_admin_auth
def list_templates():
    """List all daily prize templates"""
    try:
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        templates = DailyPrizeTemplate.get_all(include_inactive=include_inactive)
        
        return jsonify({
            'success': True,
            'templates': templates,
            'count': len(templates)
        })
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>', methods=['GET'])
@require_admin_auth
def get_template(template_id):
    """Get a specific template with its prizes"""
    try:
        template = DailyPrizeTemplate.get_by_id(template_id)
        
        if not template:
            return jsonify({
                'success': False,
                'error': 'Template not found'
            }), 404
        
        return jsonify({
            'success': True,
            'template': template
        })
    except Exception as e:
        logger.error(f"Error getting template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/default', methods=['GET'])
@require_admin_auth
def get_default_template():
    """Get the default template"""
    try:
        template = DailyPrizeTemplate.get_default()
        
        if not template:
            return jsonify({
                'success': False,
                'error': 'No default template found'
            }), 404
        
        return jsonify({
            'success': True,
            'template': template
        })
    except Exception as e:
        logger.error(f"Error getting default template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates', methods=['POST'])
@require_admin_auth
def create_template():
    """Create a new prize template"""
    try:
        data = request.get_json() or {}
        
        name = data.get('name')
        description = data.get('description')
        is_default = data.get('is_default', False)
        prizes = data.get('prizes', [])
        
        if not name:
            return jsonify({
                'success': False,
                'error': 'name is required'
            }), 400
        
        # Create template
        template = DailyPrizeTemplate.create(name, description, is_default)
        
        if not template:
            return jsonify({
                'success': False,
                'error': 'Failed to create template'
            }), 500
        
        # Add prizes to template
        for prize_data in prizes:
            DailyPrizeTemplate.add_prize(
                template['id'],
                prize_data['prize_id'],
                prize_data.get('quantity', 1),
                prize_data.get('daily_limit'),
                prize_data.get('is_enabled', True)
            )
        
        # Get full template
        full_template = DailyPrizeTemplate.get_by_id(template['id'])
        
        logger.info(f"Admin created template: {name} (ID: {template['id']})")
        
        return jsonify({
            'success': True,
            'template': full_template,
            'message': f'Template "{name}" created successfully'
        })
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>', methods=['PUT'])
@require_admin_auth
def update_template(template_id):
    """Update a template"""
    try:
        data = request.get_json() or {}
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}
        
        result = DailyPrizeTemplate.update(template_id, **update_data)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Template not found or no valid fields to update'
            }), 404
        
        return jsonify({
            'success': True,
            'template': result,
            'message': 'Template updated successfully'
        })
    except Exception as e:
        logger.error(f"Error updating template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>', methods=['DELETE'])
@require_admin_auth
def delete_template(template_id):
    """Delete a template (cannot delete default)"""
    try:
        result = DailyPrizeTemplate.delete(template_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Template not found or is the default template'
            }), 404
        
        logger.info(f"Admin deleted template: {result.get('name')} (ID: {template_id})")
        
        return jsonify({
            'success': True,
            'message': f'Template "{result.get("name")}" deleted successfully'
        })
    except Exception as e:
        logger.error(f"Error deleting template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>/populate-all', methods=['POST'])
@require_admin_auth
def populate_template_with_all_prizes(template_id):
    """Populate a template with all active prizes from the database"""
    try:
        data = request.get_json() or {}
        default_quantity = data.get('quantity', 5)
        default_daily_limit = data.get('daily_limit', None)
        clear_existing = data.get('clear_existing', True)
        
        # Get template to verify it exists
        template = DailyPrizeTemplate.get_by_id(template_id)
        if not template:
            return jsonify({
                'success': False,
                'error': 'Template not found'
            }), 404
        
        # If clear_existing, remove all current prizes from template
        if clear_existing:
            DailyPrizeTemplate.clear_prizes(template_id)
        
        # Get all active prizes
        all_prizes = Prize.get_all(include_inactive=False)
        
        if not all_prizes:
            return jsonify({
                'success': False,
                'error': 'No active prizes found in database'
            }), 400
        
        added_count = 0
        for prize in all_prizes:
            prize_id = prize.get('id') or prize.get('prize_id')
            result = DailyPrizeTemplate.add_prize(
                template_id, 
                prize_id, 
                quantity=default_quantity,
                daily_limit=default_daily_limit,
                is_enabled=True
            )
            if result:
                added_count += 1
        
        logger.info(f"Admin populated template {template_id} with {added_count} prizes")
        
        # Broadcast update to frontend
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        prizes = SpinService.get_wheel_prizes(event_id, date.today())
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'added_count': added_count,
            'total_prizes': len(all_prizes),
            'message': f'Added {added_count} prizes to template'
        })
    except Exception as e:
        logger.error(f"Error populating template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>/prizes', methods=['POST'])
@require_admin_auth
def add_prize_to_template(template_id):
    """Add or update a prize in a template"""
    try:
        data = request.get_json() or {}
        
        prize_id = data.get('prize_id')
        quantity = data.get('quantity', 1)
        daily_limit = data.get('daily_limit')
        is_enabled = data.get('is_enabled', True)
        
        if not prize_id:
            return jsonify({
                'success': False,
                'error': 'prize_id is required'
            }), 400
        
        result = DailyPrizeTemplate.add_prize(template_id, prize_id, quantity, daily_limit, is_enabled)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Failed to add prize to template'
            }), 500
        
        # Broadcast update to frontend
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        prizes = SpinService.get_wheel_prizes(event_id, date.today())
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'template_prize': result,
            'message': 'Prize added to template'
        })
    except Exception as e:
        logger.error(f"Error adding prize to template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>/prizes/<int:prize_id>', methods=['DELETE'])
@require_admin_auth
def remove_prize_from_template(template_id, prize_id):
    """Remove a prize from a template"""
    try:
        result = DailyPrizeTemplate.remove_prize(template_id, prize_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Prize not found in template'
            }), 404
        
        # Broadcast update to frontend
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        prizes = SpinService.get_wheel_prizes(event_id, date.today())
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'message': 'Prize removed from template'
        })
    except Exception as e:
        logger.error(f"Error removing prize from template: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/templates/<int:template_id>/prizes/<int:template_prize_id>', methods=['PUT'])
@require_admin_auth
def update_template_prize(template_id, template_prize_id):
    """Update a prize in a template"""
    try:
        data = request.get_json() or {}
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}
        
        result = DailyPrizeTemplate.update_prize(template_prize_id, **update_data)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Template prize not found'
            }), 404
        
        # Broadcast update to frontend
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        prizes = SpinService.get_wheel_prizes(event_id, date.today())
        RealtimeService.broadcast_prizes_updated(prizes)
        
        return jsonify({
            'success': True,
            'template_prize': result,
            'message': 'Template prize updated'
        })
    except Exception as e:
        logger.error(f"Error updating template prize: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# DATE TEMPLATE ASSIGNMENTS
# =====================================================

@admin_bp.route('/date-assignments', methods=['GET'])
@require_admin_auth
def list_date_assignments():
    """List date template assignments for a range"""
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        if not start_date_str or not end_date_str:
            # Default to current month
            today = date.today()
            start = date(today.year, today.month, 1)
            if today.month == 12:
                end = date(today.year + 1, 1, 1)
            else:
                end = date(today.year, today.month + 1, 1)
        else:
            start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        assignments = DateTemplateAssignment.get_range(start, end)
        
        return jsonify({
            'success': True,
            'assignments': assignments,
            'date_range': {'start': start.isoformat(), 'end': end.isoformat()},
            'count': len(assignments)
        })
    except Exception as e:
        logger.error(f"Error listing date assignments: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/date-assignments/for-date', methods=['GET'])
@require_admin_auth
def get_date_assignment():
    """Get template assignment for a specific date"""
    try:
        target_date_str = request.args.get('date')
        
        if not target_date_str:
            target_date = date.today()
        else:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        
        assignment = DateTemplateAssignment.get_for_date(target_date)
        effective_template = DateTemplateAssignment.get_effective_template(target_date)
        
        return jsonify({
            'success': True,
            'date': target_date.isoformat(),
            'assignment': assignment,
            'effective_template': effective_template
        })
    except Exception as e:
        logger.error(f"Error getting date assignment: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/date-assignments', methods=['POST'])
@require_admin_auth
def assign_template_to_dates():
    """Assign a template to one or more dates"""
    try:
        data = request.get_json() or {}
        
        template_id = data.get('template_id')
        dates = data.get('dates', [])  # List of date strings
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        notes = data.get('notes')
        
        if not template_id:
            return jsonify({
                'success': False,
                'error': 'template_id is required'
            }), 400
        
        results = []
        
        # Handle date range
        if start_date_str and end_date_str:
            start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            results = DateTemplateAssignment.assign_range(start, end, template_id, notes)
        # Handle specific dates
        elif dates:
            for date_str in dates:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                result = DateTemplateAssignment.assign(target_date, template_id, notes)
                if result:
                    results.append(result)
        else:
            return jsonify({
                'success': False,
                'error': 'Either dates array or start_date/end_date range is required'
            }), 400
        
        logger.info(f"Admin assigned template {template_id} to {len(results)} dates")
        
        return jsonify({
            'success': True,
            'assignments': results,
            'count': len(results),
            'message': f'Template assigned to {len(results)} date(s)'
        })
    except Exception as e:
        logger.error(f"Error assigning template to dates: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/date-assignments/<target_date>', methods=['DELETE'])
@require_admin_auth
def unassign_date(target_date):
    """Remove template assignment from a date"""
    try:
        target = datetime.strptime(target_date, '%Y-%m-%d').date()
        result = DateTemplateAssignment.unassign(target)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'No assignment found for this date'
            }), 404
        
        return jsonify({
            'success': True,
            'message': f'Template assignment removed from {target_date}'
        })
    except Exception as e:
        logger.error(f"Error unassigning date: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# GUARANTEED WINS
# =====================================================

@admin_bp.route('/guaranteed-wins', methods=['GET'])
@require_admin_auth
def list_guaranteed_wins():
    """List all guaranteed wins"""
    try:
        status = request.args.get('status')  # pending, triggered, cancelled, expired
        limit = request.args.get('limit', 50, type=int)
        
        wins = GuaranteedWin.get_all(status=status, limit=limit)
        
        # Group by status for easier display
        grouped = {
            'pending': [w for w in wins if w['status'] == 'pending'],
            'triggered': [w for w in wins if w['status'] == 'triggered'],
            'cancelled': [w for w in wins if w['status'] == 'cancelled'],
            'expired': [w for w in wins if w['status'] == 'expired']
        }
        
        return jsonify({
            'success': True,
            'wins': wins,
            'grouped': grouped,
            'count': len(wins)
        })
    except Exception as e:
        logger.error(f"Error listing guaranteed wins: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/<int:win_id>', methods=['GET'])
@require_admin_auth
def get_guaranteed_win(win_id):
    """Get a specific guaranteed win"""
    try:
        win = GuaranteedWin.get_by_id(win_id)
        
        if not win:
            return jsonify({
                'success': False,
                'error': 'Guaranteed win not found'
            }), 404
        
        return jsonify({
            'success': True,
            'win': win
        })
    except Exception as e:
        logger.error(f"Error getting guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins', methods=['POST'])
@require_admin_auth
def create_guaranteed_win():
    """Create a guaranteed win (schedule or next spin) with quantity limits"""
    try:
        data = request.get_json() or {}
        
        prize_id = data.get('prize_id')
        scheduled_at_str = data.get('scheduled_at')  # ISO format or None for next spin
        target_identifier = data.get('target_identifier')  # Phone/user ID
        reason = data.get('reason')
        priority = data.get('priority', 0)
        created_by = data.get('created_by', 'Admin')
        max_triggers = data.get('max_triggers', 1)  # How many times to trigger (default: 1)
        expires_at_str = data.get('expires_at')  # When to stop (optional)
        
        if not prize_id:
            return jsonify({
                'success': False,
                'error': 'prize_id is required'
            }), 400
        
        # Parse scheduled_at if provided
        scheduled_at = None
        if scheduled_at_str:
            try:
                scheduled_at = datetime.fromisoformat(scheduled_at_str.replace('Z', '+00:00'))
            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': f'Invalid scheduled_at format: {e}'
                }), 400
        
        # Parse expires_at if provided
        expires_at = None
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': f'Invalid expires_at format: {e}'
                }), 400
        
        win = GuaranteedWin.create(
            prize_id=prize_id,
            scheduled_at=scheduled_at,
            target_identifier=target_identifier,
            reason=reason,
            priority=priority,
            created_by=created_by,
            max_triggers=max_triggers,
            expires_at=expires_at
        )
        
        if not win:
            return jsonify({
                'success': False,
                'error': 'Failed to create guaranteed win'
            }), 500
        
        win_type = "next spin" if scheduled_at is None else f"scheduled at {scheduled_at}"
        logger.info(f"Admin created guaranteed win: Prize {prize_id} - {win_type}")
        
        return jsonify({
            'success': True,
            'win': win,
            'message': f'Guaranteed win scheduled ({win_type})'
        })
    except Exception as e:
        logger.error(f"Error creating guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/<int:win_id>', methods=['PUT'])
@require_admin_auth
def update_guaranteed_win(win_id):
    """Update a guaranteed win (only if pending)"""
    try:
        data = request.get_json() or {}
        
        # Handle scheduled_at parsing
        if 'scheduled_at' in data and data['scheduled_at']:
            try:
                data['scheduled_at'] = datetime.fromisoformat(
                    data['scheduled_at'].replace('Z', '+00:00')
                )
            except ValueError:
                pass
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}
        
        result = GuaranteedWin.update(win_id, **update_data)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Guaranteed win not found or not in pending status'
            }), 404
        
        return jsonify({
            'success': True,
            'win': result,
            'message': 'Guaranteed win updated'
        })
    except Exception as e:
        logger.error(f"Error updating guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/<int:win_id>/cancel', methods=['POST'])
@require_admin_auth
def cancel_guaranteed_win(win_id):
    """Cancel a guaranteed win"""
    try:
        result = GuaranteedWin.cancel(win_id)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Guaranteed win not found or already processed'
            }), 404
        
        logger.info(f"Admin cancelled guaranteed win (ID: {win_id})")
        
        return jsonify({
            'success': True,
            'win': result,
            'message': 'Guaranteed win cancelled'
        })
    except Exception as e:
        logger.error(f"Error cancelling guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/<int:win_id>/trigger-now', methods=['POST'])
@require_admin_auth
def trigger_guaranteed_win_now(win_id):
    """Manually trigger a guaranteed win immediately"""
    try:
        data = request.get_json() or {}
        triggered_by = data.get('triggered_by', 'Admin (Manual)')
        
        result = GuaranteedWin.trigger(win_id, triggered_by)
        
        if not result:
            return jsonify({
                'success': False,
                'error': 'Guaranteed win not found or already processed'
            }), 404
        
        logger.info(f"Admin manually triggered guaranteed win (ID: {win_id})")
        
        return jsonify({
            'success': True,
            'win': result,
            'message': 'Guaranteed win triggered manually'
        })
    except Exception as e:
        logger.error(f"Error triggering guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/expire-old', methods=['POST'])
@require_admin_auth
def expire_old_guaranteed_wins():
    """Expire old guaranteed wins that were never triggered"""
    try:
        count = GuaranteedWin.expire_old()
        
        return jsonify({
            'success': True,
            'expired_count': count,
            'message': f'Expired {count} old guaranteed wins'
        })
    except Exception as e:
        logger.error(f"Error expiring old guaranteed wins: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/guaranteed-wins/pending', methods=['GET'])
def check_pending_guaranteed_win():
    """Check for pending guaranteed win (used by spin service)"""
    try:
        user_identifier = request.args.get('user_identifier')
        
        win = GuaranteedWin.get_pending(user_identifier)
        
        return jsonify({
            'success': True,
            'has_pending': win is not None,
            'win': win
        })
    except Exception as e:
        logger.error(f"Error checking pending guaranteed win: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =====================================================
# TESTING / DANGER ZONE
# =====================================================

@admin_bp.route('/reset-daily-wins', methods=['POST'])
@require_admin_auth
def reset_daily_wins():
    """
    Reset today's wins - FOR TESTING ONLY
    
    This will:
    1. Delete ALL win transactions for today
    2. Reset prize_inventory.remaining_quantity = initial_quantity for today
    3. Return count of reset items
    
    WARNING: This action cannot be undone!
    """
    from ..database import execute_sql
    
    try:
        data = request.get_json() or {}
        confirmation = data.get('confirmation', '')
        
        # Require explicit confirmation
        if confirmation != 'RESET':
            return jsonify({
                'success': False,
                'error': 'Confirmation required. Send {"confirmation": "RESET"} to proceed.'
            }), 400
        
        # Get today's date
        today = date.today()
        
        # Step 1: Count and delete today's win transactions
        count_sql = """
            SELECT COUNT(*) as count FROM transactions 
            WHERE DATE(created_at) = :today AND transaction_type = 'win'
        """
        count_result = execute_sql(count_sql, {'today': today})
        transactions_count = count_result[0]['count'] if count_result else 0
        
        delete_sql = """
            DELETE FROM transactions 
            WHERE DATE(created_at) = :today AND transaction_type = 'win'
            RETURNING id
        """
        deleted = execute_sql(delete_sql, {'today': today})
        deleted_count = len(deleted) if deleted else 0
        
        # Step 2: Reset inventory for today
        reset_sql = """
            UPDATE prize_inventory 
            SET remaining_quantity = initial_quantity, updated_at = NOW()
            WHERE available_date = :today
            RETURNING prize_id, initial_quantity, remaining_quantity
        """
        reset_result = execute_sql(reset_sql, {'today': today})
        inventory_reset_count = len(reset_result) if reset_result else 0
        
        # Log the action
        admin_user = request.headers.get('X-Admin-User', 'Admin')
        logger.warning(f"⚠️ DAILY WINS RESET by {admin_user}: Deleted {deleted_count} transactions, reset {inventory_reset_count} inventory records for {today}")
        
        # Broadcast update to refresh frontend
        RealtimeService.broadcast_prizes_updated(SpinService.get_wheel_prizes(
            current_app.config.get('DEFAULT_EVENT_ID', 1), 
            today
        ))
        
        return jsonify({
            'success': True,
            'message': f'Daily wins reset completed for {today}',
            'details': {
                'date': today.isoformat(),
                'transactions_deleted': deleted_count,
                'inventory_records_reset': inventory_reset_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error resetting daily wins: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
