import redis

def check_redis():
    r = redis.Redis(host='172.16.12.98', port=6378, db=0)
    try:
        # Check queue length
        length = r.llen('celery')
        print(f"Tasks in 'celery' queue: {length}")
        
        # Unacknowledged tasks?
        print("Keys in Redis:")
        for key in r.scan_iter():
            print(f"- {key}")
    except Exception as e:
        print(f"Error connecting to Redis: {e}")

if __name__ == "__main__":
    check_redis()
