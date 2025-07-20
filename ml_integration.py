import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ml_transaction_extractor import MLTransactionExtractor, initialize_ml_extractor
import json
from datetime import datetime
try:
    import pytz
except ImportError:
    pytz = None
try:
    import requests
except ImportError:
    requests = None

# Global ML extractor instance
ml_extractor = None

def initialize_ml_system():
    """Initialize the ML transaction extraction system"""
    global ml_extractor
    if ml_extractor is None:
        ml_extractor = initialize_ml_extractor()
    return ml_extractor

def ml_parse_transaction_email(text):
    """ML-powered replacement for parse_transaction_email function"""
    try:
        extractor = initialize_ml_system()
        transaction_data = extractor.extract_transaction_details(text)
        
        # Convert ML output to match original API format
        result = {
            'amount': transaction_data.get('amount'),
            'currency': 'INR',  # Default currency
            'merchant': transaction_data.get('merchant'),
            'credit_or_debit': transaction_data.get('transaction_type', 'debit'),
            'reference_number': None,  # Not extracted by ML yet
            'date': transaction_data.get('date'),
            'card_last_four': transaction_data.get('card_last_four'),
            'category': transaction_data.get('category'),
            'description': transaction_data.get('description'),
            'confidence': transaction_data.get('raw_confidence', 0.0)
        }
        
        return result
        
    except Exception as e:
        print(f"ML parsing error: {str(e)}")
        return None

def ml_extract_transaction_from_email(email):
    """ML-powered replacement for extract_transaction_from_email function"""
    try:
        payload = email.get('payload', {})
        headers = payload.get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        
        # Extract email body (assuming this function exists in the original API)
        from api import extract_email_body
        body = extract_email_body(payload)
        
        # Use ML-powered parsing
        transaction = ml_parse_transaction_email(f"{subject} {body}")
        
        if transaction and transaction.get('amount'):
            # Build transaction object with ML-extracted data
            if pytz:
                ist_tz = pytz.timezone('Asia/Kolkata')
                now_ist = datetime.now(ist_tz)
            else:
                now_ist = datetime.now()
            
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
                'email_ist_date': now_ist.strftime('%Y-%m-%d %H:%M:%S') + (' IST' if pytz else ''),
                'category': transaction.get('category'),
                'description': transaction.get('description'),
                'card_last_four': transaction.get('card_last_four'),
                'ml_confidence': transaction.get('confidence', 0.0),
                'processed_by': 'ml_extractor'
            }
            
            return txn_obj
            
    except Exception as e:
        print(f"ML extraction error: {str(e)}")
        return None

def ml_store_encrypted_transaction(user_id, transaction_data, firebase_url):
    """Store transaction with AES-256 encryption"""
    try:
        extractor = initialize_ml_system()
        
        # Encrypt the transaction data
        encrypted_data = extractor.encrypt_transaction(transaction_data)
        
        # Prepare Firebase payload
        firebase_data = {
            'encrypted_transaction': encrypted_data,
            'timestamp': datetime.now().isoformat(),
            'transaction_id': transaction_data.get('id'),
            'email_id': transaction_data.get('email_id'),
            'amount_preview': f"₹{transaction_data.get('amount', 0):.2f}",  # Unencrypted preview
            'merchant_preview': transaction_data.get('merchant', 'Unknown')[:20],  # Truncated preview
            'processed_by': 'ml_extractor'
        }
        
        # Store in Firebase
        response = requests.post(
            f"{firebase_url}/{user_id}/transactions.json",
            json=firebase_data
        )
        
        if response.status_code == 200:
            return {
                'success': True,
                'transaction_id': transaction_data.get('id'),
                'firebase_key': response.json().get('name'),
                'encrypted': True
            }
        else:
            return {
                'success': False,
                'error': f'Firebase storage failed: {response.text}'
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Encryption/storage failed: {str(e)}'
        }

def ml_decrypt_transactions_for_ui(user_id, firebase_url):
    """Fetch and decrypt transactions for UI display"""
    try:
        extractor = initialize_ml_system()
        
        # Fetch encrypted transactions from Firebase
        response = requests.get(f"{firebase_url}/{user_id}/transactions.json")
        
        if response.status_code != 200:
            return []
        
        encrypted_transactions = response.json()
        if not encrypted_transactions:
            return []
        
        decrypted_transactions = []
        
        for firebase_key, transaction_data in encrypted_transactions.items():
            try:
                if 'encrypted_transaction' in transaction_data:
                    # Decrypt the transaction
                    decrypted = extractor.decrypt_transaction(
                        transaction_data['encrypted_transaction']
                    )
                    
                    # Add Firebase metadata
                    decrypted['firebase_key'] = firebase_key
                    decrypted['encrypted'] = True
                    decrypted['timestamp'] = transaction_data.get('timestamp')
                    
                    decrypted_transactions.append(decrypted)
                else:
                    # Handle unencrypted legacy data
                    transaction_data['encrypted'] = False
                    transaction_data['firebase_key'] = firebase_key
                    decrypted_transactions.append(transaction_data)
                    
            except Exception as decrypt_error:
                print(f"Failed to decrypt transaction {firebase_key}: {decrypt_error}")
                # Add error placeholder
                decrypted_transactions.append({
                    'firebase_key': firebase_key,
                    'error': 'Decryption failed',
                    'encrypted': True,
                    'amount_preview': transaction_data.get('amount_preview', 'N/A'),
                    'merchant_preview': transaction_data.get('merchant_preview', 'N/A')
                })
        
        # Sort by timestamp (newest first)
        decrypted_transactions.sort(
            key=lambda x: x.get('timestamp', ''), 
            reverse=True
        )
        
        return decrypted_transactions
        
    except Exception as e:
        print(f"Failed to fetch/decrypt transactions: {str(e)}")
        return []

def ml_process_email_pipeline(email, user_id, firebase_url):
    """Complete ML pipeline: extract, encrypt, and store"""
    try:
        # Extract transaction using ML
        transaction = ml_extract_transaction_from_email(email)
        
        if not transaction:
            return {
                'success': False,
                'reason': 'No transaction detected by ML'
            }
        
        # Store with encryption
        storage_result = ml_store_encrypted_transaction(
            user_id, transaction, firebase_url
        )
        
        if storage_result['success']:
            return {
                'success': True,
                'transaction': transaction,
                'storage': storage_result,
                'ml_confidence': transaction.get('ml_confidence', 0.0)
            }
        else:
            return {
                'success': False,
                'error': storage_result['error']
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'ML pipeline failed: {str(e)}'
        }

# API endpoint functions for integration
def get_ml_transaction_stats():
    """Get ML system statistics"""
    return {
        'ml_system_active': ml_extractor is not None,
        'encryption_enabled': True,
        'model_loaded': ml_extractor.nlp is not None if ml_extractor else False,
        'version': '1.0.0'
    }

# Export functions for easy replacement in main API
__all__ = [
    'ml_parse_transaction_email',
    'ml_extract_transaction_from_email', 
    'ml_store_encrypted_transaction',
    'ml_decrypt_transactions_for_ui',
    'ml_process_email_pipeline',
    'get_ml_transaction_stats',
    'initialize_ml_system'
]