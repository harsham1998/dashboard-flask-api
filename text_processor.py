import re
from typing import Dict, Optional

class TextProcessor:
    def __init__(self):
        self.transaction_keywords = [
            'transaction', 'payment', 'transfer', 'credited', 'debited', 
            'upi', 'imps', 'neft', 'rtgs', 'atm', 'card', 'account', 'balance',
            'sent', 'received', 'withdraw', 'deposit', 'successful', 'failed'
        ]
        
        self.banks = [
            'hdfc', 'sbi', 'icici', 'axis', 'kotak', 'pnb', 'bob', 'canara', 
            'union', 'indian', 'boi', 'central', 'syndicate', 'uco', 'vijaya', 
            'dena', 'corporation', 'allahabad', 'ubi', 'obc', 'andhra', 'karur', 
            'federal', 'south indian', 'city union', 'dhanlaxmi', 'karnataka', 
            'maharashtra', 'rajasthan', 'uttar bihar', 'west bengal', 'punjab', 
            'tamil nadu', 'telangana', 'kerala', 'paytm', 'phonepe', 'googlepay', 
            'amazon pay', 'mobikwik', 'freecharge', 'airtel'
        ]
        
        self.merchants = [
            'amazon', 'flipkart', 'zomato', 'swiggy', 'uber', 'ola', 'paytm', 
            'phonepe', 'google', 'netflix', 'spotify', 'jio', 'airtel', 'vodafone', 
            'bsnl', 'irctc', 'makemytrip', 'booking', 'myntra', 'ajio', 'nykaa', 
            'bigbasket', 'grofers', 'dunzo', 'zepto', 'blinkit'
        ]
    
    def parse_transaction_message(self, message: str) -> Optional[Dict]:
        """Parse transaction message and extract details"""
        msg = message.lower()
        
        # Check if message contains transaction keywords
        has_transaction_keyword = any(keyword in msg for keyword in self.transaction_keywords)
        if not has_transaction_keyword:
            return None
        
        # Extract amount
        amount_match = re.search(r'(?:rs\.?\s*|₹\s*|inr\s*)?(\d+(?:,\d+)*(?:\.\d{2})?)', msg, re.IGNORECASE)
        amount = float(amount_match[1].replace(',', '')) if amount_match else 0
        
        # Determine transaction type
        transaction_type = 'debited'
        if any(word in msg for word in ['credited', 'received', 'deposit']):
            transaction_type = 'credited'
        elif any(word in msg for word in ['debited', 'sent', 'withdraw', 'payment']):
            transaction_type = 'debited'
        
        # Extract bank
        bank = 'Unknown'
        for b in self.banks:
            if b in msg:
                bank = ' '.join(word.capitalize() for word in b.split())
                break
        
        # Extract mode
        mode = 'Unknown'
        if 'upi' in msg:
            mode = 'UPI'
        elif any(word in msg for word in ['card', 'debit', 'credit']):
            mode = 'Card'
        elif 'imps' in msg:
            mode = 'IMPS'
        elif 'neft' in msg:
            mode = 'NEFT'
        elif 'rtgs' in msg:
            mode = 'RTGS'
        elif 'atm' in msg:
            mode = 'ATM'
        elif 'transfer' in msg:
            mode = 'Bank Transfer'
        elif 'cash' in msg:
            mode = 'Cash'
        
        # Extract balance
        balance_match = re.search(r'(?:balance|bal|available)\s*(?:is|:)?\s*(?:rs\.?\s*|₹\s*|inr\s*)?(\d+(?:,\d+)*(?:\.\d{2})?)', msg, re.IGNORECASE)
        balance = float(balance_match[1].replace(',', '')) if balance_match else None
        
        # Extract description/merchant
        description = ''
        to_match = re.search(r'(?:to|from)\s+([a-zA-Z0-9\s@._-]+?)(?:\s+(?:rs|₹|inr|is|for|on|at)|\s*$)', msg, re.IGNORECASE)
        if to_match:
            description = to_match[1].strip()
        else:
            # Look for merchant/service names
            for merchant in self.merchants:
                if merchant in msg:
                    description = merchant.capitalize()
                    break
        
        return {
            'amount': amount,
            'type': transaction_type,
            'bank': bank,
            'mode': mode,
            'balance': balance,
            'description': description or 'Transaction',
            'rawMessage': message
        }