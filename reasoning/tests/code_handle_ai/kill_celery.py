import psutil
import os

def kill_celery_workers():
    killed = 0
    my_pid = os.getpid()
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['pid'] == my_pid:
                continue
            
            cmdline = proc.info.get('cmdline') or []
            # Jika ini adalah proses python dan ada argumen 'celery' di dalamnya
            if proc.info['name'] and 'python' in proc.info['name'].lower():
                if any('celery' in arg.lower() for arg in cmdline):
                    print(f"Menghentikan Worker nyangkut PID {proc.info['pid']}: {' '.join(cmdline)}")
                    proc.kill()
                    killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if killed > 0:
        print(f"Berhasil menghentikan {killed} proses Celery zombie.")
    else:
        print("Tidak ditemukan proses Celery yang menyala di background.")

if __name__ == "__main__":
    kill_celery_workers()
