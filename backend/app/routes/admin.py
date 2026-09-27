"""
Admin API Routes
Endpoints for prize management (add, remove, enable/disable)
"""

import hmac
import logging
from datetime import date, datetime
from flask import Blueprint, request, jsonify, current_app, session
from functools import wraps
from ..models import Prize, PrizeCategory, Inventory, Transaction, SpecialEvent, DailyPrizeTemplate, DateTemplateAssignment, GuaranteedWin
from ..services import InventoryService, SpinService, RealtimeService
from ..database import execute_transaction, run_in_transaction, log_audit
from sqlalchemy import text
import json

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)


def _actor():
    """
    The human-readable name of whoever is making this request, for the
    audit log. Sent by admin.html as admin_actor once per browser session
    (see connectLiveUpdates()/the actor-name prompt) - a real per-device/
    per-person identity is the actual long-term fix (deferred item #18
    on the multi-device board), but this at least makes 'who did this'
    answerable without it, since every admin currently shares one
    password and audit_log used to just say 'admin' for everything.
    """
    data = request.get_json(silent=True) or {}
    return (
        request.headers.get('X-Admin-Actor')
        or data.get('admin_actor')
        or 'unknown'
    )


def require_admin_auth(f):
    """
    Decorator to require admin authentication. Checks the server-side
    session set by POST /login, rather than a password sent on every
    request - the password itself is only ever transmitted once, at login.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return jsonify({
                'success': False,
                'error': 'Not authenticated'
            }), 401

        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/login', methods=['POST'])
def login():
    """Verify the admin password once and start a session cookie."""
    data = request.get_json(silent=True) or {}
    password = data.get('admin_password') or request.headers.get('X-Admin-Password') or ''

    expected_password = current_app.config.get('ADMIN_PASSWORD', 'myTAdmin2025')

    if not hmac.compare_digest(password, expected_password):
        return jsonify({
            'success': False,
            'error': 'Invalid admin password'
        }), 401

    session.permanent = True
    session['admin_authenticated'] = True
    return jsonify({'success': True})


@admin_bp.route('/logout', methods=['POST'])
def logout():
    """Clear the admin session."""
    session.pop('admin_authenticated', None)
    return jsonify({'success': True})


@admin_bp.route('/session', methods=['GET'])
def check_session():
    """
    Lets the admin page tell, on load/refresh, whether it already has a
    valid session cookie - so a refresh doesn't force the login screen
    again while the session is still good.
    """
    if session.get('admin_authenticated'):
        return jsonify({'success': True, 'authenticated': True})
    return jsonify({'success': False, 'authenticated': False}), 401


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
        emoji = data.get('emoji', '🎁')
        description = data.get('description')
        display_order = data.get('display_order', 0)
        initial_quantity = data.get('initial_quantity', 10)
        daily_limit = data.get('daily_limit', 5)
        budget_tier = data.get('budget_tier', 'budget')

        if not name:
            return jsonify({
                'success': False,
                'error': 'Name is required'
            }), 400

        if budget_tier not in ('budget', 'mid_budget', 'high_end'):
            return jsonify({
                'success': False,
                'error': "budget_tier must be one of 'budget', 'mid_budget', 'high_end'"
            }), 400

        try:
            initial_quantity = int(initial_quantity)
            daily_limit = int(daily_limit)
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': 'initial_quantity and daily_limit must be integers'
            }), 400
        if initial_quantity < 0 or daily_limit < 0:
            return jsonify({
                'success': False,
                'error': 'initial_quantity and daily_limit must be non-negative'
            }), 400

        # Create prize - category_id is derived from budget_tier
        # (BUDGET_TIER_TO_CATEGORY_ID), never taken from the client
        prize = Prize.create(name, None, emoji, description, display_order, budget_tier)

        if not prize:
            return jsonify({
                'success': False,
                'error': 'Failed to create prize'
            }), 500

        # Create inventory for the prize, honoring the admin-entered
        # quantity/daily-limit instead of silently falling back to
        # category defaults
        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        InventoryService.initialize_inventory_for_prize(
            prize['id'], prize['category_id'], event_id,
            start_date=date.today(), days=30,
            initial_quantity=initial_quantity, daily_limit=daily_limit
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


@admin_bp.route('/prizes/tier/<budget_tier>/toggle', methods=['POST'])
@require_admin_auth
def toggle_prize_tier(budget_tier):
    """
    Master toggle: enable or disable every prize in a budget tier
    (budget / mid_budget / high_end) in one action. Prizes stay
    individually toggleable afterwards - this is a bulk convenience
    over the existing per-prize is_enabled flag, not a new tier-level
    flag, so re-enabling one prize in an otherwise-disabled tier works
    exactly like it does today.
    """
    try:
        if budget_tier not in ('budget', 'mid_budget', 'high_end'):
            return jsonify({
                'success': False,
                'error': 'budget_tier must be one of: budget, mid_budget, high_end'
            }), 400

        data = request.get_json() or {}
        is_enabled = data.get('is_enabled')

        if is_enabled is None:
            return jsonify({
                'success': False,
                'error': 'is_enabled is required'
            }), 400

        results = Prize.toggle_enabled_by_tier(budget_tier, is_enabled)

        # Broadcast + audit even when 0 prizes matched (an admin flipping
        # an empty tier should still see it reflected, and an empty
        # result isn't an error - just distinguish it in the message)
        prizes = Prize.get_all()
        RealtimeService.broadcast_prizes_updated(prizes)

        log_audit('bulk_toggle_enabled', 'prize_tier', None, performed_by=_actor(),
                   new_value={'budget_tier': budget_tier, 'is_enabled': is_enabled,
                              'affected_count': len(results)})

        status = 'enabled' if is_enabled else 'disabled'
        logger.info(f"Admin {status} all '{budget_tier}' prizes ({len(results)} affected)")

        return jsonify({
            'success': True,
            'affected_count': len(results),
            'prizes': results,
            'message': f'{len(results)} {budget_tier.replace("_", "-")} prize(s) {status}'
        })
    except Exception as e:
        logger.error(f"Error toggling prize tier {budget_tier}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/prizes/<int:prize_id>', methods=['PUT'])
@require_admin_auth
def update_prize(prize_id):
    """Update prize details"""
    try:
        data = request.get_json() or {}

        # Remove admin_password from update data. category_id is also
        # dropped here even if a client sends it - it's derived from
        # budget_tier (see Prize.update()), not independently settable
        # through this API.
        update_data = {k: v for k, v in data.items() if k not in ('admin_password', 'category_id')}

        if 'budget_tier' in update_data and update_data['budget_tier'] not in ('budget', 'mid_budget', 'high_end'):
            return jsonify({
                'success': False,
                'error': "budget_tier must be one of 'budget', 'mid_budget', 'high_end'"
            }), 400

        # Optimistic concurrency: required so a stale device can't
        # silently overwrite a change made from another one since it last
        # loaded this prize.
        expected_updated_at_str = update_data.pop('expected_updated_at', None)
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /prizes)'
            }), 400
        try:
            expected_updated_at = datetime.fromisoformat(
                expected_updated_at_str.replace('Z', '+00:00')
            )
        except (ValueError, AttributeError):
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        result = Prize.update(prize_id, expected_updated_at=expected_updated_at, **update_data)

        if not result:
            if not Prize.get_by_id(prize_id):
                return jsonify({
                    'success': False,
                    'error': 'Prize not found'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This prize was changed by someone else - reload and try again'
            }), 409

        log_audit('update', 'prize', prize_id, performed_by=_actor(), new_value=update_data)

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

        if quantity is not None:
            try:
                quantity = int(quantity)
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'error': 'quantity must be a non-negative integer'
                }), 400
            if quantity < 0:
                return jsonify({
                    'success': False,
                    'error': 'quantity must be a non-negative integer'
                }), 400

        if daily_limit is not None:
            try:
                daily_limit = int(daily_limit)
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'error': 'daily_limit must be a non-negative integer'
                }), 400
            if daily_limit < 0:
                return jsonify({
                    'success': False,
                    'error': 'daily_limit must be a non-negative integer'
                }), 400

        # Optimistic concurrency: the caller must send back the updated_at
        # it last loaded (from GET /inventory). If someone else changed
        # this row since then, the UPDATE below matches zero rows instead
        # of silently overwriting their change - important now that the
        # admin panel is used from multiple devices at once.
        expected_updated_at_str = data.get('expected_updated_at')
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /inventory)'
            }), 400
        try:
            expected_updated_at = datetime.fromisoformat(
                expected_updated_at_str.replace('Z', '+00:00')
            )
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)

        target_date_str = data.get('date')
        if target_date_str:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        # One UPDATE for both fields so a quantity+daily_limit change lands
        # atomically instead of as two separate commits that could leave
        # the row half-updated if the second write failed.
        result = Inventory.update_quantity(
            prize_id, event_id, target_date,
            remaining_quantity=quantity, daily_limit=daily_limit,
            expected_updated_at=expected_updated_at
        )
        if not result:
            current = Inventory.get_for_prize(prize_id, event_id, target_date)
            if not current:
                return jsonify({
                    'success': False,
                    'error': 'Inventory not found'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This inventory was changed by someone else - reload and try again',
                'current': current
            }), 409

        log_audit('update', 'inventory', prize_id, performed_by=_actor(),
                  new_value={'quantity': quantity, 'daily_limit': daily_limit})

        if daily_limit is not None:
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

        # Broadcast the date-aware wheel prizes (with the refreshed
        # remaining quantities) rather than Prize.get_all(), which doesn't
        # carry per-day inventory and left clients showing stale numbers
        # until they reloaded.
        prizes = SpinService.get_wheel_prizes(event_id, target_date)
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
        
        # Create the event, its theme, and its prizes in one transaction -
        # a failure partway through (e.g. a bad prize_id) used to leave a
        # half-configured event behind instead of nothing at all.
        def _create_event_with_prizes(session):
            result = session.execute(text("""
                INSERT INTO special_events (name, description, event_type, start_datetime, end_datetime)
                VALUES (:name, :description, :event_type, :start_dt, :end_dt)
                RETURNING id
            """), {
                'name': name, 'description': description, 'event_type': event_type,
                'start_dt': start_dt, 'end_dt': end_dt
            })
            new_event_id = result.fetchone()[0]

            if theme_config:
                session.execute(text("""
                    UPDATE special_events
                    SET theme_config = :theme_config, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :event_id
                """), {
                    'event_id': new_event_id,
                    'theme_config': json.dumps(theme_config),
                })

            for prize_id in prize_ids:
                session.execute(text("""
                    INSERT INTO special_event_prizes (special_event_id, prize_id, boost_enabled, weight_multiplier, quantity_override)
                    VALUES (:event_id, :prize_id, TRUE, 1.5, NULL)
                    ON CONFLICT (special_event_id, prize_id) DO NOTHING
                """), {'event_id': new_event_id, 'prize_id': prize_id})

            return new_event_id

        try:
            new_event_id = run_in_transaction(_create_event_with_prizes)
        except Exception as e:
            logger.error(f"Error creating special event (rolled back): {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to create special event - check prize_ids are valid'
            }), 400

        # Get full event with prizes
        full_event = SpecialEvent.get_by_id(new_event_id)

        log_audit('create', 'special_event', new_event_id, performed_by=_actor(),
                  new_value={'name': name, 'event_type': event_type, 'prize_ids': prize_ids})
        logger.info(f"Admin created special event: {name} (ID: {new_event_id})")

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
        
        # Handle datetime parsing - reject invalid values instead of
        # silently passing the raw string through to the database
        if 'start_datetime' in data:
            try:
                data['start_datetime'] = datetime.fromisoformat(
                    data['start_datetime'].replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                return jsonify({
                    'success': False,
                    'error': 'Invalid start_datetime format'
                }), 400

        if 'end_datetime' in data:
            try:
                data['end_datetime'] = datetime.fromisoformat(
                    data['end_datetime'].replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                return jsonify({
                    'success': False,
                    'error': 'Invalid end_datetime format'
                }), 400
        
        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}

        expected_updated_at_str = update_data.pop('expected_updated_at', None)
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /special-events)'
            }), 400
        try:
            expected_updated_at = expected_updated_at_str if isinstance(expected_updated_at_str, datetime) \
                else datetime.fromisoformat(expected_updated_at_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        result = SpecialEvent.update(event_id, expected_updated_at=expected_updated_at, **update_data)

        if not result:
            if not SpecialEvent.get_by_id(event_id):
                return jsonify({
                    'success': False,
                    'error': 'Special event not found'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This special event was changed by someone else - reload and try again'
            }), 409

        log_audit('update', 'special_event', event_id, performed_by=_actor(), new_value=update_data)

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
        
        log_audit('delete', 'special_event', event_id, performed_by=_actor(), old_value={'name': result.get('name')})
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
        log_audit('toggle', 'special_event', event_id, performed_by=_actor(), new_value={'is_active': is_active})
        logger.info(f"Admin {status} special event: {result.get('name')} (ID: {event_id})")
        
        return jsonify({
            'success': True,
            'event': result,
            'message': f'Special event "{result.get("name")}" {status}'
        })
    except Exception as e:
        logger.error(f"Error toggling special event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _update_event_theme(event_id, theme_config, data):
    """
    Shared by update_event_theme/reset_event_theme - both are really just
    a SpecialEvent.update() on the theme_config field, so they get the
    same optimistic-concurrency check every other field-edit route already
    has (this used to call a separate, unlocked SpecialEvent.update_theme_config()
    instead, which also had the same naive-datetime bug already fixed
    elsewhere in SpecialEvent.update()).
    """
    expected_updated_at_str = data.get('expected_updated_at')
    if not expected_updated_at_str:
        return None, (jsonify({
            'success': False,
            'error': 'expected_updated_at is required (send back the value from GET /special-events)'
        }), 400)
    try:
        expected_updated_at = datetime.fromisoformat(expected_updated_at_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None, (jsonify({
            'success': False,
            'error': 'Invalid expected_updated_at format'
        }), 400)

    result = SpecialEvent.update(event_id, expected_updated_at=expected_updated_at, theme_config=theme_config)

    if not result:
        if not SpecialEvent.get_by_id(event_id):
            return None, (jsonify({'success': False, 'error': 'Special event not found'}), 404)
        return None, (jsonify({
            'success': False,
            'error': 'This special event was changed by someone else - reload and try again'
        }), 409)

    return result, None


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

        result, error_response = _update_event_theme(event_id, theme_config, data)
        if error_response:
            return error_response

        log_audit('update', 'special_event', event_id, performed_by=_actor(), new_value={'theme_config': theme_config})
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
        data = request.get_json() or {}

        result, error_response = _update_event_theme(event_id, {}, data)
        if error_response:
            return error_response

        log_audit('reset_theme', 'special_event', event_id, performed_by=_actor())
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

        log_audit('create', 'template', template['id'], performed_by=_actor(),
                   new_value={'name': name, 'description': description, 'is_default': is_default})
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

        expected_updated_at_str = update_data.pop('expected_updated_at', None)
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /templates)'
            }), 400
        try:
            expected_updated_at = datetime.fromisoformat(
                expected_updated_at_str.replace('Z', '+00:00')
            )
        except (ValueError, AttributeError):
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        result = DailyPrizeTemplate.update(template_id, expected_updated_at=expected_updated_at, **update_data)

        if not result:
            if not DailyPrizeTemplate.get_by_id(template_id):
                return jsonify({
                    'success': False,
                    'error': 'Template not found'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This template was changed by someone else - reload and try again'
            }), 409

        log_audit('update', 'template', template_id, performed_by=_actor(), new_value=update_data)

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

        log_audit('delete', 'template', template_id, performed_by=_actor(), old_value={'name': result.get('name')})
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

        # Get all active prizes
        all_prizes = Prize.get_all(include_inactive=False)

        if not all_prizes:
            return jsonify({
                'success': False,
                'error': 'No active prizes found in database'
            }), 400

        # Clear + repopulate in one transaction, so a failure partway
        # through can't leave the template with some prizes removed and
        # only some of the new ones added.
        operations = []
        if clear_existing:
            operations.append((
                "DELETE FROM template_prizes WHERE template_id = :template_id",
                {'template_id': template_id}
            ))
        for prize in all_prizes:
            prize_id = prize.get('id') or prize.get('prize_id')
            operations.append((
                """
                INSERT INTO template_prizes (template_id, prize_id, quantity, daily_limit, is_enabled)
                VALUES (:template_id, :prize_id, :quantity, :daily_limit, :is_enabled)
                ON CONFLICT (template_id, prize_id)
                DO UPDATE SET quantity = :quantity, daily_limit = :daily_limit, is_enabled = :is_enabled
                RETURNING id
                """,
                {
                    'template_id': template_id,
                    'prize_id': prize_id,
                    'quantity': default_quantity,
                    'daily_limit': default_daily_limit,
                    'is_enabled': True
                }
            ))

        results = execute_transaction(operations)
        # Skip the DELETE's result (it returns no counted rows) when
        # tallying how many prizes were inserted/updated
        insert_results = results[1:] if clear_existing else results
        added_count = sum(1 for r in insert_results if r)

        log_audit('populate', 'template', template_id, performed_by=_actor(),
                   new_value={'added_count': added_count, 'clear_existing': clear_existing})
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

        # Optional: omitted when adding a brand-new prize to the template
        # (nothing to conflict with yet); required in spirit when editing
        # one already there, though enforcing that would need to know in
        # advance whether this call is an add or an edit - simplest to
        # accept it as optional and let the DB-level WHERE guard do the
        # real work when it's supplied.
        expected_updated_at = None
        expected_updated_at_str = data.get('expected_updated_at')
        if expected_updated_at_str:
            try:
                expected_updated_at = datetime.fromisoformat(expected_updated_at_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return jsonify({
                    'success': False,
                    'error': 'Invalid expected_updated_at format'
                }), 400

        if not prize_id:
            return jsonify({
                'success': False,
                'error': 'prize_id is required'
            }), 400

        result = DailyPrizeTemplate.add_prize(
            template_id, prize_id, quantity, daily_limit, is_enabled,
            expected_updated_at=expected_updated_at
        )

        if not result:
            if expected_updated_at is not None:
                return jsonify({
                    'success': False,
                    'error': 'This template prize was changed by someone else - reload and try again'
                }), 409
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

        expected_updated_at_str = update_data.pop('expected_updated_at', None)
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /templates/:id)'
            }), 400
        try:
            expected_updated_at = datetime.fromisoformat(expected_updated_at_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        result = DailyPrizeTemplate.update_prize(template_prize_id, expected_updated_at=expected_updated_at, **update_data)

        if not result:
            if not DailyPrizeTemplate.get_prize_by_id(template_prize_id):
                return jsonify({
                    'success': False,
                    'error': 'Template prize not found'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This template prize was changed by someone else - reload and try again'
            }), 409

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
            if start > end:
                return jsonify({
                    'success': False,
                    'error': 'start_date must not be after end_date'
                }), 400
            if (end - start).days > 366:
                return jsonify({
                    'success': False,
                    'error': 'Date range cannot exceed 366 days'
                }), 400
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

        # For an immediate (next-spin) guaranteed win, the prize must still
        # be winnable today - otherwise the win would sit pending and, once
        # triggered, fail to actually consume any prize (see consume_prize).
        # Scheduled-for-later wins skip this check since tomorrow's
        # inventory doesn't exist yet.
        if not scheduled_at_str:
            today_inventory = Inventory.get_for_prize(prize_id)
            if not today_inventory:
                return jsonify({
                    'success': False,
                    'error': 'No inventory configured for this prize today'
                }), 400
            if today_inventory['remaining_quantity'] <= 0:
                return jsonify({
                    'success': False,
                    'error': 'This prize has no remaining quantity today'
                }), 409
            wins_today = Transaction.get_wins_today_for_prize(prize_id)
            if wins_today >= today_inventory['daily_limit']:
                return jsonify({
                    'success': False,
                    'error': 'This prize has already reached its daily limit today'
                }), 409

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
        log_audit('create', 'guaranteed_win', win['id'], performed_by=_actor(),
                   new_value={'prize_id': prize_id, 'scheduled_at': scheduled_at_str, 'target_identifier': target_identifier})
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
        
        # Handle scheduled_at parsing - reject invalid values instead of
        # silently passing the raw string through to the database
        if 'scheduled_at' in data and data['scheduled_at']:
            try:
                data['scheduled_at'] = datetime.fromisoformat(
                    data['scheduled_at'].replace('Z', '+00:00')
                )
            except (ValueError, AttributeError):
                return jsonify({
                    'success': False,
                    'error': 'Invalid scheduled_at format'
                }), 400

        # Remove admin_password from update data
        update_data = {k: v for k, v in data.items() if k != 'admin_password'}

        expected_updated_at_str = update_data.pop('expected_updated_at', None)
        if not expected_updated_at_str:
            return jsonify({
                'success': False,
                'error': 'expected_updated_at is required (send back the value from GET /guaranteed-wins)'
            }), 400
        try:
            expected_updated_at = datetime.fromisoformat(
                expected_updated_at_str.replace('Z', '+00:00')
            )
        except (ValueError, AttributeError):
            return jsonify({
                'success': False,
                'error': 'Invalid expected_updated_at format'
            }), 400

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        result = GuaranteedWin.update(win_id, expected_updated_at=expected_updated_at, **update_data)

        if not result:
            existing = GuaranteedWin.get_by_id(win_id)
            if not existing:
                return jsonify({
                    'success': False,
                    'error': 'Guaranteed win not found'
                }), 404
            if existing['status'] != 'pending':
                return jsonify({
                    'success': False,
                    'error': 'Guaranteed win is no longer pending'
                }), 404
            return jsonify({
                'success': False,
                'error': 'This guaranteed win was changed by someone else - reload and try again'
            }), 409

        log_audit('update', 'guaranteed_win', win_id, performed_by=_actor(), new_value=update_data)

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

        log_audit('cancel', 'guaranteed_win', win_id, performed_by=_actor())
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
    """
    Manually and immediately fulfil a guaranteed win.
    Goes through the same atomic consume_prize() path a real spin uses,
    so it actually awards the prize (decrements inventory, records a
    transaction) instead of just flipping the win's status with nothing
    to show for it.
    """
    try:
        data = request.get_json() or {}
        triggered_by = data.get('triggered_by', 'Admin (Manual)')

        win = GuaranteedWin.get_by_id(win_id)
        if not win or win['status'] != 'pending':
            return jsonify({
                'success': False,
                'error': 'Guaranteed win not found or already processed'
            }), 404

        event_id = current_app.config.get('DEFAULT_EVENT_ID', 1)
        result = SpinService.execute_spin(
            win['prize_id'], triggered_by, event_id, date.today(), win_id
        )

        if not result['success']:
            return jsonify({
                'success': False,
                'error': result.get('error') or 'Prize could not be awarded (out of stock or daily limit reached today)'
            }), 409

        log_audit('trigger', 'guaranteed_win', win_id, performed_by=_actor(),
                   new_value={'transaction_id': result['transaction_id'], 'triggered_by': triggered_by})
        logger.info(f"Admin manually triggered guaranteed win (ID: {win_id})")

        return jsonify({
            'success': True,
            'transaction_id': result['transaction_id'],
            'prize': result['prize'],
            'message': 'Guaranteed win triggered and prize awarded'
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
        admin_user = _actor()

        # Delete + reset + audit record land in one transaction, so a
        # failure partway through can't delete win history without also
        # resetting inventory (or vice versa).
        def _reset(session):
            deleted = session.execute(text("""
                DELETE FROM transactions
                WHERE DATE(created_at) = :today AND transaction_type = 'win'
                RETURNING id
            """), {'today': today}).fetchall()

            reset_rows = session.execute(text("""
                UPDATE prize_inventory
                SET remaining_quantity = initial_quantity, updated_at = NOW()
                WHERE available_date = :today
                RETURNING prize_id, initial_quantity, remaining_quantity
            """), {'today': today}).fetchall()

            session.execute(text("""
                INSERT INTO audit_log (action, entity_type, entity_id, old_value, performed_by)
                VALUES ('reset_daily_wins', 'event', NULL, :old_value, :performed_by)
            """), {
                'old_value': json.dumps({
                    'date': today.isoformat(),
                    'transactions_deleted': len(deleted),
                    'inventory_records_reset': len(reset_rows)
                }),
                'performed_by': admin_user
            })

            return len(deleted), len(reset_rows)

        deleted_count, inventory_reset_count = run_in_transaction(_reset)

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
