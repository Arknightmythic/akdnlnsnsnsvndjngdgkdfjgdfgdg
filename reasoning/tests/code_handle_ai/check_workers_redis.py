import redis, json

r = redis.Redis(host='172.16.12.98', port=6378, db=0)

# Check active workers via heartbeat
print("=== Celery Worker Nodes yang Aktif di Redis ===")
workers = []
for key in r.scan_iter(match='_kombu.binding.*'):
    print(f"Binding key: {key}")

# Check celery control queue (heartbeat)
print("\n=== Keys terkait Worker ===")
for key in r.scan_iter():
    key_str = key.decode('utf-8', errors='replace')
    if 'worker' in key_str.lower() or 'heartbeat' in key_str.lower() or 'uniq' in key_str.lower():
        print(f"  {key_str}")
