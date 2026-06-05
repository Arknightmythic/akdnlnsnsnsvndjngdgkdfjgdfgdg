import redis
import json

def check_redis_results():
    r = redis.Redis(host='172.16.12.98', port=6378, db=0)
    
    count_success = 0
    count_error = 0
    count_other = 0
    
    for key in r.scan_iter(match='celery-task-meta-*'):
        data = r.get(key)
        if data:
            try:
                parsed = json.loads(data)
                status = parsed.get("status")
                result = parsed.get("result")
                if status == "SUCCESS":
                    if isinstance(result, dict):
                        if result.get("status") == "success":
                            count_success += 1
                        elif result.get("status") == "error":
                            count_error += 1
                        else:
                            count_other += 1
                    else:
                        count_other += 1
                elif status == "FAILURE":
                    count_error += 1
            except:
                pass
                
    print(f"Success tasks: {count_success}")
    print(f"Error tasks: {count_error}")
    print(f"Other tasks: {count_other}")

if __name__ == "__main__":
    check_redis_results()
