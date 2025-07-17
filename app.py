from api import app

if __name__ == '__main__':
    print("🚀 Dashboard Flask API Server Starting...")
    print("📡 Server will run on: http://localhost:5000")
    print("🌐 Network access: http://YOUR_IP:5000")
    print("")
    print("📱 Endpoints:")
    print("   GET  http://localhost:5000/")
    print("   GET  http://localhost:5000/siri/add-task?text=YOUR_TASK")
    print("   GET  http://localhost:5000/siri/addTransaction?message=YOUR_MESSAGE")
    print("   GET  http://localhost:5000/tasks")
    print("   GET  http://localhost:5000/transactions")
    print("")
    print("🎤 Siri Usage:")
    print("   Tasks: http://localhost:5000/siri/add-task?text=Buy%20groceries")
    print("   Transactions: http://localhost:5000/siri/addTransaction?message=YOUR_SMS")
    print("")
    print("🔥 Firebase: https://dashboard-app-fcd42-default-rtdb.firebaseio.com")
    print("✅ Server ready for Siri shortcuts!")
    
    app.run(debug=True, host='0.0.0.0', port=5000)