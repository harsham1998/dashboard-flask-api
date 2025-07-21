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
            response = requests.get(f"{self.base_url}/data.json")
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
            response = requests.put(f"{self.base_url}/data.json", json=data)
            return response.status_code == 200
        except Exception as e:
            print(f"Firebase save_data error: {e}")
            return False
    
    def add_task(self, task_data: Dict) -> bool:
        """Add a task to Firebase"""
        try:
            data = self.get_data()
            date = task_data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            # Initialize structure if needed
            if 'tasks' not in data:
                data['tasks'] = {}
            if date not in data['tasks']:
                data['tasks'][date] = []
            
            # Remove date from task_data before adding
            task_copy = {k: v for k, v in task_data.items() if k != 'date'}
            data['tasks'][date].append(task_copy)
            
            return self.save_data(data)
        except Exception as e:
            print(f"Firebase add_task error: {e}")
            return False
    
    def add_task_for_user(self, user_email: str, task_data: Dict) -> bool:
        """Add a task to Firebase for a specific user"""
        try:
            # Convert email to user ID (replace @ and . with _)
            user_id = user_email.replace('@', '_').replace('.', '_')
            
            # Get user-specific data
            response = requests.get(f"{self.base_url}/users/{user_id}.json")
            if response.status_code == 200:
                data = response.json()
                if data is None:
                    data = self._get_default_user_data()
            else:
                data = self._get_default_user_data()
            
            date = task_data.get('date', datetime.now().strftime('%Y-%m-%d'))
            
            # Initialize structure if needed
            if 'tasks' not in data:
                data['tasks'] = {}
            if date not in data['tasks']:
                data['tasks'][date] = []
            
            # Remove date from task_data before adding
            task_copy = {k: v for k, v in task_data.items() if k != 'date'}
            data['tasks'][date].append(task_copy)
            
            # Save user-specific data
            response = requests.put(f"{self.base_url}/{user_id}.json", json=data)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Firebase add_task_for_user error: {e}")
            return False
    
    def _get_default_user_data(self) -> Dict:
        """Get default user data structure"""
        return {
            'tasks': {},
            'quickNotes': '',
            'importantFeed': [],
            'quickLinks': [],
            'teamMembers': [],
            'taskStatuses': ['pending', 'programming', 'discussion', 'pretest', 'test', 'live'],
            'transactions': [],
            'creditCards': [],
            'currentDate': datetime.now().strftime('%Y-%m-%d'),
            'lastUpdated': datetime.now().isoformat()
        }
    
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
    
    def get_user_data(self, user_email_key: str) -> Optional[Dict]:
        """Get user data from Firebase users collection"""
        try:
            response = requests.get(f"{self.base_url}/users/{user_email_key}.json")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Firebase get_user_data error: {e}")
            return None
    
    def update_user_data(self, user_email_key: str, user_data: Dict) -> bool:
        """Update user data in Firebase users collection"""
        try:
            response = requests.put(f"{self.base_url}/users/{user_email_key}.json", json=user_data)
            return response.status_code == 200
        except Exception as e:
            print(f"Firebase update_user_data error: {e}")
            return False
    
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