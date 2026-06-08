import redis
import json

def get_error():
    r = redis.Redis(host='172.16.12.98', port=6378, db=0)
    for key in r.scan_iter(match='celery-task-meta-*'):
        data = r.get(key)
        if data:
            try:
                parsed = json.loads(data)
                if parsed.get("status") == "FAILURE":
                    print(f"Task Failed: {parsed.get('task_id')}")
                    print(f"Exception: {parsed.get('result')}")
                    print(f"Traceback: {parsed.get('traceback')}")
                    break
            except:
                pass

if __name__ == "__main__":
    get_error()
