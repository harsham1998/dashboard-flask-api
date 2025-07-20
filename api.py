import os
from flask import Flask, request, jsonify, redirect, send_file
from flask_cors import CORS
from datetime import datetime
import pytz
import time
import requests
import base64
from email.utils import parsedate_to_datetime
from firebase_service import FirebaseService
from text_processor import TextProcessor
from ml_email_classifier import classify_and_process_email, batch_process_emails, EmailClassifier
from ml_integration import ml_parse_transaction_email
import threading
import schedule


app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Gmail OAuth Configuration
GMAIL_CONFIG = {
    'client_id': os.environ.get('GMAIL_CLIENT_ID'),
    'client_secret': os.environ.get('GMAIL_CLIENT_SECRET'),
    'redirect_uri': 'https://dashboard-flask-api.onrender.com/oauth/gmail/callback',
    'scope': 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/userinfo.email'
}

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

def find_user_id_by_email(email):
    """Find user ID by email from users.json"""
    try:
        response = requests.get(f"{firebase.base_url}/users.json")
        if response.ok:
            users = response.json() or {}
            for user_id, user_data in users.items():
                if user_data.get('email') == email:
                    return user_id
        return None
    except Exception as e:
        print(f"Error finding user ID for email {email}: {str(e)}")
        return None

def store_user_transaction_in_file(user_email, transaction):
    """Store transaction in user's Firebase {user_id}.json with duplicate checking"""
    error_reason = None
    try:
        print(f"=== Starting transaction storage ===")
        print(f"User email: {user_email}")
        print(f"Transaction type: {type(transaction)}")
        print(f"Transaction data: {transaction}")
        
        # Validate inputs
        if not user_email:
            error_reason = "User email is required"
            print(f"Error: {error_reason}")
            return {"stored": False, "error": error_reason}
        
        if transaction is None:
            error_reason = "Transaction data is None"
            print(f"Error: {error_reason}")
            return {"stored": False, "error": error_reason}
        
        if not isinstance(transaction, dict):
            error_reason = f"Transaction must be a dict, got {type(transaction)}"
            print(f"Error: {error_reason}")
            return {"stored": False, "error": error_reason}
        
        # Find user_id from email by searching users
        user_id = find_user_id_by_email(user_email)
        if not user_id:
            error_reason = "User ID not found for email"
            print(f"User ID not found for email: {user_email}")
            return {"stored": False, "error": error_reason}

        transaction['user_id'] = user_id
        transactions_path = f"{firebase.base_url}/{user_id}/transactions.json"
        # Get current transactions
        response = requests.get(transactions_path)
        transactions = []
        print(f"Getting transactions from: {transactions_path}")
        print(f"Response status: {response.status_code}")
        if response.ok:
            try:
                data = response.json()
                print(f"Response data type: {type(data)}, data: {data}")
            except Exception as e:
                print(f"Error decoding Firebase response: {str(e)}")
                data = None
            # If the file is empty or not a list, start with an empty list
            if data is None:
                transactions = []
                print("No existing transactions found, starting with empty list")
            elif isinstance(data, list):
                # Filter out None values from the list
                transactions = [t for t in data if t is not None]
                print(f"Found {len(transactions)} existing transactions")
            else:
                transactions = []
                print(f"Unexpected data format: {type(data)}, starting with empty list")
        else:
            print(f"Failed to get transactions: {response.status_code}")
        # If response not ok, transactions remains empty

        # Check for duplicate transactions
        transaction_id = transaction.get('id')
        existing_ids = [t.get('id') for t in transactions if t is not None]
        if transaction_id in existing_ids:
            error_reason = "Duplicate transaction ID"
            print(f"Transaction {transaction_id} already exists for user {user_id}, skipping...")
            return {"stored": False, "error": error_reason}

        # Also check by amount, date, and merchant for similar transactions
        new_amount = transaction.get('amount')
        new_date_raw = transaction.get('date', '')
        new_date = new_date_raw[:10] if new_date_raw else ''
        new_merchant = transaction.get('merchant', '')
        print(f"New transaction details - Amount: {new_amount}, Date: {new_date}, Merchant: {new_merchant}")
        
        for existing_tx in transactions:
            if existing_tx is None:
                continue
            existing_amount = existing_tx.get('amount')
            existing_date_raw = existing_tx.get('date', '')
            existing_date = existing_date_raw[:10] if existing_date_raw else ''
            existing_merchant = existing_tx.get('merchant', '')
            if (existing_amount == new_amount and existing_date == new_date and existing_merchant == new_merchant):
                error_reason = "Duplicate by amount/date/merchant"
                print(f"Duplicate transaction detected for user {user_id}, skipping...")
                return {"stored": False, "error": error_reason}

        # Add new transaction to beginning of list
        transactions.insert(0, transaction)
        # Keep only last 50 transactions
        if len(transactions) > 50:
            transactions = transactions[:50]

        # Save back to Firebase
        response = requests.put(transactions_path, json=transactions)
        print(f"Attempting to store transaction {transaction_id} for user {user_id}")
        print(f"PUT response status: {response.status_code}")
        if response.ok:
            print(f"Successfully stored transaction {transaction_id} for user {user_id}")
            return {"stored": True, "firebase_path": transactions_path, "transaction_id": transaction_id}
        else:
            error_reason = f"Failed to save to Firebase: {response.status_code} - {response.text}"
            print(f"Failed to store transaction: {error_reason}")
            return {"stored": False, "error": error_reason, "firebase_path": transactions_path, "transaction_id": transaction_id}
    except Exception as e:
        import traceback
        error_reason = f"Exception: {str(e)}"
        full_traceback = traceback.format_exc()
        print(f"=== ERROR OCCURRED ===")
        print(f"Error storing transaction for user {user_email}: {str(e)}")
        print(f"Full traceback:")
        print(full_traceback)
        print(f"=== END ERROR ===")
        
        # Try to include firebase_path and transaction_id if they exist
        result = {"stored": False, "error": error_reason}
        if 'user_id' in locals():
            result["firebase_path"] = f"{firebase.base_url}/{user_id}/transactions.json"
        if 'transaction_id' in locals():
            result["transaction_id"] = transaction_id
        return result

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'firebase_connection': 'active'
    })

@app.route('/test-api.html')
def test_api_html():
    """Interactive API testing interface"""
    html_content = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard API Tester</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }
            .header h1 {
                font-size: 2.5rem;
                margin-bottom: 10px;
            }
            .header p {
                opacity: 0.9;
                font-size: 1.1rem;
            }
            .content {
                padding: 30px;
            }
            .api-section {
                margin-bottom: 40px;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                overflow: hidden;
            }
            .api-header {
                background: #f9fafb;
                padding: 20px;
                border-bottom: 1px solid #e5e7eb;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .api-header:hover {
                background: #f3f4f6;
            }
            .api-title {
                font-size: 1.3rem;
                font-weight: 600;
                color: #1f2937;
            }
            .api-method {
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
                text-transform: uppercase;
            }
            .method-get { background: #dcfce7; color: #16a34a; }
            .method-post { background: #dbeafe; color: #2563eb; }
            .method-put { background: #fef3c7; color: #d97706; }
            .method-delete { background: #fee2e2; color: #dc2626; }
            .api-body {
                padding: 20px;
                display: none;
            }
            .api-body.active {
                display: block;
            }
            .form-group {
                margin-bottom: 15px;
            }
            .form-group label {
                display: block;
                margin-bottom: 5px;
                font-weight: 500;
                color: #374151;
            }
            .form-group input, .form-group textarea, .form-group select {
                width: 100%;
                padding: 10px;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                font-size: 14px;
            }
            .form-group textarea {
                height: 100px;
                resize: vertical;
            }
            .btn {
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                color: white;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
                transition: all 0.2s;
            }
            .btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .response-section {
                margin-top: 20px;
                border-top: 1px solid #e5e7eb;
                padding-top: 20px;
            }
            .response-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .status-badge {
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
            }
            .status-200 { background: #dcfce7; color: #16a34a; }
            .status-400 { background: #fef3c7; color: #d97706; }
            .status-500 { background: #fee2e2; color: #dc2626; }
            .response-body {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 15px;
                white-space: pre-wrap;
                font-family: 'Courier New', monospace;
                font-size: 13px;
                max-height: 400px;
                overflow-y: auto;
            }
            .loading {
                display: none;
                color: #6b7280;
                font-style: italic;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Dashboard API Tester</h1>
                <p>Test all API endpoints with interactive forms and live responses</p>
            </div>
            <div class="content">
                
                <!-- Health Check -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('health')">
                        <div class="api-title">Health Check</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="health">
                        <p><strong>Endpoint:</strong> /health</p>
                        <p><strong>Description:</strong> Check if the API is running</p>
                        <button class="btn" onclick="testAPI('health', 'GET', '/health')">Test Health</button>
                        <div class="response-section" id="health-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="health-status"></span>
                            </div>
                            <div class="response-body" id="health-body"></div>
                        </div>
                        <div class="loading" id="health-loading">Testing...</div>
                    </div>
                </div>

                <!-- User Connections -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('connections')">
                        <div class="api-title">Get User Connections</div>
                        <span class="api-method method-post">POST</span>
                    </div>
                    <div class="api-body" id="connections">
                        <p><strong>Endpoint:</strong> /user/connections</p>
                        <p><strong>Description:</strong> Get user's email connections</p>
                        <div class="form-group">
                            <label>User Email:</label>
                            <input type="email" id="connections-email" placeholder="user@example.com" value="test@gmail.com">
                        </div>
                        <button class="btn" onclick="testUserConnections()">Test Connections</button>
                        <div class="response-section" id="connections-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="connections-status"></span>
                            </div>
                            <div class="response-body" id="connections-body"></div>
                        </div>
                        <div class="loading" id="connections-loading">Testing...</div>
                    </div>
                </div>

                <!-- Gmail Check -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('gmail-check')">
                        <div class="api-title">Check Gmail Now</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="gmail-check">
                        <p><strong>Endpoint:</strong> /gmail/check-now</p>
                        <p><strong>Description:</strong> Manually check Gmail for transactions</p>
                        <div class="form-group">
                            <label>User Email:</label>
                            <input type="email" id="gmail-email" placeholder="user@example.com" value="test@gmail.com">
                        </div>
                        <div class="form-group">
                            <label>Minutes to check (1-1440):</label>
                            <input type="number" id="gmail-minutes" placeholder="5" value="5" min="1" max="1440">
                        </div>
                        <button class="btn" onclick="testGmailCheck()">Check Gmail</button>
                        <div class="response-section" id="gmail-check-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="gmail-check-status"></span>
                            </div>
                            <div class="response-body" id="gmail-check-body"></div>
                        </div>
                        <div class="loading" id="gmail-check-loading">Testing...</div>
                    </div>
                </div>

                <!-- Refresh Gmail Token -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('refresh-token')">
                        <div class="api-title">Refresh Gmail Token</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="refresh-token">
                        <p><strong>Endpoint:</strong> /gmail/refresh</p>
                        <p><strong>Description:</strong> Refresh Gmail access token</p>
                        <div class="form-group">
                            <label>User Email:</label>
                            <input type="email" id="refresh-email" placeholder="user@example.com" value="test@gmail.com">
                        </div>
                        <button class="btn" onclick="testRefreshToken()">Refresh Token</button>
                        <div class="response-section" id="refresh-token-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="refresh-token-status"></span>
                            </div>
                            <div class="response-body" id="refresh-token-body"></div>
                        </div>
                        <div class="loading" id="refresh-token-loading">Testing...</div>
                    </div>
                </div>

                <!-- Add Task -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('add-task')">
                        <div class="api-title">Add Task</div>
                        <span class="api-method method-post">POST</span>
                    </div>
                    <div class="api-body" id="add-task">
                        <p><strong>Endpoint:</strong> /tasks</p>
                        <p><strong>Description:</strong> Add a new task</p>
                        <div class="form-group">
                            <label>Task Text:</label>
                            <input type="text" id="task-text" placeholder="Complete the dashboard feature" value="Test task from API tester">
                        </div>
                        <div class="form-group">
                            <label>Date (YYYY-MM-DD):</label>
                            <input type="date" id="task-date">
                        </div>
                        <div class="form-group">
                            <label>Assigned To:</label>
                            <input type="text" id="task-assignee" placeholder="Harsha (Me)" value="Harsha (Me)">
                        </div>
                        <button class="btn" onclick="testAddTask()">Add Task</button>
                        <div class="response-section" id="add-task-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="add-task-status"></span>
                            </div>
                            <div class="response-body" id="add-task-body"></div>
                        </div>
                        <div class="loading" id="add-task-loading">Testing...</div>
                    </div>
                </div>

                <!-- Get Tasks -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('get-tasks')">
                        <div class="api-title">Get All Tasks</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="get-tasks">
                        <p><strong>Endpoint:</strong> /tasks</p>
                        <p><strong>Description:</strong> Get all tasks</p>
                        <button class="btn" onclick="testAPI('get-tasks', 'GET', '/tasks')">Get Tasks</button>
                        <div class="response-section" id="get-tasks-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="get-tasks-status"></span>
                            </div>
                            <div class="response-body" id="get-tasks-body"></div>
                        </div>
                        <div class="loading" id="get-tasks-loading">Testing...</div>
                    </div>
                </div>

                <!-- Get Tasks by Date -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('get-tasks-date')">
                        <div class="api-title">Get Tasks by Date</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="get-tasks-date">
                        <p><strong>Endpoint:</strong> /tasks/{date}</p>
                        <p><strong>Description:</strong> Get tasks for a specific date</p>
                        <div class="form-group">
                            <label>Date (YYYY-MM-DD):</label>
                            <input type="date" id="tasks-date">
                        </div>
                        <button class="btn" onclick="testTasksByDate()">Get Tasks by Date</button>
                        <div class="response-section" id="get-tasks-date-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="get-tasks-date-status"></span>
                            </div>
                            <div class="response-body" id="get-tasks-date-body"></div>
                        </div>
                        <div class="loading" id="get-tasks-date-loading">Testing...</div>
                    </div>
                </div>

                <!-- Add Transaction via Siri -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('siri-transaction')">
                        <div class="api-title">Add Transaction (Siri)</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="siri-transaction">
                        <p><strong>Endpoint:</strong> /siri/addTransaction</p>
                        <p><strong>Description:</strong> Add transaction via Siri message</p>
                        <div class="form-group">
                            <label>Transaction Message:</label>
                            <textarea id="transaction-message" placeholder="Your account has been debited Rs. 1500 for payment to Amazon">Your account has been debited Rs. 150 for payment to Swiggy via UPI</textarea>
                        </div>
                        <button class="btn" onclick="testSiriTransaction()">Add Transaction</button>
                        <div class="response-section" id="siri-transaction-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="siri-transaction-status"></span>
                            </div>
                            <div class="response-body" id="siri-transaction-body"></div>
                        </div>
                        <div class="loading" id="siri-transaction-loading">Testing...</div>
                    </div>
                </div>

                <!-- Get Transactions -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('get-transactions')">
                        <div class="api-title">Get Recent Transactions</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="get-transactions">
                        <p><strong>Endpoint:</strong> /transactions</p>
                        <p><strong>Description:</strong> Get recent transactions</p>
                        <div class="form-group">
                            <label>Limit:</label>
                            <input type="number" id="transactions-limit" placeholder="5" value="5" min="1" max="50">
                        </div>
                        <button class="btn" onclick="testGetTransactions()">Get Transactions</button>
                        <div class="response-section" id="get-transactions-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="get-transactions-status"></span>
                            </div>
                            <div class="response-body" id="get-transactions-body"></div>
                        </div>
                        <div class="loading" id="get-transactions-loading">Testing...</div>
                    </div>
                </div>

                <!-- Scheduler Debug -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('scheduler-debug')">
                        <div class="api-title">Scheduler Status</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="scheduler-debug">
                        <p><strong>Endpoint:</strong> /debug/scheduler</p>
                        <p><strong>Description:</strong> Check scheduler status and statistics</p>
                        <button class="btn" onclick="testAPI('scheduler-debug', 'GET', '/debug/scheduler')">Check Scheduler</button>
                        <div class="response-section" id="scheduler-debug-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="scheduler-debug-status"></span>
                            </div>
                            <div class="response-body" id="scheduler-debug-body"></div>
                        </div>
                        <div class="loading" id="scheduler-debug-loading">Testing...</div>
                    </div>
                </div>

                <!-- Trigger Scheduler -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('trigger-scheduler')">
                        <div class="api-title">Trigger Scheduler</div>
                        <span class="api-method method-get">GET</span>
                    </div>
                    <div class="api-body" id="trigger-scheduler">
                        <p><strong>Endpoint:</strong> /debug/trigger-scheduler</p>
                        <p><strong>Description:</strong> Manually trigger the Gmail scheduler</p>
                        <button class="btn" onclick="testAPI('trigger-scheduler', 'GET', '/debug/trigger-scheduler')">Trigger Scheduler</button>
                        <div class="response-section" id="trigger-scheduler-response" style="display:none;">
                            <div class="response-header">
                                <h4>Response:</h4>
                                <span class="status-badge" id="trigger-scheduler-status"></span>
                            </div>
                            <div class="response-body" id="trigger-scheduler-body"></div>
                        </div>
                        <div class="loading" id="trigger-scheduler-loading">Testing...</div>
                    </div>
                </div>

                <!-- ML Transaction Extraction Test -->
                <div class="api-section">
                    <div class="api-header" onclick="toggleSection('ml-extract')">
                        <div class="api-title">🤖 ML Transaction Extraction</div>
                        <span class="api-method method-post">POST</span>
                    </div>
                    <div class="api-body" id="ml-extract">
                        <p><strong>Endpoint:</strong> /ml/extract</p>
                        <p><strong>Description:</strong> Extract transaction details using Machine Learning</p>
                        
                        <div style="margin: 10px 0;">
                            <label for="ml-email-body"><strong>Email/Transaction Text:</strong></label>
                            <textarea id="ml-email-body" rows="4" style="width: 100%; margin-top: 5px; padding: 8px; border: 1px solid #ddd; border-radius: 4px;" placeholder="Your card ending in 1234 was charged $45.67 at Starbucks Coffee on March 15, 2024...">Your card ending in 1234 was charged $45.67 at Starbucks Coffee on March 15, 2024. Transaction ID: TXN123456789</textarea>
                        </div>
                        
                        <div style="margin: 10px 0;">
                            <button class="btn" onclick="testMLExtraction()">🧠 Extract with ML</button>
                            <button class="btn" onclick="loadSampleStarbucks()" style="background: #6c757d; margin-left: 10px;">Starbucks Sample</button>
                            <button class="btn" onclick="loadSampleUPI()" style="background: #6c757d; margin-left: 5px;">UPI Sample</button>
                            <button class="btn" onclick="loadSampleGas()" style="background: #6c757d; margin-left: 5px;">Gas Sample</button>
                        </div>
                        
                        <div class="response-section" id="ml-extract-response" style="display:none;">
                            <div class="response-header">
                                <h4>ML Extraction Result:</h4>
                                <span class="status-badge" id="ml-extract-status"></span>
                            </div>
                            <div class="response-body" id="ml-extract-body"></div>
                            <div id="ml-confidence-display" style="margin-top: 10px; padding: 8px; background: #f8f9fa; border-radius: 4px; font-size: 14px;">
                                ML Confidence: Will show after extraction
                            </div>
                        </div>
                        <div class="loading" id="ml-extract-loading">Extracting...</div>
                    </div>
                </div>

            </div>
        </div>

        <script>
            // Set default date to today
            document.addEventListener('DOMContentLoaded', function() {
                const today = new Date().toISOString().split('T')[0];
                document.getElementById('task-date').value = today;
                document.getElementById('tasks-date').value = today;
            });

            function toggleSection(sectionId) {
                const section = document.getElementById(sectionId);
                section.classList.toggle('active');
            }

            async function testAPI(testId, method, endpoint, data = null) {
                const loadingEl = document.getElementById(testId + '-loading');
                const responseEl = document.getElementById(testId + '-response');
                const statusEl = document.getElementById(testId + '-status');
                const bodyEl = document.getElementById(testId + '-body');

                // Show loading
                loadingEl.style.display = 'block';
                responseEl.style.display = 'none';

                try {
                    const options = {
                        method: method,
                        headers: {
                            'Content-Type': 'application/json',
                        }
                    };

                    if (data) {
                        options.body = JSON.stringify(data);
                    }

                    const response = await fetch(endpoint, options);
                    const responseData = await response.text();

                    // Update UI
                    loadingEl.style.display = 'none';
                    responseEl.style.display = 'block';
                    
                    statusEl.textContent = response.status + ' ' + response.statusText;
                    statusEl.className = 'status-badge status-' + Math.floor(response.status / 100) + '00';
                    
                    try {
                        const jsonData = JSON.parse(responseData);
                        bodyEl.textContent = JSON.stringify(jsonData, null, 2);
                    } catch {
                        bodyEl.textContent = responseData;
                    }

                } catch (error) {
                    loadingEl.style.display = 'none';
                    responseEl.style.display = 'block';
                    statusEl.textContent = 'Error';
                    statusEl.className = 'status-badge status-500';
                    bodyEl.textContent = 'Error: ' + error.message;
                }
            }

            async function testUserConnections() {
                const email = document.getElementById('connections-email').value;
                await testAPI('connections', 'POST', '/user/connections', { userEmail: email });
            }

            async function testGmailCheck() {
                const email = document.getElementById('gmail-email').value;
                const minutes = document.getElementById('gmail-minutes').value;
                const url = `/gmail/check-now?userEmail=${encodeURIComponent(email)}&minutes=${minutes}`;
                await testAPI('gmail-check', 'GET', url);
            }

            async function testRefreshToken() {
                const email = document.getElementById('refresh-email').value;
                const url = `/gmail/refresh?userEmail=${encodeURIComponent(email)}`;
                await testAPI('refresh-token', 'GET', url);
            }

            async function testAddTask() {
                const text = document.getElementById('task-text').value;
                const date = document.getElementById('task-date').value;
                const assignedTo = document.getElementById('task-assignee').value;
                
                const data = {
                    text: text,
                    date: date,
                    assignedTo: assignedTo
                };
                
                await testAPI('add-task', 'POST', '/tasks', data);
            }

            async function testTasksByDate() {
                const date = document.getElementById('tasks-date').value;
                await testAPI('get-tasks-date', 'GET', `/tasks/${date}`);
            }

            async function testSiriTransaction() {
                const message = document.getElementById('transaction-message').value;
                const url = `/siri/addTransaction?message=${encodeURIComponent(message)}`;
                await testAPI('siri-transaction', 'GET', url);
            }

            async function testGetTransactions() {
                const limit = document.getElementById('transactions-limit').value;
                const url = `/transactions?limit=${limit}`;
                await testAPI('get-transactions', 'GET', url);
            }

            // ML Testing Functions
            async function testMLExtraction() {
                const emailBody = document.getElementById('ml-email-body').value;
                
                if (!emailBody.trim()) {
                    alert('Please enter some transaction text to extract');
                    return;
                }

                const loadingEl = document.getElementById('ml-extract-loading');
                const responseEl = document.getElementById('ml-extract-response');
                const statusEl = document.getElementById('ml-extract-status');
                const bodyEl = document.getElementById('ml-extract-body');
                const confidenceEl = document.getElementById('ml-confidence-display');

                loadingEl.style.display = 'block';
                responseEl.style.display = 'none';

                try {
                    const response = await fetch('/ml/extract', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            email_body: emailBody
                        })
                    });

                    const data = await response.json();
                    
                    loadingEl.style.display = 'none';
                    responseEl.style.display = 'block';
                    
                    statusEl.textContent = response.ok ? 'SUCCESS' : 'ERROR';
                    statusEl.className = 'status-badge ' + (response.ok ? 'status-success' : 'status-error');
                    
                    bodyEl.textContent = JSON.stringify(data, null, 2);

                    // Update confidence display
                    if (data.extracted_data && data.extracted_data.raw_confidence !== undefined) {
                        const confidence = (data.extracted_data.raw_confidence * 100).toFixed(1);
                        const amount = data.extracted_data.amount || 'N/A';
                        const merchant = data.extracted_data.merchant || 'N/A';
                        confidenceEl.textContent = `ML Confidence: ${confidence}% | Amount: $${amount} | Merchant: ${merchant}`;
                    } else {
                        confidenceEl.textContent = 'ML Confidence: No data extracted';
                    }

                } catch (error) {
                    loadingEl.style.display = 'none';
                    responseEl.style.display = 'block';
                    statusEl.textContent = 'ERROR';
                    statusEl.className = 'status-badge status-error';
                    bodyEl.textContent = 'Request failed: ' + error.message;
                    confidenceEl.textContent = 'ML Confidence: Error occurred';
                }
            }

            function loadSampleStarbucks() {
                document.getElementById('ml-email-body').value = 
                    "Your card ending in 1234 was charged $45.67 at Starbucks Coffee on March 15, 2024. Transaction ID: TXN123456789. Date: 03/15/2024 2:30 PM. Thank you for your business.";
            }

            function loadSampleUPI() {
                document.getElementById('ml-email-body').value = 
                    "UPI transaction successful! Rs.1500.00 sent to John Doe from your HDFC Bank account ending in 9012. UPI ID: 9010853978@ybl. Transaction ID: 425692851472. Date: 20-Jul-24 14:30.";
            }

            function loadSampleGas() {
                document.getElementById('ml-email-body').value = 
                    "Transaction alert: $67.89 charged at Shell Gas Station #1234 on 03/20/2024 at 2:30 PM. Card ending in 5678. Available balance: $1,234.56.";
            }
        </script>
    </body>
    </html>
    '''
    return html_content

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
        
        # Find user ID and get user data from Firebase
        user_id = find_user_id_by_email(user_email)
        if not user_id:
            return jsonify({
                'connections': {
                    'gmail': {'connected': False},
                    'outlook': {'connected': False}
                }
            })
        
        user_data = firebase.get_user_data(user_id)
        
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
                # Find user ID by email
                user_id = find_user_id_by_email(state)
                if not user_id:
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
                                <h1>User Not Found</h1>
                                <p>No user account found for this email. Please sign up first.</p>
                            </div>
                        </body>
                        </html>
                        '''
                
                # Get existing user data
                user_data = firebase.get_user_data(user_id)
                
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
                success = firebase.update_user_data(user_id, user_data)
                
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
        user_id = find_user_id_by_email(user_email)
        if not user_id:
            return jsonify({'error': 'User not found'}), 400
        user_data = firebase.get_user_data(user_id)
        
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
        firebase.update_user_data(user_id, user_data)
        
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
    """Get all emails with ML-powered classification and transaction extraction"""
    try:
        access_token = gmail_tokens['access_token']
        
        # Simple time-based search - let ML classifier handle identification
        time_filter = f'newer_than:{minutes}m' if minutes <= 60 else f'newer_than:{max(1, int(minutes / 60))}h'
        search_query = f'{time_filter} -category:promotions'
        
        print(f"Gmail search query: {search_query}")
        print(f"Searching for emails in last {minutes} minutes...")
        
        # Get emails from Gmail API
        email_list = search_gmail_emails(access_token, search_query, max_results=20)
        print(f"Found {len(email_list)} emails from Gmail API")
        
        # If no emails found, try broader search
        if not email_list and minutes > 60:
            fallback_query = f'newer_than:1d'
            email_list = search_gmail_emails(access_token, fallback_query, max_results=10)
            print(f"Found {len(email_list)} emails with fallback search")
        
        if not email_list:
            return {
                'emails': [],
                'transactions': [],
                'total_emails': 0,
                'total_transactions': 0
            }
        
        # Get full email details
        full_emails = []
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist_tz)
        
        for i, email_data in enumerate(email_list):
            print(f"Retrieving email {i+1}/{len(email_list)}: {email_data.get('id', 'unknown')}")
            email = get_gmail_email(access_token, email_data['id'])
            if email:
                # Time filtering
                if email.get('internalDate'):
                    try:
                        timestamp_ms = int(email['internalDate'])
                        timestamp_s = timestamp_ms / 1000
                        utc_dt = datetime.fromtimestamp(timestamp_s, tz=pytz.UTC)
                        ist_dt = utc_dt.astimezone(ist_tz)
                        delta_minutes = (now_ist - ist_dt).total_seconds() / 60.0
                        if delta_minutes > minutes or delta_minutes < 0:
                            print(f"Skipping email {i+1}: outside requested time window")
                            continue
                    except:
                        pass
                
                full_emails.append(email)
                print(f"Added email {i+1} for ML processing")
        
        print(f"Processing {len(full_emails)} emails through ML classifier...")
        
        # Process emails through ML classifier
        transactions = batch_process_emails(full_emails)
        
        print(f"ML processing complete: {len(transactions)} transactions found")
        
        # Prepare email summaries for response with cleaned bodies
        processed_emails = []
        classifier = EmailClassifier()
        
        for email in full_emails:
            headers = email.get('payload', {}).get('headers', [])
            
            # Get cleaned email body using the same process as ML classification
            cleaned_body = classifier.decode_email_body(email.get('payload', {}))
            
            email_summary = {
                'id': email.get('id'),
                'subject': next((h['value'] for h in headers if h['name'] == 'Subject'), ''),
                'from': next((h['value'] for h in headers if h['name'] == 'From'), ''),
                'body': cleaned_body,  # Return cleaned body instead of snippet
                'has_transaction': any(t['transaction_identifier_id'] == email.get('id') for t in transactions)
            }
            processed_emails.append(email_summary)
        
        return {
            'emails': processed_emails,
            'transactions': transactions,
            'total_emails': len(processed_emails),
            'total_transactions': len(transactions)
        }
        
    except Exception as e:
        print(f"Error in ML email processing for {user_email}: {str(e)}")
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
            # Get user's current tokens from Firebase
            user_id = find_user_id_by_email(user_email)
            if not user_id:
                return jsonify({'error': 'User not found'}), 400
            firebase.update_user_data(user_id, user_data)
            
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
        user_id = find_user_id_by_email(user_email)
        if not user_id:
            return jsonify({'error': 'User not found'}), 400
        user_data = firebase.get_user_data(user_id)
        
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
        storage_results = []
        stored_count = 0
        for transaction in result['transactions']:
            transaction['dashboard_user_email'] = storage_user_email
            transaction['gmail_source'] = user_email
            store_result = store_user_transaction_in_file(storage_user_email, transaction)
            transaction_id = transaction.get('id')
            user_id = find_user_id_by_email(storage_user_email)
            firebase_path = f"{firebase.base_url}/{user_id}/transactions.json" if user_id else None
            if store_result.get('stored'):
                stored_count += 1
                storage_results.append({
                    "transaction_id": transaction_id,
                    "stored": True,
                    "firebase_path": firebase_path
                })
            else:
                storage_results.append({
                    "transaction_id": transaction_id,
                    "stored": False,
                    "error": store_result.get('error'),
                    "firebase_path": firebase_path
                })
        
        # Update last check time
        ist_tz = pytz.timezone('Asia/Kolkata')
        current_time_ist = datetime.now(ist_tz)
        tokens['last_email_check'] = current_time_ist.isoformat()
        user_data['gmailTokens'] = tokens
        firebase.update_user_data(user_id, user_data)
        
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
                'email_subject': txn.get('email_subject'),
                'email_ist_date': txn.get('email_ist_date'),
                'gmail_source': txn.get('gmail_source'),
                'dashboard_user_email': txn.get('dashboard_user_email'),
                'description': txn.get('description'),
                'from_account': txn.get('from_account'),
                'to_account': txn.get('to_account'),
                'account_number': txn.get('account_number'),
                'credit_or_debit': txn.get('credit_or_debit'),
                'mode': txn.get('mode'),
                'category': txn.get('category'),
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
            'storage_results': storage_results,
            'gmail_messages': result['emails'],
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
        user_id = find_user_id_by_email(user_email)
        if not user_id:
            return jsonify({'error': 'User not found'}), 400
        user_data = firebase.get_user_data(user_id)
        
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
                # Extract transaction data using new ML classifier
                transaction = classify_and_process_email(email)
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

def check_all_users_gmail():
    """Check Gmail for all users using ML classification"""
    try:
        print("🔄 Checking Gmail for all users...")
        
        # Get all users from Firebase
        response = requests.get(f"{firebase.base_url}/users.json")
        if not response.ok:
            print(f"Failed to fetch users: {response.status_code}")
            return
        
        users = response.json() or {}
        processed_count = 0
        
        for user_key, user_data in users.items():
            try:
                # Check if user has Gmail credentials
                if 'gmail_credentials' in user_data:
                    print(f"Processing Gmail for user: {user_key}")
                    
                    # Get recent emails using existing function
                    transactions = get_gmail_transactions(user_key)
                    
                    if transactions:
                        processed_count += len(transactions)
                        print(f"Processed {len(transactions)} transactions for user {user_key}")
                    
            except Exception as e:
                print(f"Error processing user {user_key}: {str(e)}")
                continue
        
        print(f"✅ Gmail check completed. Processed {processed_count} transactions total.")
        
    except Exception as e:
        print(f"Error in check_all_users_gmail: {str(e)}")

# Schedule Gmail checking every 5 minutes
schedule.every(5).minutes.do(check_all_users_gmail)

# ML Testing Endpoint
@app.route('/ml/extract', methods=['POST'])
def ml_extract_endpoint():
    """Extract transaction details using ML for testing"""
    try:
        data = request.get_json()
        if not data or 'email_body' not in data:
            return jsonify({'error': 'email_body required in JSON payload'}), 400
        
        email_body = data['email_body'].strip()
        if not email_body:
            return jsonify({'error': 'email_body cannot be empty'}), 400
        
        # Use the same ML function as the main API
        extracted_data = ml_parse_transaction_email(email_body)
        
        if extracted_data:
            # Calculate basic confidence score for display
            confidence_score = 0.0
            total_fields = 7
            if extracted_data.get('amount'): confidence_score += 1.0
            if extracted_data.get('merchant'): confidence_score += 1.0
            if extracted_data.get('date'): confidence_score += 1.0
            if extracted_data.get('credit_or_debit'): confidence_score += 1.0
            if extracted_data.get('card_last_four'): confidence_score += 1.0
            if extracted_data.get('category'): confidence_score += 1.0
            if extracted_data.get('description'): confidence_score += 1.0
            
            extracted_data['raw_confidence'] = confidence_score / total_fields
            
            response = {
                'success': True,
                'email_body_length': len(email_body),
                'extracted_data': extracted_data,
                'ml_system': 'spacy_nlp_integration'
            }
        else:
            response = {
                'success': False,
                'message': 'No transaction detected in the provided text',
                'email_body_length': len(email_body)
            }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500

@app.route('/ml/classify_email', methods=['POST'])
def ml_classify_email():
    """New ML Email Classifier - Classifies entire Gmail email and extracts transaction data"""
    try:
        data = request.get_json()
        if not data or 'email' not in data:
            return jsonify({'error': 'email object required in JSON payload'}), 400
        
        email = data['email']
        
        # Process email through new ML classifier
        result = classify_and_process_email(email)
        
        if result:
            response = {
                'success': True,
                'classification': 'transaction',
                'transaction_data': result,
                'ml_system': 'email_classifier_v2'
            }
        else:
            # Classify but don't process (non-transaction email)
            from ml_email_classifier import EmailClassifier
            classifier = EmailClassifier()
            email_data = classifier.process_email(email)
            
            response = {
                'success': True,
                'classification': email_data.get('category', 'other'),
                'email_metadata': {
                    'subject': email_data.get('subject'),
                    'from': email_data.get('from'),
                    'category': email_data.get('category')
                },
                'transaction_data': None,
                'ml_system': 'email_classifier_v2'
            }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500

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