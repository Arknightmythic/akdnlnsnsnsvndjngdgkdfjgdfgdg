import redis

def purge():
    r = redis.Redis(host='172.16.12.98', port=6378, db=0)
    print("Mencari data cache task (celery-task-meta-*) di Redis...")
    
    count = 0
    # Scan dan hapus semua metadata task celery
    for key in r.scan_iter(match='celery-task-meta-*'):
        r.delete(key)
        count += 1
        
    print(f"[OK] Berhasil menghapus {count} task log/results dari Redis!")
    
    # Kosongkan juga queue yang mungkin menggantung
    q_len = r.llen('celery')
    if q_len > 0:
        r.delete('celery')
        print(f"[OK] Berhasil menghapus {q_len} task yang menggantung di antrean Celery!")
    else:
        print("[OK] Antrean utama Celery sudah bersih.")

if __name__ == "__main__":
    purge()
