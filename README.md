# Dashboard Flask API

Flask-based API for Dashboard app with Firebase integration and Siri shortcuts support.

## 🚀 Quick Start

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Server:**
   ```bash
   python main.py
   # or
   python app.py
   # or
   flask run
   ```

3. **Access API:**
   - Local: http://localhost:5000
   - Network: http://YOUR_IP:5000

## 📱 Siri Integration

### Add Tasks
```
http://localhost:5000/siri/add-task?text=Buy groceries
```

### Process Transactions
```
http://localhost:5000/siri/addTransaction?message=Your UPI payment to Amazon Pay of Rs.500 is successful
```

## 🔥 Firebase Integration

- **Database:** `https://dashboard-app-fcd42-default-rtdb.firebaseio.com`
- **Tasks:** `/tasks.json`
- **Transactions:** `/transactions.json`

## 📋 API Endpoints

### Tasks
- `GET /tasks` - Get all tasks
- `POST /tasks` - Add new task
- `GET /tasks/<date>` - Get tasks for specific date
- `GET /siri/add-task?text=<task>` - Add task via Siri

### Transactions
- `GET /transactions` - Get recent transactions
- `GET /transactions?limit=<n>` - Get specific number of transactions
- `GET /siri/addTransaction?message=<sms>` - Process transaction SMS

### System
- `GET /` - API information
- `GET /health` - Health check

## 🧪 Testing

1. **Open Test Interface:**
   ```
   http://localhost:5000/index.html
   http://localhost:5000/test_api.html
   ```

2. **Test with curl:**
   ```bash
   # Add task
   curl "http://localhost:5000/siri/add-task?text=Test task"
   
   # Process transaction
   curl "http://localhost:5000/siri/addTransaction?message=Rs.500 debited from HDFC Bank"
   
   # Get health
   curl http://localhost:5000/health
   ```

## 📁 File Structure

```
api/
├── main.py              # Main entry point
├── app.py               # Flask app runner
├── api.py               # API routes and logic
├── firebase_service.py  # Firebase integration
├── text_processor.py    # Transaction message parsing
├── index.html          # API documentation page
├── test_api.html       # Interactive API tester
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## 🔧 Configuration

No configuration needed! The API uses Firebase Realtime Database with public read/write access.

## 🚀 Deployment

### Replit
1. Upload files to Replit
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python main.py`
4. Access via Replit URL

### Heroku
1. Add `Procfile`: `web: python main.py`
2. Deploy to Heroku
3. Access via Heroku URL

### Local Development
```bash
cd api/
python main.py
```

## 🎯 Siri Shortcuts Setup

1. **Create Shortcuts on iPhone**
2. **Add Web Request action**
3. **Use these URLs:**
   - Tasks: `http://YOUR_SERVER/siri/add-task?text=[Spoken Text]`
   - Transactions: `http://YOUR_SERVER/siri/addTransaction?message=[SMS Content]`

## 📊 Data Structure

### Task Object
```json
{
  "id": 1752739988034,
  "text": "Buy groceries",
  "completed": false,
  "assignee": "Harsha (Me)",
  "status": "pending",
  "note": "",
  "issues": [],
  "appreciation": [],
  "createdAt": "2025-07-17T08:13:08.034Z"
}
```

### Transaction Object
```json
{
  "id": 1752739988034,
  "amount": 500,
  "type": "debited",
  "bank": "HDFC",
  "mode": "UPI",
  "balance": 15000,
  "description": "Amazon Pay",
  "rawMessage": "Your UPI payment...",
  "timestamp": "2025-07-17T08:13:08.034Z"
}
```

## 🛠️ Development

- **Flask** - Web framework
- **Firebase Realtime Database** - Data storage
- **CORS** - Cross-origin requests
- **Requests** - HTTP client for Firebase