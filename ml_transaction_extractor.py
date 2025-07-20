import re
import json
import base64
import hashlib
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import spacy
from spacy import displacy
import requests
import firebase_admin
from firebase_admin import credentials, db


class AESEncryption:
    """AES-256-GCM encryption utilities for transaction data"""
    
    @staticmethod
    def generate_key(password: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """Generate encryption key from password using PBKDF2"""
        if salt is None:
            salt = secrets.token_bytes(32)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = kdf.derive(password.encode())
        return key, salt
    
    @staticmethod
    def encrypt(data: str, key: bytes) -> str:
        """Encrypt data using AES-256-GCM"""
        iv = secrets.token_bytes(12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        ciphertext = encryptor.update(data.encode()) + encryptor.finalize()
        
        encrypted_data = {
            'iv': base64.b64encode(iv).decode(),
            'data': base64.b64encode(ciphertext).decode(),
            'tag': base64.b64encode(encryptor.tag).decode()
        }
        
        return base64.b64encode(json.dumps(encrypted_data).encode()).decode()
    
    @staticmethod
    def decrypt(encrypted_data: str, key: bytes) -> str:
        """Decrypt data using AES-256-GCM"""
        try:
            data = json.loads(base64.b64decode(encrypted_data).decode())
            
            iv = base64.b64decode(data['iv'])
            ciphertext = base64.b64decode(data['data'])
            tag = base64.b64decode(data['tag'])
            
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
            decryptor = cipher.decryptor()
            
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            return plaintext.decode()
        except Exception as e:
            raise Exception(f"Decryption failed: {str(e)}")


class MLTransactionExtractor:
    """Machine Learning based transaction extraction from email content"""
    
    def __init__(self):
        self.nlp = None
        self.load_model()
        self.encryption = AESEncryption()
        self.master_key = None
        
    def load_model(self):
        """Load spaCy NLP model"""
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("spaCy model not found. Installing...")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"])
            self.nlp = spacy.load("en_core_web_sm")
    
    def set_encryption_key(self, password: str, salt: bytes = None):
        """Set master encryption key"""
        self.master_key, salt = self.encryption.generate_key(password, salt)
        return salt
    
    def extract_transaction_details(self, email_body: str) -> Dict:
        """Extract transaction details using ML/NLP"""
        doc = self.nlp(email_body)
        
        transaction_data = {
            'amount': self._extract_amount(doc, email_body),
            'merchant': self._extract_merchant(doc, email_body),
            'date': self._extract_date(doc, email_body),
            'transaction_type': self._extract_transaction_type(doc, email_body),
            'card_last_four': self._extract_card_details(doc, email_body),
            'category': self._extract_category(doc, email_body),
            'description': self._extract_description(doc, email_body)
        }
        
        return transaction_data
    
    def _extract_amount(self, doc, text: str) -> Optional[float]:
        """Extract transaction amount using NLP and patterns"""
        # Currency patterns
        currency_patterns = [
            r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|dollars?)',
            r'Amount:?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'Total:?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'Charged:?\s*\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        ]
        
        amounts = []
        for pattern in currency_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    amount = float(match.replace(',', ''))
                    if 0.01 <= amount <= 100000:  # Reasonable transaction range
                        amounts.append(amount)
                except ValueError:
                    continue
        
        # Use NLP to find MONEY entities
        for ent in doc.ents:
            if ent.label_ == "MONEY":
                amount_text = re.sub(r'[^\d.,]', '', ent.text)
                try:
                    amount = float(amount_text.replace(',', ''))
                    if 0.01 <= amount <= 100000:
                        amounts.append(amount)
                except ValueError:
                    continue
        
        return max(amounts) if amounts else None
    
    def _extract_merchant(self, doc, text: str) -> Optional[str]:
        """Extract merchant name using NLP"""
        # Common merchant indicators
        merchant_patterns = [
            r'(?:at|from|to)\s+([A-Z][A-Za-z\s&\-\.]{2,30})',
            r'Merchant:?\s*([A-Za-z][A-Za-z\s&\-\.]{2,30})',
            r'Store:?\s*([A-Za-z][A-Za-z\s&\-\.]{2,30})',
            r'Purchase\s+(?:at|from)\s+([A-Za-z][A-Za-z\s&\-\.]{2,30})'
        ]
        
        merchants = []
        
        # Pattern-based extraction
        for pattern in merchant_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                merchant = match.strip()
                if len(merchant) > 2 and not merchant.lower() in ['the', 'and', 'for', 'with']:
                    merchants.append(merchant)
        
        # NLP-based extraction (ORG entities)
        for ent in doc.ents:
            if ent.label_ in ["ORG", "PERSON"] and len(ent.text) > 2:
                merchants.append(ent.text.strip())
        
        # Filter and rank merchants
        if merchants:
            # Remove duplicates and rank by frequency
            merchant_counts = {}
            for merchant in merchants:
                clean_merchant = re.sub(r'[^\w\s]', '', merchant).strip()
                if len(clean_merchant) > 2:
                    merchant_counts[clean_merchant] = merchant_counts.get(clean_merchant, 0) + 1
            
            if merchant_counts:
                return max(merchant_counts.items(), key=lambda x: x[1])[0]
        
        return None
    
    def _extract_date(self, doc, text: str) -> Optional[str]:
        """Extract transaction date using NLP"""
        # Date patterns
        date_patterns = [
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})'
        ]
        
        dates = []
        
        # Pattern-based extraction
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)
        
        # NLP-based extraction (DATE entities)
        for ent in doc.ents:
            if ent.label_ == "DATE":
                dates.append(ent.text)
        
        # Try to parse and normalize dates
        for date_str in dates:
            try:
                # Try various date formats
                for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y']:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        return parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
            except:
                continue
        
        return datetime.now().strftime('%Y-%m-%d')  # Default to today
    
    def _extract_transaction_type(self, doc, text: str) -> str:
        """Determine transaction type"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['purchase', 'bought', 'paid', 'charged', 'debit']):
            return 'purchase'
        elif any(word in text_lower for word in ['refund', 'return', 'credit', 'reversed']):
            return 'refund'
        elif any(word in text_lower for word in ['withdrawal', 'atm', 'cash']):
            return 'withdrawal'
        elif any(word in text_lower for word in ['transfer', 'sent', 'received']):
            return 'transfer'
        else:
            return 'purchase'  # Default
    
    def _extract_card_details(self, doc, text: str) -> Optional[str]:
        """Extract card last four digits"""
        card_patterns = [
            r'card\s+ending\s+in\s+(\d{4})',
            r'card\s+\*+(\d{4})',
            r'\*{4,}(\d{4})',
            r'xxxx\s*(\d{4})'
        ]
        
        for pattern in card_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_category(self, doc, text: str) -> str:
        """Categorize transaction based on merchant and context"""
        text_lower = text.lower()
        
        categories = {
            'food': ['restaurant', 'cafe', 'pizza', 'burger', 'food', 'dining', 'starbucks', 'mcdonald'],
            'shopping': ['amazon', 'walmart', 'target', 'store', 'shop', 'retail'],
            'gas': ['gas', 'fuel', 'shell', 'exxon', 'chevron', 'bp'],
            'groceries': ['grocery', 'supermarket', 'safeway', 'kroger', 'whole foods'],
            'entertainment': ['movie', 'netflix', 'spotify', 'theater', 'cinema'],
            'transportation': ['uber', 'lyft', 'taxi', 'bus', 'metro', 'parking'],
            'utilities': ['electric', 'water', 'internet', 'phone', 'utility'],
            'healthcare': ['hospital', 'doctor', 'pharmacy', 'medical', 'health']
        }
        
        for category, keywords in categories.items():
            if any(keyword in text_lower for keyword in keywords):
                return category
        
        return 'other'
    
    def _extract_description(self, doc, text: str) -> str:
        """Extract or generate transaction description"""
        # Look for description patterns
        desc_patterns = [
            r'Description:?\s*([^\n\r]+)',
            r'Reference:?\s*([^\n\r]+)',
            r'Details:?\s*([^\n\r]+)'
        ]
        
        for pattern in desc_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Generate description from extracted data
        return "Transaction processed"
    
    def encrypt_transaction(self, transaction_data: Dict) -> str:
        """Encrypt transaction data for storage"""
        if not self.master_key:
            raise Exception("Encryption key not set")
        
        json_data = json.dumps(transaction_data)
        return self.encryption.encrypt(json_data, self.master_key)
    
    def decrypt_transaction(self, encrypted_data: str) -> Dict:
        """Decrypt transaction data for display"""
        if not self.master_key:
            raise Exception("Encryption key not set")
        
        json_data = self.encryption.decrypt(encrypted_data, self.master_key)
        return json.loads(json_data)
    
    def process_email_and_store(self, email_body: str, user_id: str, firebase_url: str) -> Dict:
        """Complete pipeline: extract, encrypt, and store transaction"""
        try:
            # Extract transaction details using ML
            transaction_data = self.extract_transaction_details(email_body)
            
            # Add metadata
            transaction_data.update({
                'id': secrets.token_hex(16),
                'created_at': datetime.now().isoformat(),
                'processed_by': 'ml_extractor',
                'raw_confidence': self._calculate_confidence(transaction_data)
            })
            
            # Encrypt transaction data
            encrypted_data = self.encrypt_transaction(transaction_data)
            
            # Store in Firebase
            firebase_data = {
                'encrypted_transaction': encrypted_data,
                'timestamp': datetime.now().isoformat(),
                'transaction_id': transaction_data['id']
            }
            
            # Send to Firebase
            response = requests.post(
                f"{firebase_url}/{user_id}/transactions.json",
                json=firebase_data
            )
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'transaction_id': transaction_data['id'],
                    'message': 'Transaction processed and stored successfully'
                }
            else:
                return {
                    'success': False,
                    'error': f'Firebase storage failed: {response.text}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Processing failed: {str(e)}'
            }
    
    def _calculate_confidence(self, transaction_data: Dict) -> float:
        """Calculate confidence score for extracted data"""
        score = 0.0
        total_fields = 7
        
        if transaction_data.get('amount'):
            score += 1.0
        if transaction_data.get('merchant'):
            score += 1.0
        if transaction_data.get('date'):
            score += 1.0
        if transaction_data.get('transaction_type'):
            score += 1.0
        if transaction_data.get('card_last_four'):
            score += 1.0
        if transaction_data.get('category'):
            score += 1.0
        if transaction_data.get('description'):
            score += 1.0
        
        return score / total_fields


# Usage example and API functions
def initialize_ml_extractor(encryption_password: str = "dashboard_electron_2024") -> MLTransactionExtractor:
    """Initialize the ML transaction extractor with encryption"""
    extractor = MLTransactionExtractor()
    extractor.set_encryption_key(encryption_password)
    return extractor


def extract_and_store_transaction(email_body: str, user_id: str, firebase_url: str) -> Dict:
    """Main API function to extract and store transaction"""
    extractor = initialize_ml_extractor()
    return extractor.process_email_and_store(email_body, user_id, firebase_url)


def decrypt_transaction_for_ui(encrypted_data: str, encryption_password: str = "dashboard_electron_2024") -> Dict:
    """Decrypt transaction data for UI display"""
    extractor = initialize_ml_extractor(encryption_password)
    return extractor.decrypt_transaction(encrypted_data)


if __name__ == "__main__":
    # Test the ML extractor
    sample_email = """
    Dear Customer,
    
    Your card ending in 1234 was charged $45.67 at Starbucks Coffee on March 15, 2024.
    Transaction ID: TXN123456789
    Date: 03/15/2024 2:30 PM
    Amount: $45.67
    Merchant: Starbucks Store #1234
    
    Thank you for your business.
    """
    
    extractor = initialize_ml_extractor()
    result = extractor.extract_transaction_details(sample_email)
    print("Extracted transaction data:")
    print(json.dumps(result, indent=2))
    
    # Test encryption
    encrypted = extractor.encrypt_transaction(result)
    print(f"\nEncrypted data length: {len(encrypted)} characters")
    
    # Test decryption
    decrypted = extractor.decrypt_transaction(encrypted)
    print("\nDecrypted data matches:", result == decrypted)