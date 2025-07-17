#!/usr/bin/env python3
"""
Dashboard Flask API - Main Entry Point
Handles Siri integration for tasks and transactions with Firebase storage
"""

from flask import Flask
from api import app
import sys
import os

def main():
    """Main function to run the Flask API server"""
    try:
        print("=" * 60)
        print("🚀 DASHBOARD FLASK API SERVER")
        print("=" * 60)
        print("📡 Local URL: http://localhost:5000")
        print("🌐 Network URL: http://YOUR_IP:5000")
        print("🔥 Firebase: dashboard-app-fcd42-default-rtdb.firebaseio.com")
        print("")
        print("📱 SIRI ENDPOINTS:")
        print("   Tasks: /siri/add-task?text=YOUR_TASK")
        print("   Transactions: /siri/addTransaction?message=YOUR_SMS")
        print("")
        print("🔧 API ENDPOINTS:")
        print("   GET  / - API info")
        print("   GET  /health - Health check")
        print("   GET  /tasks - All tasks")
        print("   POST /tasks - Add task")
        print("   GET  /transactions - Recent transactions")
        print("")
        print("💡 USAGE:")
        print("   1. Create Siri Shortcuts pointing to these URLs")
        print("   2. Forward SMS messages to transaction endpoint")
        print("   3. Add tasks via voice commands")
        print("")
        print("✅ Starting server...")
        print("=" * 60)
        
        # Run the Flask app
        port = int(os.environ.get('PORT', 5000))  # Use Render.com PORT or default to 5000
        app.run(
            debug=False,  # Set to False for production
            host='0.0.0.0',
            port=port,
            use_reloader=False  # Disable reloader in production
        )
        
    except KeyboardInterrupt:
        print("\n🔴 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()