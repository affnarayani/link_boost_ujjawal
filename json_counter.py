import json

with open('scraped_connections.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

total_count = len(data)
sent_request_true_count = 0
sent_request_false_count = 0
withdraw_total_count = 0

for item in data:
    if item.get('sent_request') is True:
        sent_request_true_count += 1
    elif item.get('sent_request') is False:
        sent_request_false_count += 1
    
    if 'withdraw' in item:
        withdraw_total_count += 1

print(f"Total number of connections: {total_count}")
print(f"Sent Request True: {sent_request_true_count}")
print(f"Sent Request False: {sent_request_false_count}")
print(f"Total Withdrawals (True or False): {withdraw_total_count}")
