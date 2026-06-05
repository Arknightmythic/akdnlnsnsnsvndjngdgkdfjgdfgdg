import redis
import json

r = redis.Redis(host='172.16.12.98', port=6378, db=0)
errors = {}

for key in r.scan_iter(match='celery-task-meta-*'):
    data = r.get(key)
    if data:
        try:
            p = json.loads(data)
            if p.get('status') == 'FAILURE':
                result = p.get('result', {})
                if isinstance(result, dict):
                    exc_type = result.get('exc_type', 'unknown')
                    msg = str(result.get('exc_message', ''))
                else:
                    exc_type = str(type(result).__name__)
                    msg = str(result)
                if exc_type not in errors:
                    errors[exc_type] = {'count': 0, 'msg': msg}
                errors[exc_type]['count'] += 1
        except Exception as e:
            pass

print("Error types in Redis:")
for k, v in errors.items():
    print(f"  [{v['count']}x] {k}: {v['msg']}")
