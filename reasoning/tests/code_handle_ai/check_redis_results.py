import redis
import json

def check_redis_results():
    r = redis.Redis(host='172.16.12.98', port=6378, db=0)
    print("Checking some task results from Redis:")
    
    count = 0
    for key in r.scan_iter(match='celery-task-meta-*'):
        data = r.get(key)
        if data:
            try:
                parsed = json.loads(data)
                result = parsed.get("result")
                if result and isinstance(result, dict) and result.get("status") == "error":
                    print(f"Error task {key}: {result}")
                    count += 1
                elif result and isinstance(result, dict) and result.get("status") == "success":
                    pass # print(f"Success task {key}: {result.get('id')}")
            except:
                pass
    print(f"Total error results found: {count}")

if __name__ == "__main__":
    check_redis_results()
