import json
from datetime import datetime, timedelta
import pytz

# Load scraped connections data
with open('scraped_connections.json', 'r', encoding='utf-8') as f:
    scraped_data = json.load(f)

# Load config data
with open('config.json', 'r', encoding='utf-8') as f:
    config_data = json.load(f)

# Extract withdraw_connection_days_after_sending from config
withdraw_connection_days_after_sending = 0
for item in config_data:
    if "withdraw_connection_days_after_sending" in item:
        withdraw_connection_days_after_sending = item["withdraw_connection_days_after_sending"]
        break

total_count = len(scraped_data)
sent_request_true_count = 0
sent_request_false_count = 0
withdraw_total_count = 0
latest_sent_request_timestamp = None

for item in scraped_data:
    if item.get('sent_request') is True:
        sent_request_true_count += 1
        timestamp_str = item.get('sent_request_timestamp')
        if timestamp_str:
            # Parse timestamp, assuming it's in UTC (ISO format without Z implies local or unspecified, but for consistency, treating as UTC)
            # Then convert to IST for comparison
            dt_utc = datetime.fromisoformat(timestamp_str).replace(tzinfo=pytz.utc)
            if latest_sent_request_timestamp is None or dt_utc > latest_sent_request_timestamp:
                latest_sent_request_timestamp = dt_utc
    elif item.get('sent_request') is False:
        sent_request_false_count += 1
    
    if 'withdraw' in item:
        withdraw_total_count += 1

print(f"Total number of connections: {total_count}")
print(f"Sent Request True: {sent_request_true_count}")
print(f"Sent Request False: {sent_request_false_count}")
print(f"Total Withdrawals (True or False): {withdraw_total_count}")

# Define IST timezone
ist = pytz.timezone('Asia/Kolkata') # 'Asia/Kolkata' is the correct timezone name for IST

if sent_request_false_count == 0:
    if latest_sent_request_timestamp:
        # Add withdraw_connection_days_after_sending to the latest timestamp
        time_after_adding_days = latest_sent_request_timestamp + timedelta(days=withdraw_connection_days_after_sending)
        
        # Convert to IST timezone and format
        next_search_timestamp = time_after_adding_days.astimezone(ist).strftime("%d-%m-%Y %H:%M:%S")
        
        print(f"Next URL Search Timestamp: {next_search_timestamp}")

        # Get current system time in IST
        current_system_time_ist = datetime.now(ist)
        
        # Convert next_search_timestamp back to datetime object for comparison
        next_search_dt_ist = ist.localize(datetime.strptime(next_search_timestamp, "%d-%m-%Y %H:%M:%S"))

        if current_system_time_ist < next_search_dt_ist:
            remaining_time = next_search_dt_ist - current_system_time_ist
            # Format remaining time for better readability
            days = remaining_time.days
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            remaining_time_str = ""
            if days > 0:
                remaining_time_str += f"{days} days "
            if hours > 0:
                remaining_time_str += f"{hours} hours "
            if minutes > 0:
                remaining_time_str += f"{minutes} minutes "
            if seconds > 0 or not remaining_time_str: # Ensure some output even if less than a second
                remaining_time_str += f"{seconds} seconds"
            
            print(f"You need to wait for more {remaining_time_str.strip()}")
        else:
            print("You may search for next URL.")
    else:
        print("No 'sent_request_timestamp' found in scraped_connections.json.")
else:
    print("Wait for all request be sent.")
