#!/usr/bin/env python3

"""
ML Email Classifier - Identifies and processes different types of emails
Supports: Transaction emails, Credit card statements, Amazon orders, etc.
"""

import re
import base64
import html
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import spacy
from email.utils import parsedate_tz, mktime_tz

class EmailClassifier:
    """ML-powered email classifier and processor"""
    
    def __init__(self):
        self.nlp = None
        self.load_model()
        
        # Financial institution patterns
        self.financial_patterns = [
            # Banks
            r'hdfc\s*bank', r'axis\s*bank', r'icici\s*bank', r'sbi\s*bank', 
            r'kotak\s*bank', r'yes\s*bank', r'pnb\s*bank', r'canara\s*bank',
            r'bank\s*of\s*baroda', r'union\s*bank', r'indian\s*bank',
            
            # Payment gateways
            r'razorpay', r'paytm', r'phonepe', r'googlepay', r'amazon\s*pay',
            r'paypal', r'stripe', r'cashfree', r'instamojo',
            
            # Credit card companies
            r'visa', r'mastercard', r'american\s*express', r'rupay',
            
            # Financial services
            r'mutual\s*fund', r'zerodha', r'groww', r'upstox', r'angel\s*broking'
        ]
        
        # Transaction keywords
        self.transaction_keywords = [
            # Transaction types
            r'debited', r'credited', r'payment', r'transaction', r'charged',
            r'refund', r'withdrawal', r'deposit', r'transfer', r'purchase',
            
            # Currency and amounts
            r'rs\.?\s*\d+', r'inr\s*\d+', r'₹\s*\d+', r'\$\s*\d+',
            
            # Payment methods
            r'upi', r'neft', r'imps', r'rtgs', r'credit\s*card', r'debit\s*card',
            
            # Transaction references
            r'reference\s*number', r'transaction\s*id', r'receipt\s*number',
            r'order\s*id', r'payment\s*id'
        ]
    
    def load_model(self):
        """Load spaCy NLP model"""
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("spaCy model not found. Installing...")
            import subprocess
            subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"])
            self.nlp = spacy.load("en_core_web_sm")
    
    def decode_email_body(self, payload: Dict) -> str:
        """Extract and decode email body from Gmail API payload"""
        body = ""
        
        try:
            # Handle multipart emails
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        if 'data' in part.get('body', {}):
                            encoded_body = part['body']['data']
                            if encoded_body:  # Check if data exists
                                decoded_body = base64.urlsafe_b64decode(encoded_body).decode('utf-8', errors='ignore')
                                body += decoded_body + "\n"
                    elif part.get('mimeType') == 'text/html':
                        if 'data' in part.get('body', {}):
                            encoded_body = part['body']['data']
                            if encoded_body:  # Check if data exists
                                decoded_body = base64.urlsafe_b64decode(encoded_body).decode('utf-8', errors='ignore')
                                # Convert HTML to text (basic)
                                html_text = self._html_to_text(decoded_body)
                                body += html_text + "\n"
            else:
                # Single part email
                if 'data' in payload.get('body', {}):
                    encoded_body = payload['body']['data']
                    if encoded_body:  # Check if data exists
                        decoded_body = base64.urlsafe_b64decode(encoded_body).decode('utf-8', errors='ignore')
                        body = decoded_body
        except Exception as e:
            print(f"Error decoding email body: {str(e)}")
            # Fallback: try to get body from snippet or other sources
            return ""
        
        return self._clean_email_body(body)
    
    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to clean plain text, removing all CSS/JS/formatting"""
        if not html_content:
            return ""
        
        text = html_content
        
        # Remove CSS style blocks and JavaScript
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'@media[^{]*\{[^{}]*\{[^}]*\}[^}]*\}', '', text, flags=re.DOTALL)
        text = re.sub(r'@font-face[^{]*\{[^}]*\}', '', text, flags=re.DOTALL)
        
        # Remove CSS rules and properties scattered in text
        text = re.sub(r'[a-zA-Z-]+\s*:\s*[^;{}]+;', '', text)
        text = re.sub(r'\{[^}]*\}', '', text)
        text = re.sub(r'-->[^{]*\{', '', text)  # Remove --> and CSS start
        text = re.sub(r'\.[a-zA-Z-]+\s*\{', '', text)  # Remove .class {
        text = re.sub(r'\.[a-zA-Z-]+\s*$', '', text, flags=re.MULTILINE)  # Remove standalone .class
        
        # Remove tracking pixels and hidden elements
        text = re.sub(r'%[a-zA-Z0-9_]+%', '', text)
        text = re.sub(r'͏+', '', text)  # Remove invisible characters
        text = re.sub(r'­+', '', text)  # Remove soft hyphens
        
        # Convert semantic HTML to readable text
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?div[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?tr[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
        text = re.sub(r'</?h[1-6][^>]*>', '\n', text, flags=re.IGNORECASE)
        
        # Add minimal spacing for table structure
        text = re.sub(r'</?t[hd][^>]*>', ' ', text, flags=re.IGNORECASE)
        
        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode HTML entities
        text = html.unescape(text)
        
        # Clean up URLs and tracking links
        text = re.sub(r'https?://[^\s]+', '[LINK]', text)
        
        # Aggressive whitespace cleanup
        text = re.sub(r'^\s*\|\s*$', '', text, flags=re.MULTILINE)  # Remove empty pipe lines
        text = re.sub(r'\|\s*\|\s*\|+', '', text)  # Remove multiple pipes
        text = re.sub(r'-->\s*}[|\s]*', '', text)  # Remove -->} artifacts
        text = re.sub(r'^\s*}[|\s]*', '', text, flags=re.MULTILINE)  # Remove standalone } with pipes
        text = re.sub(r'[ \t]{2,}', ' ', text)  # Multiple spaces to single
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple newlines to double
        text = re.sub(r'^\s+|\s+$', '', text, flags=re.MULTILINE)  # Trim line edges
        
        # Remove lines that are mostly CSS artifacts or empty
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            line = line.strip()
            # Skip lines that are CSS artifacts, just punctuation, or very short
            if (len(line) > 3 and 
                not re.match(r'^[|\s\-=]+$', line) and  # Skip lines with just formatting chars
                not re.match(r'^[.,:;!\?}]+$', line) and  # Skip lines with just punctuation/braces
                not re.search(r'^\w+\s*:\s*\w+', line) and  # Skip CSS-like properties
                not re.match(r'^-->\.[a-zA-Z-]+', line) and  # Skip -->className
                not re.match(r'^\.[a-zA-Z-]+$', line) and  # Skip standalone .className
                not re.match(r'^}[|\s]*$', line) and  # Skip closing braces with pipes
                ('[LINK]' not in line or any(word in line.lower() for word in ['transaction', 'payment', 'amount', 'rs', 'upi', 'bank', 'card', 'credit', 'debit']))):
                clean_lines.append(line)
        
        return '\n'.join(clean_lines).strip()
    
    def _clean_email_body(self, body: str) -> str:
        """Clean email body while preserving maximum transaction details"""
        if not body:
            return ""
        
        # Remove email chain headers (forwarded/replied emails)
        body = re.sub(r'----+\s*Original Message\s*----+.*$', '', body, flags=re.DOTALL)
        body = re.sub(r'----+\s*From:.*?----+', '', body, flags=re.DOTALL)
        
        # Remove CSS/JS artifacts that might have escaped HTML cleaning
        body = re.sub(r'@media[^{]*\{.*?\}', '', body, flags=re.DOTALL)
        body = re.sub(r'@font-face[^{]*\{.*?\}', '', body, flags=re.DOTALL)
        body = re.sub(r'[a-zA-Z-]+\s*:\s*[^;{}]+;', '', body)
        
        # Remove tracking/marketing artifacts
        body = re.sub(r'%[a-zA-Z0-9_]+%', '', body)
        body = re.sub(r'͏+', '', body)  # Invisible characters
        body = re.sub(r'­+', '', body)  # Soft hyphens
        
        # Remove obvious non-transaction footers
        body = re.sub(r'Get Outlook for (iOS|Android).*$', '', body, flags=re.DOTALL)
        body = re.sub(r'Sent from my (iPhone|Samsung|Android).*$', '', body, flags=re.DOTALL)
        body = re.sub(r'This is an automated message.*?do not reply.*$', '', body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r'Unsubscribe\s*\|.*$', '', body, flags=re.DOTALL | re.IGNORECASE)
        
        # Clean up pipe artifacts and excessive formatting
        body = re.sub(r'^\s*\|\s*$', '', body, flags=re.MULTILINE)  # Remove empty pipe lines
        body = re.sub(r'\|\s*\|\s*\|+', '', body)  # Remove multiple consecutive pipes
        body = re.sub(r'\|\s*$', '', body, flags=re.MULTILINE)  # Remove trailing pipes
        body = re.sub(r'^\s*\|\s*', '', body, flags=re.MULTILINE)  # Remove leading pipes
        
        # Clean up excessive whitespace
        body = re.sub(r'[ \t]{2,}', ' ', body)  # Multiple spaces/tabs to single
        body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)  # Multiple blank lines to double
        body = re.sub(r'^\s+|\s+$', '', body, flags=re.MULTILINE)  # Trim line edges
        
        # Remove lines that are just formatting artifacts
        lines = body.split('\n')
        clean_lines = []
        for line in lines:
            line = line.strip()
            # Keep lines with meaningful content
            if (len(line) > 2 and 
                not re.match(r'^[|\s\-=_~©]+$', line) and  # Skip lines with just formatting chars
                not re.match(r'^[.,:;!\?]+$', line) and  # Skip lines with just punctuation
                not re.match(r'^\|\s*For more details.*\|\s*©.*$', line) and  # Skip footer lines
                line != ''):
                clean_lines.append(line)
        
        return '\n'.join(clean_lines).strip()
    
    def classify_email(self, subject: str, sender: str, body: str) -> str:
        """Classify email as transaction, order, statement, or other"""
        
        # Combine text for analysis
        full_text = f"{subject} {sender} {body}".lower()
        
        # Check for financial institution patterns
        financial_score = 0
        for pattern in self.financial_patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                financial_score += 2
        
        # Check for transaction keywords
        transaction_score = 0
        for pattern in self.transaction_keywords:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            transaction_score += len(matches)
        
        # Transaction classification rules
        if financial_score >= 2 and transaction_score >= 3:
            return "transaction"
        elif financial_score >= 1 and transaction_score >= 5:
            return "transaction"
        elif "amazon" in full_text and ("order" in full_text or "shipped" in full_text):
            return "order"
        elif ("statement" in full_text or "bill" in full_text) and financial_score >= 1:
            return "statement"
        else:
            return "other"
    
    def extract_email_metadata(self, email: Dict) -> Dict:
        """Extract basic email metadata"""
        payload = email.get('payload', {})
        headers = payload.get('headers', [])
        
        # Extract headers
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
        date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        
        # Parse date
        email_date = self._parse_email_date(date_str)
        
        return {
            'subject': subject,
            'from': sender,
            'date': email_date,
            'email_id': email.get('id', '')
        }
    
    def _parse_email_date(self, date_str: str) -> str:
        """Parse email date to standard format"""
        try:
            # Parse email date
            parsed_date = parsedate_tz(date_str)
            if parsed_date:
                timestamp = mktime_tz(parsed_date)
                dt = datetime.fromtimestamp(timestamp)
                return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def process_email(self, email: Dict) -> Dict:
        """Main email processing function"""
        try:
            # Extract metadata
            metadata = self.extract_email_metadata(email)
            
            # Decode body
            body = self.decode_email_body(email.get('payload', {}))
            
            # Classify email
            category = self.classify_email(metadata['subject'], metadata['from'], body)
            
            # Return structured result
            return {
                'subject': metadata['subject'],
                'datetime': metadata['date'],
                'from': metadata['from'],
                'body': body,
                'category': category,
                'email_id': metadata['email_id']
            }
            
        except Exception as e:
            print(f"Error processing email: {str(e)}")
            return {
                'subject': '',
                'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'from': '',
                'body': '',
                'category': 'other',
                'email_id': email.get('id', ''),
                'error': str(e)
            }

class EmailProcessor:
    """Processes different types of classified emails"""
    
    def __init__(self):
        from ml_transaction_extractor import initialize_ml_extractor
        self.transaction_extractor = initialize_ml_extractor()
    
    def process_by_category(self, email_data: Dict) -> Optional[Dict]:
        """Process email based on its category"""
        category = email_data.get('category', 'other')
        
        if category == 'transaction':
            return self._process_transaction(email_data)
        elif category == 'order':
            return self._process_order(email_data)
        elif category == 'statement':
            return self._process_statement(email_data)
        else:
            return None  # Skip non-relevant emails
    
    def _process_transaction(self, email_data: Dict) -> Dict:
        """Process transaction emails"""
        body = email_data.get('body', '')
        
        # Extract transaction details using existing ML model
        transaction_details = self.transaction_extractor.extract_transaction_details(body)
        
        # Format according to new JSON structure
        result = {
            "account_number": transaction_details.get('account_number'),
            "amount": transaction_details.get('amount'),
            "available_balance": transaction_details.get('available_balance'),
            "card_last_four": transaction_details.get('card_last_four'),
            "category": transaction_details.get('category', 'other'),
            "credit_or_debit": transaction_details.get('credit_or_debit', 'debit'),
            "currency": transaction_details.get('currency', 'INR'),
            "date": transaction_details.get('date'),
            "description": transaction_details.get('description'),
            "from_account": transaction_details.get('from_account'),
            "to_account": transaction_details.get('to_account'),
            "merchant": transaction_details.get('merchant'),
            "mode": transaction_details.get('mode'),
            "reference_number": transaction_details.get('reference_number'),
            "email_from": email_data.get('from'),
            "transaction_identifier_id": email_data.get('email_id'),
            "email_subject": email_data.get('subject')
        }
        
        return result
    
    def _process_order(self, email_data: Dict) -> Dict:
        """Process order emails (placeholder for future)"""
        # TODO: Implement order processing
        return {
            "type": "order",
            "email_from": email_data.get('from'),
            "email_subject": email_data.get('subject'),
            "transaction_identifier_id": email_data.get('email_id'),
            "body": email_data.get('body')
        }
    
    def _process_statement(self, email_data: Dict) -> Dict:
        """Process statement emails (placeholder for future)"""
        # TODO: Implement statement processing
        return {
            "type": "statement",
            "email_from": email_data.get('from'),
            "email_subject": email_data.get('subject'),
            "transaction_identifier_id": email_data.get('email_id'),
            "body": email_data.get('body')
        }

# Main processing functions
def classify_and_process_email(email: Dict) -> Optional[Dict]:
    """Main function to classify and process an email"""
    classifier = EmailClassifier()
    processor = EmailProcessor()
    
    # Step 1: Classify email and extract basic info
    email_data = classifier.process_email(email)
    
    # Step 2: Process based on category
    if email_data.get('category') == 'transaction':
        return processor.process_by_category(email_data)
    else:
        # For future: handle orders, statements, etc.
        return None

def batch_process_emails(emails: List[Dict]) -> List[Dict]:
    """Process multiple emails in batch"""
    results = []
    
    for email in emails:
        try:
            result = classify_and_process_email(email)
            if result:  # Only add valid transactions
                results.append(result)
        except Exception as e:
            print(f"Error processing email {email.get('id', 'unknown')}: {str(e)}")
    
    return results

if __name__ == "__main__":
    # Test the classifier
    print("Email Classifier and Processor ready!")
    print("Supports: Transaction emails, Orders (future), Statements (future)")