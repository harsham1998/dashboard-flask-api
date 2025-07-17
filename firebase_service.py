import requests
import json
from datetime import datetime
from typing import Dict, List, Optional

class FirebaseService:
    def __init__(self):
        self.base_url = "https://dashboard-app-fcd42-default-rtdb.firebaseio.com"
        
    def get_data(self) -> Dict:
        """Get all data from Firebase"""
        try:
            response = requests.get(f"{self.base_url}/.json")
            if response.status_code == 200:
                data = response.json()
                if data is None:
                    return self._get_default_data()
                return data
            else:
                print(f"Error fetching data: {response.status_code}")
                return self._get_default_data()
        except Exception as e:
            print(f"Firebase get_data error: {e}")
            return self._get_default_data()
    
    def save_data(self, data: Dict) -> bool:
        """Save data to Firebase"""
        try:
            response = requests.put(f"{self.base_url}/.json", json=data)
            return response.status_code == 200
        except Exception as e:
            print(f"Firebase save_data error: {e}")
            return False
    
    def add_task(self, task_data: Dict) -> bool:
        """Add a task to Firebase"""
        try:
            data = self.get_data()
            date = task_data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            if 'tasks' not in data:
                data['tasks'] = {}
            if date not in data['tasks']:
                data['tasks'][date] = []
            
            data['tasks'][date].append(task_data)
            return self.save_data(data)
        except Exception as e:
            print(f"Firebase add_task error: {e}")
            return False
    
    def add_transaction(self, transaction_data: Dict) -> bool:
        """Add a transaction to Firebase"""
        try:
            data = self.get_data()
            
            if 'transactions' not in data:
                data['transactions'] = []
            
            # Add transaction to beginning of list
            data['transactions'].insert(0, transaction_data)
            
            # Keep only last 50 transactions
            if len(data['transactions']) > 50:
                data['transactions'] = data['transactions'][:50]
            
            return self.save_data(data)
        except Exception as e:
            print(f"Firebase add_transaction error: {e}")
            return False
    
    def get_tasks(self, date: Optional[str] = None) -> List[Dict]:
        """Get tasks for a specific date or all tasks"""
        try:
            data = self.get_data()
            tasks = data.get('tasks', {})
            
            if date:
                return tasks.get(date, [])
            return tasks
        except Exception as e:
            print(f"Firebase get_tasks error: {e}")
            return []
    
    def get_transactions(self, limit: int = 5) -> List[Dict]:
        """Get recent transactions"""
        try:
            data = self.get_data()
            transactions = data.get('transactions', [])
            return transactions[:limit]
        except Exception as e:
            print(f"Firebase get_transactions error: {e}")
            return []
    
    def _get_default_data(self) -> Dict:
        """Return default data structure"""
        return {
            "tasks": {},
            "quickNotes": "",
            "importantFeed": [],
            "quickLinks": [
                {"id": 1, "name": "Gmail", "url": "https://gmail.com"},
                {"id": 2, "name": "GitHub", "url": "https://github.com"}
            ],
            "teamMembers": [
                "Harsha (Me)", "Ujjawal", "Arun", "Sanskar", "Thombre", 
                "Sakshi", "Soumi", "Ayush", "Aditya", "Sankalp"
            ],
            "transactions": []
        }