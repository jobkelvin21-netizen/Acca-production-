#!/bin/bash
cd ~/Acca-production-

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt

pkill -f "python3 main.py" 2>/dev/null
sleep 1

nohup python3 main.py > bot_output.log 2>&1 &

sleep 2
echo "Bot is running in the background."
