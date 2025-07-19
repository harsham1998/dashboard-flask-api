from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from datetime import datetime
import pytz
import time
import requests
import base64
import re
import html
from email.utils import parsedate_to_datetime
from firebase_service import FirebaseService
from text_processor import TextProcessor
import threading
import schedule

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize services
firebase = FirebaseService()
text_processor = TextProcessor()

# Global scheduler statistics
scheduler_stats = {
    'last_run': None,
    'last_run_ist': None,
    'total_users_checked': 0,
    'total_emails_found': 0,
    'total_transactions_found': 0,
    'last_error': None,
    'run_count': 0
}

# Gmail OAuth Configuration
import os
GMAIL_CONFIG = {
    'client_id': os.environ.get('GMAIL_CLIENT_ID'),
    'client_secret': os.environ.get('GMAIL_CLIENT_SECRET'),
    'redirect_uri': 'https://dashboard-flask-api.onrender.com/oauth/gmail/callback',
    'scope': 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/userinfo.email'
}

@app.route('/')
def home():
    """Root endpoint with API information"""
    return jsonify({
        'status': 'Dashboard Flask API Server Running',
        'version': '1.0.0',
        'endpoints': {
            'GET /tasks': 'Get all tasks',
            'POST /tasks': 'Add new task',
            'GET /tasks/<date>': 'Get tasks for specific date',
            'GET /siri/add-task': 'Add task via Siri (text query param)',
            'GET /siri/addTransaction': 'Add transaction via Siri (message param)',
            'GET /transactions': 'Get recent transactions',
            'GET /test_api.html': 'API Testing Interface'
        },
        'time': datetime.now().isoformat()
    })

@app.route('/test_api.html')
def serve_test_api():
    """Serve the test API HTML interface"""
    try:
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_api_path = os.path.join(current_dir, 'test_api.html')
        
        with open(test_api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        from flask import Response
        return Response(content, mimetype='text/html')
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to load test API interface',
            'message': str(e)
        }), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'firebase_connection': 'active'
    })

@app.route('/debug/env')
def debug_env():
    """Debug endpoint to check environment variables"""
    return jsonify({
        'gmail_client_id': 'Set' if GMAIL_CONFIG['client_id'] else 'Missing',
        'gmail_client_secret': 'Set' if GMAIL_CONFIG['client_secret'] else 'Missing',
        'redirect_uri': GMAIL_CONFIG['redirect_uri'],
        'environment_variables': {
            'GMAIL_CLIENT_ID': 'Set' if os.environ.get('GMAIL_CLIENT_ID') else 'Missing',
            'GMAIL_CLIENT_SECRET': 'Set' if os.environ.get('GMAIL_CLIENT_SECRET') else 'Missing'
        }
    })

@app.route('/debug/scheduler')
def debug_scheduler():
    """Debug endpoint to check scheduler status with enhanced statistics"""
    global scheduler_stats
    
    # Calculate IST times
    ist_tz = pytz.timezone('Asia/Kolkata')
    current_time_ist = datetime.now(ist_tz)
    
    next_run_utc = schedule.next_run() if schedule.jobs else None
    next_run_ist = None
    if next_run_utc:
        next_run_ist = next_run_utc.replace(tzinfo=pytz.UTC).astimezone(ist_tz)
    
    return jsonify({
        'scheduler_running': True,
        'scheduled_jobs': [str(job) for job in schedule.jobs],
        'next_run_utc': str(next_run_utc) if next_run_utc else None,
        'next_run_ist': next_run_ist.strftime('%Y-%m-%d %H:%M:%S IST') if next_run_ist else None,
        'current_time_utc': datetime.now().isoformat(),
        'current_time_ist': current_time_ist.strftime('%Y-%m-%d %H:%M:%S IST'),
        'gmail_check_interval': '5 minutes',
        'last_run_stats': {
            'last_run_utc': scheduler_stats['last_run'],
            'last_run_ist': scheduler_stats['last_run_ist'],
            'users_checked': scheduler_stats['total_users_checked'],
            'emails_found': scheduler_stats['total_emails_found'],
            'transactions_found': scheduler_stats['total_transactions_found'],
            'run_count': scheduler_stats['run_count'],
            'last_error': scheduler_stats['last_error']
        },
        'time_until_next_run': str(next_run_utc - datetime.now()) if next_run_utc else None
    })

@app.route('/debug/trigger-scheduler')
def trigger_scheduler():
    """Manually trigger the Gmail scheduler for testing"""
    try:
        print("🔄 Manually triggering Gmail scheduler...")
        check_all_users_gmail()
        return jsonify({
            'success': True,
            'message': 'Scheduler triggered successfully',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/user/connections', methods=['POST'])
def get_user_connections():
    """Get user's email connections"""
    try:
        data = request.get_json()
        user_email = data.get('userEmail')
        
        if not user_email:
            return jsonify({'error': 'User email required'}), 400
        
        # Get user data from Firebase
        user_email_key = user_email.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
        user_data = firebase.get_user_data(user_email_key)
        
        if not user_data:
            return jsonify({
                'connections': {
                    'gmail': {'connected': False},
                    'outlook': {'connected': False}
                }
            })
        
        # Check Gmail connection
        gmail_connected = 'gmailTokens' in user_data and user_data['gmailTokens'].get('connected', False)
        gmail_info = {}
        if gmail_connected:
            gmail_info = {
                'connected': True,
                'email': user_data.get('email', user_email),
                'connectedAt': user_data['gmailTokens'].get('created_at'),
                'scope': user_data['gmailTokens'].get('scope', '')
            }
        else:
            gmail_info = {'connected': False}
        
        return jsonify({
            'connections': {
                'gmail': gmail_info,
                'outlook': {'connected': False}  # Not implemented yet
            }
        })
        
    except Exception as e:
        print(f"Get user connections error: {str(e)}")
        return jsonify({'error': 'Failed to get user connections'}), 500

# Task endpoints
@app.route('/tasks', methods=['GET'])
def get_tasks():
    """Get all tasks"""
    try:
        tasks = firebase.get_tasks()
        return jsonify({
            'success': True,
            'tasks': tasks
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/tasks/<date>')
def get_tasks_by_date(date):
    """Get tasks for specific date"""
    try:
        tasks = firebase.get_tasks(date)
        return jsonify({
            'success': True,
            'date': date,
            'tasks': tasks
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/tasks', methods=['POST'])
def add_task():
    """Add new task"""
    try:
        data = request.get_json()
        text = data.get('text')
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        assigned_to = data.get('assignedTo', 'Harsha (Me)')
        
        if not text:
            return jsonify({
                'success': False,
                'error': 'Task text is required'
            }), 400
        
        new_task = {
            'id': int(time.time() * 1000),  # Timestamp in milliseconds
            'text': text.strip(),
            'completed': False,
            'assignee': assigned_to,
            'status': 'programming',
            'note': '',
            'issues': [],
            'appreciation': [],
            'createdAt': datetime.now().isoformat()
        }
        
        success = firebase.add_task({**new_task, 'date': date})
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Task added successfully',
                'task': new_task,
                'date': date
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save task'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Siri endpoints
@app.route('/siri/add-task')
def siri_add_task():
    """Add task via Siri (supports GET with query param)"""
    try:
        task_text = request.args.get('text') or request.args.get('task')
        
        if not task_text:
            return jsonify({
                'success': False,
                'error': 'Task text is required. Use ?text=your_task'
            }), 400
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        new_task = {
            'id': int(time.time() * 1000),
            'text': task_text.strip(),
            'completed': False,
            'assignee': 'Harsha (Me)',
            'status': 'pending',
            'note': '',
            'issues': [],
            'appreciation': [],
            'createdAt': datetime.now().isoformat()
        }
        
        success = firebase.add_task({**new_task, 'date': today})
        
        if success:
            print(f"🎤 Siri task added: \"{task_text}\" for {today}")
            return jsonify({
                'success': True,
                'message': f'Task added via Siri: \"{task_text}\"',
                'task': new_task,
                'date': today
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save task'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/siri/addTransaction')
def siri_add_transaction():
    """Add transaction via Siri"""
    try:
        message = request.args.get('message')
        
        if not message:
            return jsonify({
                'success': False,
                'error': 'Message parameter is required'
            }), 400
        
        # Parse the transaction message
        transaction_data = text_processor.parse_transaction_message(message)
        
        if not transaction_data:
            return jsonify({
                'success': False,
                'message': 'Message does not contain transaction information',
                'ignored': True
            })
        
        # Create transaction object
        transaction = {
            'id': int(time.time() * 1000),
            **transaction_data,
            'timestamp': datetime.now().isoformat()
        }
        
        # Save to Firebase
        success = firebase.add_transaction(transaction)
        
        if success:
            print(f"💳 Transaction added: {transaction['type']} ₹{transaction['amount']} via {transaction['mode']}")
            return jsonify({
                'success': True,
                'message': 'Transaction added successfully',
                'transaction': transaction
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save transaction'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Transaction endpoints
@app.route('/transactions')
def get_transactions():
    """Get recent transactions"""
    try:
        limit = int(request.args.get('limit', 5))
        transactions = firebase.get_transactions(limit)
        
        return jsonify({
            'success': True,
            'transactions': transactions,
            'count': len(transactions)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Gmail OAuth Endpoints
@app.route('/oauth/gmail/callback', methods=['GET'])
def gmail_oauth_callback():
    """Handle OAuth callback from Google"""
    try:
        # Check if environment variables are set
        if not GMAIL_CONFIG['client_id'] or not GMAIL_CONFIG['client_secret']:
            return '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gmail Authentication</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                    .container { max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    .error { color: #e74c3c; font-size: 48px; margin-bottom: 20px; }
                    h1 { color: #333; margin-bottom: 10px; }
                    p { color: #666; margin-bottom: 10px; }
                    .debug { background: #f8f9fa; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; text-align: left; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">⚠️</div>
                    <h1>Configuration Error</h1>
                    <p>Gmail OAuth credentials not configured properly.</p>
                    <div class="debug">
                        <strong>Missing Environment Variables:</strong><br>
                        GMAIL_CLIENT_ID: ''' + ('Set' if GMAIL_CONFIG['client_id'] else 'Missing') + '''<br>
                        GMAIL_CLIENT_SECRET: ''' + ('Set' if GMAIL_CONFIG['client_secret'] else 'Missing') + '''<br><br>
                        <strong>Please set these environment variables on your deployment platform.</strong>
                    </div>
                </div>
            </body>
            </html>
            '''
        
        # Get authorization code and state from URL parameters
        code = request.args.get('code')
        error = request.args.get('error')
        state = request.args.get('state')  # This is the user's email
        
        if error:
            return '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gmail Authentication</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                    .container { max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    .error { color: #e74c3c; font-size: 48px; margin-bottom: 20px; }
                    h1 { color: #333; margin-bottom: 10px; }
                    p { color: #666; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">❌</div>
                    <h1>Authentication Failed</h1>
                    <p>Gmail authentication was cancelled or failed. You can close this window and try again.</p>
                </div>
            </body>
            </html>
            '''
        
        if not code:
            return '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gmail Authentication</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                    .container { max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    .error { color: #e74c3c; font-size: 48px; margin-bottom: 20px; }
                    h1 { color: #333; margin-bottom: 10px; }
                    p { color: #666; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">❌</div>
                    <h1>No Authorization Code</h1>
                    <p>No authorization code received. Please try again.</p>
                </div>
            </body>
            </html>
            '''
        
        # Exchange authorization code for tokens
        token_data = {
            'client_id': GMAIL_CONFIG['client_id'],
            'client_secret': GMAIL_CONFIG['client_secret'],
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': GMAIL_CONFIG['redirect_uri']
        }
        
        token_response = requests.post(
            'https://oauth2.googleapis.com/token',
            data=token_data
        )
        
        if not token_response.ok:
            # Log the error details for debugging
            error_details = f"Status: {token_response.status_code}, Response: {token_response.text}"
            print(f"Token exchange failed: {error_details}")
            print(f"Request data: {token_data}")
            
            return f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gmail Authentication</title>
                <style>
                    body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                    .container {{ max-width: 500px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                    .error {{ color: #e74c3c; font-size: 48px; margin-bottom: 20px; }}
                    h1 {{ color: #333; margin-bottom: 10px; }}
                    p {{ color: #666; margin-bottom: 10px; }}
                    .debug {{ background: #f8f9fa; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; text-align: left; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">❌</div>
                    <h1>Token Exchange Failed</h1>
                    <p>Failed to exchange authorization code for tokens.</p>
                    <div class="debug">
                        <strong>Debug Info:</strong><br>
                        Status: {token_response.status_code}<br>
                        Client ID: {GMAIL_CONFIG['client_id']}<br>
                        Client Secret: {'Set' if GMAIL_CONFIG['client_secret'] else 'Missing'}<br>
                        Redirect URI: {GMAIL_CONFIG['redirect_uri']}<br>
                        Error: {token_response.text}
                    </div>
                </div>
            </body>
            </html>
            '''
        
        tokens = token_response.json()
        
        if 'error' in tokens:
            return f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Gmail Authentication</title>
                <style>
                    body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                    .container {{ max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                    .error {{ color: #e74c3c; font-size: 48px; margin-bottom: 20px; }}
                    h1 {{ color: #333; margin-bottom: 10px; }}
                    p {{ color: #666; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">❌</div>
                    <h1>Authentication Error</h1>
                    <p>Error: {tokens['error']}. Please try again.</p>
                </div>
            </body>
            </html>
            '''
        
        # Store tokens directly in Firebase
        if state:  # state contains user email
            try:
                user_email_key = state.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
                
                # Get existing user data or create new user
                user_data = firebase.get_user_data(user_email_key)
                
                if not user_data:
                    # Create new user data
                    user_data = {
                        'email': state,
                        'name': state.split('@')[0].title(),
                        'createdAt': datetime.now().isoformat(),
                        'lastLogin': datetime.now().isoformat()
                    }
                else:
                    # Update last login
                    user_data['lastLogin'] = datetime.now().isoformat()
                
                # Add Gmail tokens to user data
                user_data['gmailTokens'] = {
                    'access_token': tokens['access_token'],
                    'refresh_token': tokens['refresh_token'],
                    'expires_in': tokens['expires_in'],
                    'token_type': tokens['token_type'],
                    'scope': tokens['scope'],
                    'created_at': datetime.now().isoformat(),
                    'connected': True
                }
                
                # Save back to Firebase using Firebase service
                success = firebase.update_user_data(user_email_key, user_data)
                
                if success:
                    print(f'Gmail tokens stored for user: {state}')
                else:
                    print(f'Failed to store Gmail tokens for user: {state}')
                
                # Return success page
                return '''
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Gmail Authentication</title>
                        <style>
                            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                            .container { max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                            .success { color: #27ae60; font-size: 48px; margin-bottom: 20px; }
                            h1 { color: #333; margin-bottom: 10px; }
                            p { color: #666; }
                        </style>
                        <script>
                            // Auto-close after 3 seconds
                            setTimeout(function() {
                                window.close();
                            }, 3000);
                        </script>
                    </head>
                    <body>
                        <div class="container">
                            <div class="success">✅</div>
                            <h1>Gmail Connected Successfully!</h1>
                            <p>Your Gmail account has been connected. This window will close automatically.</p>
                        </div>
                    </body>
                    </html>
                    '''
            except Exception as e:
                print(f'Error storing Gmail tokens: {str(e)}')
                return f'''
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Gmail Authentication</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                        .container {{ max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                        .error {{ color: #e74c3c; font-size: 48px; margin-bottom: 20px; }}
                        h1 {{ color: #333; margin-bottom: 10px; }}
                        p {{ color: #666; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="error">❌</div>
                        <h1>Storage Error</h1>
                        <p>Failed to store Gmail tokens: {str(e)}</p>
                    </div>
                </body>
                </html>
                '''
        
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Gmail Authentication</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }
                .container { max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                .error { color: #e74c3c; font-size: 48px; margin-bottom: 20px; }
                h1 { color: #333; margin-bottom: 10px; }
                p { color: #666; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error">❌</div>
                <h1>Missing User Information</h1>
                <p>No user email provided in the authentication request.</p>
            </div>
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"OAuth callback error: {str(e)}")
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Gmail Authentication</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f5f5f5; }}
                .container {{ max-width: 400px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .error {{ color: #e74c3c; font-size: 48px; margin-bottom: 20px; }}
                h1 {{ color: #333; margin-bottom: 10px; }}
                p {{ color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error">❌</div>
                <h1>Callback Error</h1>
                <p>An error occurred during the OAuth callback: {str(e)}</p>
            </div>
        </body>
        </html>
        '''

@app.route('/oauth/gmail/refresh', methods=['POST'])
def refresh_gmail_token():
    """Refresh Gmail access token"""
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')
        user_email = data.get('userEmail')
        
        if not refresh_token:
            return jsonify({'error': 'Refresh token required'}), 400
        
        # Refresh token with Google
        token_data = {
            'client_id': GMAIL_CONFIG['client_id'],
            'client_secret': GMAIL_CONFIG['client_secret'],
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(
            'https://oauth2.googleapis.com/token',
            data=token_data
        )
        
        if not response.ok:
            return jsonify({'error': 'Token refresh failed'}), 400
        
        tokens = response.json()
        
        if 'error' in tokens:
            return jsonify({'error': tokens['error']}), 400
        
        return jsonify({'tokens': tokens})
        
    except Exception as e:
        print(f"Token refresh error: {str(e)}")
        return jsonify({'error': 'Failed to refresh token'}), 500

@app.route('/gmail/refresh')
def refresh_gmail_token_get():
    """Refresh Gmail access token via GET with userEmail parameter"""
    try:
        user_email = request.args.get('userEmail')
        if not user_email:
            return jsonify({'error': 'User email required. Use ?userEmail=your@email.com'}), 400
        
        # Get user's current tokens from Firebase
        user_email_key = user_email.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
        user_data = firebase.get_user_data(user_email_key)
        
        if not user_data or 'gmailTokens' not in user_data:
            return jsonify({'error': 'No Gmail tokens found for this user'}), 400
        
        gmail_tokens = user_data['gmailTokens']
        refresh_token = gmail_tokens.get('refresh_token')
        
        if not refresh_token:
            return jsonify({'error': 'No refresh token found'}), 400
        
        print(f"Refreshing Gmail token for user: {user_email}")
        
        # Refresh token with Google
        token_data = {
            'client_id': GMAIL_CONFIG['client_id'],
            'client_secret': GMAIL_CONFIG['client_secret'],
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(
            'https://oauth2.googleapis.com/token',
            data=token_data
        )
        
        print(f"Google token refresh response: {response.status_code}")
        
        if not response.ok:
            return jsonify({
                'error': 'Token refresh failed',
                'status_code': response.status_code,
                'response': response.text
            }), 400
        
        new_tokens = response.json()
        
        if 'error' in new_tokens:
            return jsonify({'error': new_tokens['error']}), 400
        
        # Update tokens in Firebase
        gmail_tokens['access_token'] = new_tokens['access_token']
        gmail_tokens['token_type'] = new_tokens.get('token_type', 'Bearer')
        gmail_tokens['expires_in'] = new_tokens.get('expires_in', 3600)
        gmail_tokens['last_refreshed'] = datetime.now().isoformat()
        
        user_data['gmailTokens'] = gmail_tokens
        firebase.update_user_data(user_email_key, user_data)
        
        print(f"Updated tokens in Firebase for user: {user_email}")
        
        return jsonify({
            'success': True,
            'user_email': user_email,
            'new_access_token': new_tokens['access_token'],
            'expires_in': new_tokens.get('expires_in', 3600),
            'updated_in_firebase': True,
            'message': 'Token refreshed and updated in Firebase successfully'
        })
        
    except Exception as e:
        print(f"Token refresh error: {str(e)}")
        return jsonify({'error': f'Failed to refresh token: {str(e)}'}), 500

def get_gmail_emails_with_details(gmail_tokens, user_email, minutes=5):
    """Get all emails with details and identified transactions for a specific user"""
    try:
        access_token = gmail_tokens['access_token']
        
        # Build comprehensive search query for transaction-related emails, exclude promotions
        search_query_parts = [
            'transaction', 'payment', 'purchase', 'charge', 'debit', 'credit', 'receipt', 'invoice',
            'bank', 'upi', 'transfer', 'credited', 'debited', 'rs', 'inr', 'rupees',
            'hdfc', 'icici', 'sbi', 'axis', 'kotak', 'pnb', 'canara', 'union',
            'paytm', 'phonepe', 'googlepay', 'amazonpay', 'mobikwik', 'freecharge',
            'visa', 'mastercard', 'rupay',
            'alert', 'notification', 'statement', 'balance', 'withdraw', 'deposit'
        ]
        # Exclude category:promotions
        time_filter = f'newer_than:{minutes}m' if minutes <= 60 else f'newer_than:{max(1, int(minutes / 60))}h'
        search_query = f'({" OR ".join(search_query_parts)}) {time_filter} -category:promotions'
        
        print(f"Gmail search query: {search_query}")
        print(f"Searching for emails in last {minutes} minutes...")
        
        # Get emails from Gmail API (limit to 20 for 5min, can be tuned)
        email_list = search_gmail_emails(access_token, search_query, max_results=20)
        
        print(f"Found {len(email_list)} emails from Gmail API")
        
        # If no emails found with transaction terms, try a time-only search
        if not email_list:
            print(f"No emails found with transaction terms, trying time-only search for last {minutes} minutes...")
            time_only_query = time_filter
            email_list = search_gmail_emails(access_token, time_only_query, max_results=20)
            print(f"Found {len(email_list)} emails with time-only search")
            
        # Final fallback only if debugging is needed (remove transaction filtering)
        if not email_list and minutes > 60:  # Only for longer periods
            print("No emails found with time filter, trying broader time range for debugging...")
            fallback_query = f'newer_than:1d'  # Last day for debugging
            email_list = search_gmail_emails(access_token, fallback_query, max_results=5)
            print(f"Found {len(email_list)} emails with fallback search (debugging)")
        
        # IST timezone
        ist_tz = pytz.timezone('Asia/Kolkata')
        
        all_emails = []
        transactions = []
        
        print(f"Processing {len(email_list)} emails...")
        
        now_ist = datetime.now(ist_tz)
        for i, email_data in enumerate(email_list):
            print(f"Processing email {i+1}/{len(email_list)}: {email_data.get('id', 'unknown')}")
            email = get_gmail_email(access_token, email_data['id'])
            if email:
                print(f"Successfully retrieved email {i+1}")
                email_info = {
                    'id': email['id'],
                    'thread_id': email['threadId'],
                    'snippet': email.get('snippet', ''),
                    'payload': email.get('payload', {}),
                    'size_estimate': email.get('sizeEstimate', 0),
                    'history_id': email.get('historyId', ''),
                    'internal_date': email.get('internalDate', ''),
                    'label_ids': email.get('labelIds', [])
                }
                # Convert Gmail internal date to IST
                email_ist_dt = None
                if email_info['internal_date']:
                    try:
                        timestamp_ms = int(email_info['internal_date'])
                        timestamp_s = timestamp_ms / 1000
                        utc_dt = datetime.fromtimestamp(timestamp_s, tz=pytz.UTC)
                        ist_dt = utc_dt.astimezone(ist_tz)
                        email_info['ist_date'] = ist_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                        email_info['ist_timestamp'] = ist_dt.isoformat()
                        email_ist_dt = ist_dt
                    except:
                        email_info['ist_date'] = 'Unable to parse'
                        email_info['ist_timestamp'] = None
                # Filter by IST date
                if email_ist_dt:
                    delta_minutes = (now_ist - email_ist_dt).total_seconds() / 60.0
                    if delta_minutes > minutes or delta_minutes < 0:
                        print(f"Skipping email {i+1}: outside requested time window")
                        continue
                # Extract subject, sender, and body
                headers = email_info['payload'].get('headers', [])
                for header in headers:
                    name = header.get('name', '').lower()
                    value = header.get('value', '')
                    if name == 'subject':
                        email_info['subject'] = value
                    elif name == 'from':
                        email_info['from'] = value
                    elif name == 'to':
                        email_info['to'] = value
                    elif name == 'date':
                        email_info['date_header'] = value
                body = extract_email_body(email_info['payload'])
                email_info['body'] = body  # Always decoded
                transaction, transaction_log = extract_transaction_from_email(email)
                if transaction:
                    print(f"Email {i+1} has transaction: {transaction.get('amount', 'unknown')} {transaction.get('currency', 'unknown')}")
                    transaction_clean = {
                        'id': transaction.get('id'),
                        'amount': transaction.get('amount'),
                        'currency': transaction.get('currency'),
                        'date': transaction.get('date'),
                        'merchant': transaction.get('merchant'),
                        'type': transaction.get('type'),
                        'account': transaction.get('account'),
                        'category': transaction.get('category'),
                        'description': transaction.get('description'),
                        'source': transaction.get('source'),
                        'processed': transaction.get('processed'),
                        'verified': transaction.get('verified'),
                        'dashboard_user_email': user_email,
                        'gmail_source': user_email,
                        'email_id': email_info['id'],
                        'email_subject': email_info.get('subject', ''),
                        'email_from': email_info.get('from', ''),
                        'email_ist_date': email_info.get('ist_date', ''),
                        'body': body
                    }
                    transactions.append(transaction_clean)
                    email_info['has_transaction'] = True
                    email_info['transaction_data'] = transaction_clean
                    email_info['not_transaction_reason'] = None
                else:
                    print(f"Email {i+1} has no transaction data: {transaction_log}")
                    email_info['has_transaction'] = False
                    email_info['transaction_data'] = None
                    email_info['not_transaction_reason'] = transaction_log
                all_emails.append(email_info)
            else:
                print(f"Failed to retrieve email {i+1}")
        
        print(f"Final results: {len(all_emails)} emails processed, {len(transactions)} transactions found")
        
        return {
            'emails': all_emails,
            'transactions': transactions,
            'total_emails': len(all_emails),
            'total_transactions': len(transactions)
        }
        
    except Exception as e:
        print(f"Error getting Gmail emails with details for {user_email}: {str(e)}")
        return {
            'emails': [],
            'transactions': [],
            'total_emails': 0,
            'total_transactions': 0,
            'error': str(e)
        }

def decode_gmail_base64(encoded_data):
    """Properly decode Gmail Base64url encoded data or return if already decoded"""
    try:
        # Check if data is already decoded (contains HTML tags or readable text)
        if '<' in encoded_data and '>' in encoded_data:
            # Already decoded HTML, return as is
            return encoded_data
        
        # Check if it looks like plain text (no base64 characters)
        if not any(c in encoded_data for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_'):
            # Probably already decoded text
            return encoded_data
        
        # Step 1: Fix Base64url (Gmail uses - and _ instead of + and /)
        encoded_data = encoded_data.replace('-', '+').replace('_', '/')
        
        # Step 2: Fix padding (Gmail often omits =)
        padding = len(encoded_data) % 4
        if padding:
            encoded_data += '=' * (4 - padding)
        
        # Step 3: Decode
        decoded_bytes = base64.b64decode(encoded_data)
        decoded_text = decoded_bytes.decode('utf-8', errors='replace')
        
        return decoded_text
        
    except Exception as e:
        print(f"Error decoding Gmail Base64: {str(e)}")
        # Return original data if decoding fails
        return encoded_data

def extract_email_body(payload):
    """Extract email body from Gmail payload with proper Base64url decoding"""
    try:
        raw_body = ''
        if isinstance(payload, dict):
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        if 'data' in part.get('body', {}):
                            decoded_body = decode_gmail_base64(part['body']['data'])
                            raw_body += decoded_body
                    elif part.get('mimeType') == 'text/html':
                        if 'data' in part.get('body', {}):
                            decoded_html = decode_gmail_base64(part['body']['data'])
                            raw_body += decoded_html
                    elif 'parts' in part:
                        raw_body += extract_email_body(part)
            else:
                if payload.get('mimeType') == 'text/plain':
                    if 'data' in payload.get('body', {}):
                        raw_body = decode_gmail_base64(payload['body']['data'])
                elif payload.get('mimeType') == 'text/html':
                    if 'data' in payload.get('body', {}):
                        decoded_html = decode_gmail_base64(payload['body']['data'])
                        raw_body = decoded_html

        # Clean the raw body using your helper
        cleaned_body = clean_email_body(raw_body)
        return cleaned_body
    except Exception as e:
        print(f"Error extracting email body: {str(e)}")
        return ''

def find_user_by_gmail_account(gmail_account):
    """Find the actual user who owns this Gmail account by searching through Firebase users"""
    try:
        # Get all users from Firebase
        response = requests.get(f"{firebase.base_url}/users.json")
        if not response.ok:
            return None
        
        users = response.json()
        if not users:
            return None
        
        # Search through all users to find who has this Gmail account connected
        for user_key, user_data in users.items():
            if not user_data or 'gmailTokens' not in user_data:
                continue
            
            gmail_tokens = user_data['gmailTokens']
            if not gmail_tokens.get('connected'):
                continue
            
            # Check if this user has the Gmail account connected
            connected_email = gmail_tokens.get('email', '')
            if connected_email == gmail_account:
                # Return the actual user's email
                return user_data.get('email', user_key.replace('_', '.'))
        
        return None
        
    except Exception as e:
        print(f"Error finding user by Gmail account: {str(e)}")
        return None

def validate_and_refresh_token(user_email, user_data):
    """Validate access token and refresh if expired"""
    try:
        tokens = user_data['gmailTokens']
        access_token = tokens.get('access_token')
        
        if not access_token:
            return None, "No access token found"
        
        # Test if the token is valid by making a simple API call
        headers = {'Authorization': f'Bearer {access_token}'}
        test_response = requests.get(
            'https://gmail.googleapis.com/gmail/v1/users/me/profile',
            headers=headers
        )
        
        if test_response.status_code == 200:
            print(f"Access token is valid for {user_email}")
            return tokens, None
        elif test_response.status_code == 401:
            print(f"Access token expired for {user_email}, refreshing...")
            
            # Token is expired, refresh it
            refresh_token = tokens.get('refresh_token')
            if not refresh_token:
                return None, "No refresh token available"
            
            # Refresh the token
            token_data = {
                'client_id': GMAIL_CONFIG['client_id'],
                'client_secret': GMAIL_CONFIG['client_secret'],
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token'
            }
            
            refresh_response = requests.post(
                'https://oauth2.googleapis.com/token',
                data=token_data
            )
            
            if not refresh_response.ok:
                return None, f"Token refresh failed: {refresh_response.text}"
            
            new_tokens = refresh_response.json()
            
            if 'error' in new_tokens:
                return None, f"Token refresh error: {new_tokens['error']}"
            
            # Update tokens in the current data and Firebase
            tokens['access_token'] = new_tokens['access_token']
            tokens['token_type'] = new_tokens.get('token_type', 'Bearer')
            tokens['expires_in'] = new_tokens.get('expires_in', 3600)
            tokens['last_refreshed'] = datetime.now().isoformat()
            
            user_data['gmailTokens'] = tokens
            user_email_key = user_email.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
            firebase.update_user_data(user_email_key, user_data)
            
            print(f"Token refreshed successfully for {user_email}")
            return tokens, None
        else:
            return None, f"Token validation failed with status: {test_response.status_code}"
            
    except Exception as e:
        return None, f"Token validation error: {str(e)}"

@app.route('/gmail/check-now')
def check_gmail_now():
    """Manually check Gmail for transactions with dynamic time parameter - returns all emails and transactions"""
    try:
        user_email = request.args.get('userEmail')
        actual_user_email = request.args.get('actualUserEmail')  # The actual user who owns the dashboard
        minutes = int(request.args.get('minutes', 5))  # Default to 5 minutes
        
        if not user_email:
            return jsonify({'error': 'User email required. Use ?userEmail=your@email.com'}), 400
        
        if minutes < 1 or minutes > 1440:  # Max 24 hours
            return jsonify({'error': 'Minutes must be between 1 and 1440 (24 hours)'}), 400
        
        # Get user's Gmail tokens from Firebase
        user_email_key = user_email.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
        user_data = firebase.get_user_data(user_email_key)
        
        if not user_data or 'gmailTokens' not in user_data:
            return jsonify({'error': 'No Gmail tokens found'}), 400
        
        if not user_data['gmailTokens'].get('connected'):
            return jsonify({'error': 'Gmail not connected'}), 400
        
        # Validate and refresh token if needed
        tokens, error = validate_and_refresh_token(user_email, user_data)
        if error:
            return jsonify({'error': f'Token validation/refresh failed: {error}'}), 400
        
        # Find the actual user who owns this Gmail account
        if not actual_user_email:
            actual_user_email = find_user_by_gmail_account(user_email)
            if not actual_user_email:
                # Default to the Gmail account if we can't find the actual user
                actual_user_email = user_email
        
        storage_user_email = actual_user_email
        
        print(f"Manual Gmail check requested for Gmail: {user_email}, storing in: {storage_user_email} (last {minutes} minutes)")
        
        # Get all emails with details and transactions
        result = get_gmail_emails_with_details(tokens, user_email, minutes=minutes)
        
        # Store transactions in the correct user's individual JSON file
        stored_count = 0
        for transaction in result['transactions']:
            # Update transaction to reflect the actual user
            transaction['dashboard_user_email'] = storage_user_email
            transaction['gmail_source'] = user_email
            success = store_user_transaction_in_file(storage_user_email, transaction)
            if success:
                stored_count += 1
        
        # Update last check time
        ist_tz = pytz.timezone('Asia/Kolkata')
        current_time_ist = datetime.now(ist_tz)
        tokens['last_email_check'] = current_time_ist.isoformat()
        user_data['gmailTokens'] = tokens
        firebase.update_user_data(user_email_key, user_data)
        
        # Ensure transactions reflect the latest schema (removal/addition of fields)
        transactions_cleaned = []
        for txn in result['transactions']:
            cleaned_txn = {
                'id': txn.get('id'),
                'amount': txn.get('amount'),
                'currency': txn.get('currency'),
                'date': txn.get('date'),
                'merchant': txn.get('merchant'),
                'type': txn.get('type'),
                'reference_number': txn.get('reference_number'),
                'email_id': txn.get('email_id'),
                'email_subject': txn.get('email_subject'),
                'email_from': txn.get('email_from'),
                'email_ist_date': txn.get('email_ist_date'),
                'gmail_source': txn.get('gmail_source'),
                'dashboard_user_email': txn.get('dashboard_user_email'),
                'description': txn.get('description'),
                # Add any other required fields, remove unwanted ones
            }
            transactions_cleaned.append(cleaned_txn)

        return jsonify({
            'success': True,
            'gmail_account': user_email,
            'dashboard_user': storage_user_email,
            'time_period_minutes': minutes,
            'current_time_ist': current_time_ist.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'emails_found': result['total_emails'],
            'transactions_found': result['total_transactions'],
            'transactions_stored': stored_count,
            'gmail_messages': result['emails'],  # Show actual Gmail messages
            'transactions': transactions_cleaned,
            'message': f'Checked last {minutes} minutes of Gmail ({user_email}). Found {result["total_emails"]} emails with {result["total_transactions"]} transactions. Stored in {storage_user_email} file.',
            'error': result.get('error'),
            'user_mapping': {
                'gmail_account': user_email,
                'actual_user': storage_user_email,
                'mapping_method': 'auto-detected' if not request.args.get('actualUserEmail') else 'manual'
            },
            'token_info': {
                'access_token_validated': True,
                'token_refreshed': tokens.get('last_refreshed') is not None,
                'last_refreshed': tokens.get('last_refreshed')
            }
        })
        
    except Exception as e:
        print(f"Manual Gmail check error: {str(e)}")
        return jsonify({'error': f'Failed to check Gmail: {str(e)}'}), 500

@app.route('/gmail/transactions', methods=['POST'])
def get_gmail_transactions():
    """Get transactions from Gmail emails"""
    try:
        data = request.get_json()
        user_email = data.get('userEmail')
        last_check = data.get('lastCheck')
        
        if not user_email:
            return jsonify({'error': 'User email required'}), 400
        
        # Get user's Gmail tokens from Firebase
        user_email_key = user_email.replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')
        user_data = firebase.get_user_data(user_email_key)
        
        if not user_data or 'gmailTokens' not in user_data:
            return jsonify({'error': 'No Gmail tokens found'}), 400
        
        tokens = user_data['gmailTokens']
        
        # Search for transaction emails
        transactions = []
        
        # Build search query
        search_query = 'transaction OR payment OR purchase OR charge OR debit OR receipt OR invoice OR bank OR card'
        
        if last_check:
            # Only get emails since last check
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', '+00:00'))
                days_ago = (datetime.now() - last_check_date).days
                if days_ago > 0:
                    search_query += f' newer_than:{days_ago}d'
            except:
                pass  # If date parsing fails, get all recent emails
        
        # Get emails from Gmail API
        emails = search_gmail_emails(tokens['access_token'], search_query)
        
        for email_data in emails:
            # Get full email content
            email = get_gmail_email(tokens['access_token'], email_data['id'])
            
            if email:
                # Extract transaction data
                transaction = extract_transaction_from_email(email)
                if transaction:
                    transactions.append(transaction)
        
        return jsonify({'transactions': transactions})
        
    except Exception as e:
        print(f"Get transactions error: {str(e)}")
        return jsonify({'error': 'Failed to get transactions'}), 500

# Helper functions for Gmail API
def search_gmail_emails(access_token, query, max_results=50):
    """Search Gmail emails with enhanced debugging"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        params = {
            'q': query,
            'maxResults': max_results
        }
        
        print(f"Making Gmail API request with query: {query}")
        print(f"Max results: {max_results}")
        
        response = requests.get(
            'https://gmail.googleapis.com/gmail/v1/users/me/messages',
            headers=headers,
            params=params
        )
        
        print(f"Gmail API response status: {response.status_code}")
        
        if response.ok:
            data = response.json()
            messages = data.get('messages', [])
            print(f"Gmail API returned {len(messages)} messages")
            return messages
        else:
            print(f"Gmail search error: {response.status_code}")
            print(f"Response content: {response.text}")
            return []
            
    except Exception as e:
        print(f"Search emails error: {str(e)}")
        return []

def get_gmail_email(access_token, message_id):
    """Get full Gmail email content with enhanced debugging"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        print(f"Fetching email with ID: {message_id}")
        
        response = requests.get(
            f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}',
            headers=headers,
            params={'format': 'full'}
        )
        
        print(f"Gmail email API response status: {response.status_code}")
        
        if response.ok:
            email_data = response.json()
            print(f"Successfully retrieved email data, keys: {list(email_data.keys())}")
            return email_data
        else:
            print(f"Gmail get email error: {response.status_code}")
            print(f"Response content: {response.text}")
            return None
            
    except Exception as e:
        print(f"Get email error: {str(e)}")
        return None

def extract_transaction_from_email(email):
    """Extract transaction data from email"""
    try:
        payload = email.get('payload', {})
        headers = payload.get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        body = extract_email_body(payload)
        # Use your parsing function
        transaction = parse_transaction_email(body)
        transaction_log = None
        if transaction and transaction.get('amount'):
            # Build new transaction object as per requirements
            ist_tz = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist_tz)
            txn_obj = {
                'id': email.get('id'),
                'amount': transaction.get('amount'),
                'currency': transaction.get('currency', 'INR'),
                'merchant': transaction.get('merchant'),
                'type': transaction.get('credit_or_debit'),
                'reference_number': transaction.get('reference_number'),
                'email_id': email.get('id'),
                'email_subject': subject,
                'email_from': sender,
                'email_ist_date': now_ist.strftime('%Y-%m-%d %H:%M:%S IST'),
                'gmail_source': email.get('gmail_source'),
                'dashboard_user_email': email.get('dashboard_user_email'),
                'description': body
            }
            transaction_log = 'Transaction detected.'
            return txn_obj, transaction_log
        else:
            transaction_log = 'No transaction detected or amount missing.'
            return None, transaction_log
    except Exception as e:
        print(f"Extract transaction error: {str(e)}")
        return None, None
# Helper functions from user
def clean_email_body(raw_body):
    try:
        # Instead of decoding unicode, just replace common unicode escapes manually
        # Replace \u003C and \u003E with < and >
        safe_body = re.sub(r'\\u003[Cc]', '<', raw_body)
        safe_body = re.sub(r'\\u003[Ee]', '>', safe_body)
        # Replace other \uXXXX escapes with a placeholder
        safe_body = re.sub(r'\\u[0-9A-Fa-f]{4}', '', safe_body)

        # Unescape HTML entities
        unescaped = html.unescape(safe_body)

        # Remove tracking links like <https://...>
        unescaped = re.sub(r'<https?://[^>]+>', '', unescaped)

        # Remove script/style/head/meta/title tags and all HTML tags using regex
        unescaped = re.sub(r'<(script|style|head|meta|title)[^>]*>.*?</\1>', '', unescaped, flags=re.DOTALL|re.IGNORECASE)
        # Remove all HTML tags
        text = re.sub(r'<[^>]+>', '', unescaped)
        # Remove links
        text = re.sub(r'https?://\S+', '', text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    except Exception as e:
        return f"Error cleaning email: {str(e)}"

def parse_transaction_email(text):
    """
    Extracts structured transaction info from clean email body
    """
    try:
        text_lower = text.lower()

        # Transaction keywords for identification
        keywords = [
            "debited", "credited", "transaction", "payment of", "paid to", "purchased at",
            "withdrawn", "spent", "credited to your account", "upi reference", "imps", "neft",
            "rtgs", "pos", "transfer of", "card ending", "your account has been debited"
        ]

        # Only proceed if at least one keyword is present
        if not any(k in text_lower for k in keywords):
            return None

        result = {
            "amount": None,
            "merchant": None,
            "bank": None,
            "transaction_type": None,
            "credit_or_debit": None,
            "date": None,
            "reference_number": None,
            "card_info": None,
            "currency": "INR"
        }

        # Amount
        amt_match = re.search(r'(rs\.?|inr|₹)\s*([0-9,]+\.\d{1,2})', text_lower)
        if amt_match:
            result['amount'] = float(amt_match.group(2).replace(',', ''))

        # Credit or Debit
        if 'debited' in text_lower:
            result['credit_or_debit'] = 'debit'
        elif 'credited' in text_lower or 'received' in text_lower:
            result['credit_or_debit'] = 'credit'

        # Transaction Type
        if 'upi' in text_lower:
            result['transaction_type'] = 'upi'
        elif 'card' in text_lower:
            result['transaction_type'] = 'card'
        elif 'neft' in text_lower or 'imps' in text_lower:
            result['transaction_type'] = 'bank_transfer'

        # Merchant
        merchant_match = re.search(r'to\s+([a-z0-9@.\s&-]+?)\s+(?:on|for)', text_lower)
        if merchant_match:
            result['merchant'] = merchant_match.group(1).strip()

        # Bank
        banks = ['hdfc', 'icici', 'sbi', 'axis', 'kotak', 'pnb', 'canara', 'union', 'bob', 'yes bank']
        for bank in banks:
            if bank in text_lower:
                result['bank'] = bank.upper()
                break

        # Card Info
        card_match = re.search(r'card\s+(?:xx|ending\s+in)?\s*(\d{4})', text_lower)
        if card_match:
            result['card_info'] = f"XX{card_match.group(1)}"

        # Reference Number
        ref_match = re.search(r'reference\s+(?:number|no\.?)\s+is\s+([\w\d]+)', text_lower)
        if ref_match:
            result['reference_number'] = ref_match.group(1)

        # Date
        date_match = re.search(r'on\s+(\d{2}[-/]\d{2}[-/]\d{2,4})', text_lower)
        if date_match:
            raw_date = date_match.group(1)
            try:
                fmt = '%d-%m-%y' if len(raw_date.split('-')[-1]) == 2 else '%d-%m-%Y'
                result['date'] = datetime.strptime(raw_date, fmt).strftime('%Y-%m-%d')
            except:
                pass

        return result

    except Exception as e:
        return {"error": f"Parsing error: {str(e)}"}


def parse_transaction_data(subject, body, sender, date, return_log=False):
    """Parse transaction data from email content with robust Indian transaction detection"""

    text = f"{subject} {body}".lower()
    sender_lower = sender.lower() if sender else ""

    # Keywords for transaction identification
    bank_keywords = [
        "hdfc", "icici", "sbi", "axis", "kotak", "pnb", "canara", "union", "paytm", "phonepe", "googlepay", "amazonpay", "mobikwik", "freecharge", "bank", "card", "rupay", "mastercard", "visa"
    ]
    txn_keywords = [
        "transaction", "upi", "credit", "debit", "sent", "txn", "received", "transfer", "payment", "deposit", "withdraw", "statement", "alert", "balance", "refund", "purchase", "charged"
    ]

    # Check for bank keywords in sender
    sender_has_bank = any(word in sender_lower for word in bank_keywords)
    # Check for transaction keywords in subject or body
    subject_has_txn = any(word in subject.lower() for word in txn_keywords + bank_keywords)
    body_has_txn = any(word in body.lower() for word in txn_keywords + bank_keywords)

    # Enhanced amount patterns for Indian transactions (INR, Rs., etc.)
    amount_patterns = [
        r'rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'inr\s*([0-9,]+\.?\d{0,2})',
        r'₹\s*([0-9,]+\.?\d{0,2})',
        r'amount:?\s*rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'credited.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'debited.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'paid.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'charged.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'received.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'transfer.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'upi.*?rs[\.\s]*([0-9,]+\.?\d{0,2})',
        r'\$([0-9,]+\.?\d{0,2})',
        r'amount:?\s*\$?([0-9,]+\.?\d{0,2})',
        r'charged?\s*\$?([0-9,]+\.?\d{0,2})',
        r'paid?\s*\$?([0-9,]+\.?\d{0,2})'
    ]

    # ...existing code...

# Background email checking service
def check_all_users_gmail():
    """Check Gmail for all users and extract transactions - Enhanced version"""
    global scheduler_stats
    
    try:
        # Initialize IST timezone
        ist_tz = pytz.timezone('Asia/Kolkata')
        current_time_ist = datetime.now(ist_tz)
        
        print(f"Starting Gmail check for all users at {current_time_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")
        
        # Update scheduler stats
        scheduler_stats['last_run'] = datetime.now().isoformat()
        scheduler_stats['last_run_ist'] = current_time_ist.isoformat()
        scheduler_stats['run_count'] += 1
        scheduler_stats['last_error'] = None
        
        # Get all users from Firebase
        response = requests.get(f"{firebase.base_url}/users.json")
        if not response.ok:
            error_msg = f"Failed to get users from Firebase: {response.status_code}"
            print(error_msg)
            scheduler_stats['last_error'] = error_msg
            return
        
        users = response.json()
        if not users:
            print("No users found")
            scheduler_stats['total_users_checked'] = 0
            scheduler_stats['total_emails_found'] = 0
            scheduler_stats['total_transactions_found'] = 0
            return
        
        total_users_checked = 0
        total_emails_found = 0
        total_transactions_found = 0
        
        for user_key, user_data in users.items():
            if not user_data or 'gmailTokens' not in user_data:
                continue
            
            gmail_tokens = user_data['gmailTokens']
            if not gmail_tokens.get('connected') or not gmail_tokens.get('access_token'):
                continue
            
            user_email = user_data.get('email', '')
            total_users_checked += 1
            print(f"Checking Gmail for user: {user_email}")
            
            try:
                # Use enhanced email processing (last 5 minutes)
                result = get_gmail_emails_with_details(gmail_tokens, user_email, minutes=5)
                
                total_emails_found += result['total_emails']
                total_transactions_found += result['total_transactions']
                
                if result['transactions']:
                    print(f"Found {len(result['transactions'])} new transactions for {user_email}")
                    
                    # Store transactions in user's individual JSON file
                    for transaction in result['transactions']:
                        transaction['source'] = 'gmail_auto'  # Mark as automatic
                        success = store_user_transaction_in_file(user_email, transaction)
                        if not success:
                            print(f"Failed to store transaction for {user_email}")
                
                # Update last check time with IST
                gmail_tokens['last_email_check'] = current_time_ist.isoformat()
                user_data['gmailTokens'] = gmail_tokens
                
                # Save updated user data
                firebase.update_user_data(user_key, user_data)
                
            except Exception as e:
                error_msg = f"Error checking Gmail for user {user_email}: {str(e)}"
                print(error_msg)
                scheduler_stats['last_error'] = error_msg
                continue
        
        # Update final stats
        scheduler_stats['total_users_checked'] = total_users_checked
        scheduler_stats['total_emails_found'] = total_emails_found
        scheduler_stats['total_transactions_found'] = total_transactions_found
        
        print(f"Gmail check completed. Checked {total_users_checked} users, found {total_emails_found} emails, identified {total_transactions_found} transactions.")
        
    except Exception as e:
        error_msg = f"Error in check_all_users_gmail: {str(e)}"
        print(error_msg)
        scheduler_stats['last_error'] = error_msg

def get_gmail_transactions_for_user(gmail_tokens, user_email, last_check, minutes=5):
    """Get transactions from Gmail for a specific user"""
    try:
        access_token = gmail_tokens['access_token']
        
        # Build search query
        search_query = 'transaction OR payment OR purchase OR charge OR debit OR receipt OR invoice OR bank OR card'
        
        # Only get emails from last X minutes (default 5)
        if last_check:
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', '+00:00'))
                minutes_ago = max(1, int((datetime.now() - last_check_date).total_seconds() / 60))
                # Use hours if more than 60 minutes
                if minutes_ago > 60:
                    hours_ago = max(1, int(minutes_ago / 60))
                    search_query += f' newer_than:{hours_ago}h'
                else:
                    search_query += f' newer_than:{minutes_ago}m'
            except:
                search_query += f' newer_than:{minutes}m'  # Default to specified minutes
        else:
            search_query += f' newer_than:{minutes}m'  # Default to specified minutes
        
        print(f"Gmail search query: {search_query}")
        
        # Get emails from Gmail API
        emails = search_gmail_emails(access_token, search_query, max_results=20)
        
        transactions = []
        for email_data in emails:
            # Get full email content
            email = get_gmail_email(access_token, email_data['id'])
            
            if email:
                # Extract transaction data
                transaction = extract_transaction_from_email(email)
                if transaction:
                    # Add user information
                    transaction['user_email'] = user_email
                    transaction['source'] = 'gmail_auto'
                    transactions.append(transaction)
        
        return transactions
        
    except Exception as e:
        print(f"Error getting Gmail transactions for {user_email}: {str(e)}")
        return []

def store_user_transaction_in_file(user_email, transaction):
    """Store transaction in user's individual JSON file with duplicate checking"""
    try:
        # Create safe filename from email
        safe_email = user_email.replace('@', '_at_').replace('.', '_dot_')
        filename = f"{safe_email}.json"
        
        # Get existing transactions from user's file
        response = requests.get(f"{firebase.base_url}/{filename}")
        
        if response.ok:
            user_data = response.json() or {}
        else:
            user_data = {}
        
        # Initialize transactions array if not exists
        if 'transactions' not in user_data:
            user_data['transactions'] = []
        
        # Check for duplicate transactions
        transaction_id = transaction.get('id')
        existing_ids = [t.get('id') for t in user_data['transactions']]
        
        if transaction_id in existing_ids:
            print(f"Transaction {transaction_id} already exists for user {user_email}, skipping...")
            return False
        
        # Also check by amount, date, and merchant for similar transactions
        new_amount = transaction.get('amount')
        new_date = transaction.get('date', '')[:10]  # Just the date part
        new_merchant = transaction.get('merchant', '')
        
        for existing_tx in user_data['transactions']:
            existing_amount = existing_tx.get('amount')
            existing_date = existing_tx.get('date', '')[:10]
            existing_merchant = existing_tx.get('merchant', '')
            
            # Check if it's the same transaction (same amount, date, merchant)
            if (existing_amount == new_amount and 
                existing_date == new_date and 
                existing_merchant == new_merchant):
                print(f"Similar transaction found for user {user_email}, skipping duplicate...")
                return False
        
        # Add new transaction to beginning of list
        user_data['transactions'].insert(0, transaction)
        
        # Keep only last 50 transactions
        if len(user_data['transactions']) > 50:
            user_data['transactions'] = user_data['transactions'][:50]
        
        # Save back to Firebase
        response = requests.put(f"{firebase.base_url}/{filename}", json=user_data)
        
        print(f"Stored new transaction {transaction_id} for user {user_email}")
        return response.ok
        
    except Exception as e:
        print(f"Error storing transaction for user {user_email}: {str(e)}")
        return False

def store_user_transaction(user_key, transaction):
    """Store transaction in user's Firebase transactions (legacy method)"""
    try:
        # Get user's existing transactions
        response = requests.get(f"{firebase.base_url}/users/{user_key}/transactions.json")
        
        if response.ok:
            existing_transactions = response.json() or []
        else:
            existing_transactions = []
        
        # Add new transaction to beginning of list
        existing_transactions.insert(0, transaction)
        
        # Keep only last 50 transactions
        if len(existing_transactions) > 50:
            existing_transactions = existing_transactions[:50]
        
        # Save back to Firebase
        response = requests.put(f"{firebase.base_url}/users/{user_key}/transactions.json", json=existing_transactions)
        
        return response.ok
        
    except Exception as e:
        print(f"Error storing transaction for user {user_key}: {str(e)}")
        return False

def run_background_scheduler():
    """Run the background scheduler in a separate thread"""
    while True:
        schedule.run_pending()
        time.sleep(30)  # Check every 30 seconds

# Schedule Gmail checking every 5 minutes
schedule.every(5).minutes.do(check_all_users_gmail)

# Start background scheduler
def start_background_services():
    """Start background services"""
    print("Starting background services...")
    
    # Run initial check after 30 seconds
    threading.Timer(30.0, check_all_users_gmail).start()
    
    # Start scheduler thread
    scheduler_thread = threading.Thread(target=run_background_scheduler, daemon=True)
    scheduler_thread.start()
    
    print("Background services started")

# Auto-start background services when module is imported
def initialize_scheduler():
    """Initialize scheduler automatically when module is imported"""
    print("🔄 Initializing Gmail scheduler...")
    start_background_services()

# Initialize scheduler when module is imported
initialize_scheduler()

if __name__ == '__main__':
    # Background services are already started by initialize_scheduler()
    app.run(debug=True, host='0.0.0.0', port=5000)