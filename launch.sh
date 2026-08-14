#!/bin/bash
cd ~/Acca-production-

# Install pip for your user account if missing (no sudo needed)
if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "Installing pip..."
    curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python3 get-pip.py --user
fi

echo "Installing requirements..."
python3 -m pip install --user -r requirements.txt

echo "Stopping any old copy of the bot..."
pkill -f "python3 main.py" 2>/dev/null
sleep 1

echo "Starting bot..."
nohup python3 main.py > bot_output.log 2>&1 &
BOT_PID=$!
sleep 3

if kill -0 $BOT_PID 2>/dev/null; then
    echo "✅ Bot is running in the background. PID: $BOT_PID"
else
    echo "❌ Bot crashed on startup. Check the error below:"
    cat bot_output.log
fi
