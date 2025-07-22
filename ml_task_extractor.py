#!/usr/bin/env python3
"""
ML Task Extractor
Machine Learning-based task detail extraction from text and JSON input
"""

import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TaskExtractor:
    """ML-based task extractor for parsing task information from various input formats"""
    
    def __init__(self):
        # Initialize patterns for extracting different types of information
        self.patterns = {
            'hours': [
                r'(\d+)\s*h(ou)?rs?',
                r'(\d+)\s*h\b',
                r'(\d+)\s*hours?',
                r'budget:?\s*(\d+)',
                r'effort:?\s*(\d+)',
                r'estimate:?\s*(\d+)',
                r'expected.{0,10}hours?:?\s*(\d+)',
                r'duration:?\s*(\d+)'
            ],
            'dates': [
                r'\d{4}-\d{2}-\d{2}',
                r'\d{2}/\d{2}/\d{4}',
                r'\d{1,2}/\d{1,2}/\d{4}',
                r'due:?\s*(\d{4}-\d{2}-\d{2})',
                r'deadline:?\s*(\d{4}-\d{2}-\d{2})',
                r'by:?\s*(\d{4}-\d{2}-\d{2})',
                r'target:?\s*(\d{4}-\d{2}-\d{2})'
            ],
            'assignee': [
                r'assigned\s+to:?\s*([A-Za-z\s]+)',
                r'assignee:?\s*([A-Za-z\s]+)',
                r'owner:?\s*([A-Za-z\s]+)',
                r'developer:?\s*([A-Za-z\s]+)',
                r'responsible:?\s*([A-Za-z\s]+)',
                r'assignedto["\']?\s*:\s*["\']?([^"\']+)["\']?'
            ],
            'sprint': [
                r'sprint:?\s*(\d+)',
                r'sprint\s+id:?\s*(\d+)',
                r'iteration:?\s*(\d+)',
                r'sprintid["\']?\s*:\s*["\']?(\d+)["\']?'
            ],
            'competency': [
                r'competency:?\s*(\d+)',
                r'skill:?\s*(\d+)',
                r'category:?\s*(\d+)',
                r'competencyid["\']?\s*:\s*["\']?(\d+)["\']?'
            ],
            'project': [
                r'project:?\s*([^,\n]+)',
                r'project\s+name:?\s*([^,\n]+)',
                r'taskprojectname["\']?\s*:\s*["\']?([^"\']+)["\']?'
            ]
        }
        
        # Default values based on the provided JSON structure
        self.defaults = {
            'assignedTo': 'Harshavardhan Mandali',
            'assignedBy': 'Harshavardhan Mandali',
            'sprint': '2370',
            'competency': '498',
            'codingHours': 8,
            'testingHours': 2,
            'reviewHours': 1,
            'projectId': '824',
            'projectName': 'THD - Support'
        }

    def clean_text(self, text: str) -> str:
        """Clean and normalize text input"""
        if not text:
            return ""
        
        # Remove extra whitespace and normalize
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', '', text)
        
        return text

    def extract_from_json(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract task details from JSON structure"""
        logger.info(f"Extracting from JSON: {list(json_data.keys())}")
        
        extracted = {
            'taskName': '',
            'assignedTo': '',
            'assignedBy': '',
            'dueDate': '',
            'sprint': '',
            'competency': '',
            'codingHours': 0,
            'testingHours': 0,
            'reviewHours': 0,
            'projectId': '',
            'projectName': '',
            'priority': 2,
            'category': 1
        }
        
        # Extract task name from multiple possible fields
        task_name_fields = ['TaskName', 'MDDescription', 'Notes', 'taskName', 'name', 'title']
        for field in task_name_fields:
            if field in json_data and json_data[field]:
                extracted['taskName'] = self.clean_text(str(json_data[field]))
                break
        
        # Extract assignee information
        extracted['assignedTo'] = json_data.get('AssignedTo') or json_data.get('assignedTo', '')
        extracted['assignedBy'] = json_data.get('AssignedBy') or json_data.get('assignedBy', '')
        
        # Extract due date
        due_date_fields = ['TaskDueDate', 'dueDate', 'deadline', 'targetDate']
        for field in due_date_fields:
            due_date = json_data.get(field)
            if due_date:
                try:
                    # Handle different date formats
                    if isinstance(due_date, str):
                        # Remove time part if present
                        date_str = due_date.replace(' 00:00:00', '').split('T')[0]
                        date_obj = datetime.fromisoformat(date_str)
                        extracted['dueDate'] = date_obj.strftime('%Y-%m-%d')
                        break
                except Exception as e:
                    logger.warning(f"Date parsing error for {due_date}: {e}")
                    continue
        
        # Extract IDs and references
        extracted['sprint'] = str(json_data.get('SprintID') or json_data.get('sprintId') or json_data.get('sprint', ''))
        extracted['competency'] = str(json_data.get('CompetencyID') or json_data.get('competencyId') or json_data.get('competency', ''))
        extracted['projectId'] = str(json_data.get('TaskProjectID') or json_data.get('projectId', ''))
        extracted['projectName'] = json_data.get('TaskProjectName') or json_data.get('projectName', '')
        extracted['priority'] = json_data.get('TaskPriorityID') or json_data.get('priority', 2)
        extracted['category'] = json_data.get('TaskCategoryID') or json_data.get('category', 1)
        
        # Extract hours from TaskBillingStatuses
        billing_statuses = json_data.get('TaskBillingStatuses', [])
        if billing_statuses:
            for billing in billing_statuses:
                name = billing.get('BillingStatusName', '').lower()
                hours = billing.get('expectedHours') or billing.get('StatusEfforts') or 0
                
                if 'coding' in name or 'development' in name:
                    extracted['codingHours'] = int(hours)
                elif 'testing' in name or 'qa' in name:
                    extracted['testingHours'] = int(hours)
                elif 'review' in name or 'misc' in name or 'documentation' in name:
                    extracted['reviewHours'] = int(hours)
        
        # Fallback to ExpectedHours if no specific billing found
        if not any([extracted['codingHours'], extracted['testingHours'], extracted['reviewHours']]):
            expected_hours = json_data.get('ExpectedHours', 0)
            if expected_hours:
                total_hours = int(expected_hours)
                extracted['codingHours'] = max(1, int(total_hours * 0.7))  # 70% coding
                extracted['testingHours'] = max(0, int(total_hours * 0.2))  # 20% testing
                extracted['reviewHours'] = max(0, int(total_hours * 0.1))   # 10% review
        
        logger.info(f"Extracted task: {extracted['taskName'][:50]}...")
        return extracted

    def extract_from_text(self, text: str) -> Dict[str, Any]:
        """Extract task details from plain text using pattern matching and heuristics"""
        logger.info(f"Extracting from text: {text[:100]}...")
        
        extracted = {
            'taskName': '',
            'assignedTo': '',
            'assignedBy': '',
            'dueDate': '',
            'sprint': '',
            'competency': '',
            'codingHours': 0,
            'testingHours': 0,
            'reviewHours': 0,
            'projectId': '',
            'projectName': '',
            'priority': 2,
            'category': 1
        }
        
        # Clean and normalize text
        text = self.clean_text(text)
        text_lower = text.lower()
        
        # Extract task name (use first meaningful line or sentence)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            # Use the longest line or first line as task name
            potential_names = [line for line in lines if len(line) > 10]
            if potential_names:
                extracted['taskName'] = max(potential_names, key=len)
            else:
                extracted['taskName'] = lines[0]
        else:
            # Single line text
            extracted['taskName'] = text[:200] if text else 'Untitled Task'
        
        # Extract hours using patterns
        total_hours_found = 0
        for pattern in self.patterns['hours']:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    hours = int(match.group(1))
                    total_hours_found = hours
                    break
                except (ValueError, IndexError):
                    continue
        
        # Distribute hours if found
        if total_hours_found > 0:
            extracted['codingHours'] = max(1, int(total_hours_found * 0.7))
            extracted['testingHours'] = max(0, int(total_hours_found * 0.2))
            extracted['reviewHours'] = max(0, int(total_hours_found * 0.1))
        
        # Extract dates
        for pattern in self.patterns['dates']:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1) if match.groups() else match.group(0)
                try:
                    # Try different date formats
                    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y'):
                        try:
                            date_obj = datetime.strptime(date_str, fmt)
                            extracted['dueDate'] = date_obj.strftime('%Y-%m-%d')
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
                if extracted['dueDate']:
                    break
        
        # Extract assignee
        for pattern in self.patterns['assignee']:
            match = re.search(pattern, text_lower)
            if match:
                assignee = match.group(1).strip().title()
                # Clean up common artifacts
                assignee = re.sub(r'["\',]', '', assignee).strip()
                if assignee and len(assignee) > 2:
                    extracted['assignedTo'] = assignee
                break
        
        # Extract sprint
        for pattern in self.patterns['sprint']:
            match = re.search(pattern, text_lower)
            if match:
                extracted['sprint'] = match.group(1)
                break
        
        # Extract competency
        for pattern in self.patterns['competency']:
            match = re.search(pattern, text_lower)
            if match:
                extracted['competency'] = match.group(1)
                break
        
        # Extract project information
        for pattern in self.patterns['project']:
            match = re.search(pattern, text_lower)
            if match:
                project = match.group(1).strip().title()
                extracted['projectName'] = re.sub(r'["\',]', '', project).strip()
                break
        
        # Apply defaults for empty fields
        for key, default_value in self.defaults.items():
            if not extracted.get(key):
                extracted[key] = default_value
        
        # Set minimum default hours if none found
        if not any([extracted['codingHours'], extracted['testingHours'], extracted['reviewHours']]):
            extracted['codingHours'] = self.defaults['codingHours']
            extracted['testingHours'] = self.defaults['testingHours']
            extracted['reviewHours'] = self.defaults['reviewHours']
        
        logger.info(f"Text extraction complete: {extracted['taskName'][:50]}...")
        return extracted

    def process_input(self, input_data: str) -> List[Dict[str, Any]]:
        """Process input data and return list of extracted tasks"""
        logger.info(f"Processing input: {len(input_data)} characters")
        
        if not input_data or not input_data.strip():
            return []
        
        tasks = []
        
        try:
            # Try to parse as JSON first
            input_data = input_data.strip()
            if input_data.startswith('{') or input_data.startswith('['):
                logger.info("Parsing as JSON...")
                json_data = json.loads(input_data)
                
                if isinstance(json_data, list):
                    for i, item in enumerate(json_data):
                        logger.info(f"Processing JSON item {i+1}/{len(json_data)}")
                        tasks.append(self.extract_from_json(item))
                else:
                    tasks.append(self.extract_from_json(json_data))
            else:
                # Process as text
                logger.info("Processing as text...")
                # Split into multiple tasks if separated by clear delimiters
                task_separators = [
                    '\n---\n', '\n===\n', '\n\n\n',
                    'Task:', 'TASK:', 'Task #', 'TASK #'
                ]
                
                parts = [input_data]
                for separator in task_separators:
                    new_parts = []
                    for part in parts:
                        if separator in part:
                            new_parts.extend(part.split(separator))
                        else:
                            new_parts.append(part)
                    parts = new_parts
                
                # Process each part
                for i, part in enumerate(parts):
                    part = part.strip()
                    if part and len(part) > 10:  # Minimum length for a meaningful task
                        logger.info(f"Processing text part {i+1}/{len(parts)}")
                        tasks.append(self.extract_from_text(part))
        
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}, treating as text")
            tasks.append(self.extract_from_text(input_data))
        except Exception as e:
            logger.error(f"Error processing input: {e}")
            # Fallback to text processing
            tasks.append(self.extract_from_text(input_data))
        
        logger.info(f"Extraction complete: {len(tasks)} tasks found")
        return tasks

    def generate_task_json(self, extracted_task: Dict[str, Any]) -> Dict[str, Any]:
        """Generate the full task JSON structure from extracted data"""
        return {
            "AssignedBy": extracted_task.get('assignedBy') or self.defaults['assignedBy'],
            "AssignedTo": extracted_task.get('assignedTo') or self.defaults['assignedTo'],
            "AssignedToEmpID": 2754,
            "AssociatedTasks": "",
            "Attachments": [],
            "CompetencyID": int(extracted_task.get('competency') or self.defaults['competency']),
            "EmpID": 2754,
            "ExpectedHours": extracted_task.get('codingHours', 0) + extracted_task.get('testingHours', 0) + extracted_task.get('reviewHours', 0),
            "GetUpdates": "0",
            "InformTo": "",
            "IsTaskEdited": False,
            "ModuleName": "",
            "MDDescription": extracted_task.get('taskName', 'Untitled Task'),
            "NonBillableTask": "",
            "Notes": f"<p>{extracted_task.get('taskName', 'Untitled Task')}</p>",
            "OwnerID": "2754",
            "SendEmail": True,
            "SprintID": int(extracted_task.get('sprint') or self.defaults['sprint']),
            "TaskBillingStatuses": [
                {
                    "BillingStatusID": 206,
                    "BillingStatusName": "Coding",
                    "StatusEfforts": extracted_task.get('codingHours', 0),
                    "Color": "#0067a5",
                    "CompanyID": 0,
                    "CreatedOn": "0001-01-01 00:00:00",
                    "ModifiedOn": "0001-01-01 00:00:00",
                    "ProjectID": int(extracted_task.get('projectId') or self.defaults['projectId']),
                    "IsActive": True,
                    "IsMandatory": True,
                    "expectedHours": extracted_task.get('codingHours', 0),
                    "showInput": False
                },
                {
                    "BillingStatusID": 207,
                    "BillingStatusName": "Testing",
                    "Color": "#e25822",
                    "StatusEfforts": extracted_task.get('testingHours', 0),
                    "CompanyID": 0,
                    "CreatedOn": "0001-01-01 00:00:00",
                    "ModifiedOn": "0001-01-01 00:00:00",
                    "ProjectID": int(extracted_task.get('projectId') or self.defaults['projectId']),
                    "IsActive": True,
                    "IsMandatory": False,
                    "expectedHours": extracted_task.get('testingHours', 0),
                    "showInput": False
                },
                {
                    "BillingStatusID": 18682,
                    "BillingStatusName": "Review",
                    "Color": "#8DB600",
                    "StatusEfforts": extracted_task.get('reviewHours', 0),
                    "CompanyID": 0,
                    "CreatedOn": "0001-01-01 00:00:00",
                    "ModifiedOn": "0001-01-01 00:00:00",
                    "ProjectID": int(extracted_task.get('projectId') or self.defaults['projectId']),
                    "IsActive": True,
                    "IsMandatory": False,
                    "expectedHours": extracted_task.get('reviewHours', 0),
                    "showInput": False
                }
            ],
            "TaskCategoryID": extracted_task.get('category', 1),
            "TaskDifficultyID": 2,
            "TaskDueDate": f"{extracted_task.get('dueDate') or '2025-07-31'} 00:00:00",
            "TaskID": "",
            "TaskName": extracted_task.get('taskName', 'Untitled Task'),
            "TaskPriorityID": extracted_task.get('priority', 2),
            "TaskProjectID": int(extracted_task.get('projectId') or self.defaults['projectId']),
            "TaskProjectName": extracted_task.get('projectName') or self.defaults['projectName'],
            "TaskStatusID": 452,
            "TaskSprintID": "",
            "TaskWithMultipleCategories": [],
            "UserStoryID": "0",
            "TaskHistories": [],
            "Predictions": []
        }


# Create a global instance for use in API
task_extractor = TaskExtractor()

def extract_tasks_from_input(input_data: str) -> Dict[str, Any]:
    """Main function to extract tasks from input - to be used by API"""
    try:
        extracted_tasks = task_extractor.process_input(input_data)
        
        return {
            "success": True,
            "tasks_count": len(extracted_tasks),
            "tasks": extracted_tasks,
            "metadata": {
                "processed_at": datetime.now().isoformat(),
                "input_type": "json" if input_data.strip().startswith(('{', '[')) else "text",
                "input_length": len(input_data)
            }
        }
    except Exception as e:
        logger.error(f"Task extraction error: {e}")
        return {
            "success": False,
            "error": str(e),
            "tasks_count": 0,
            "tasks": []
        }