import time
from functools import wraps

def record_time(func):
    """
    A decorator that prints the execution time of a function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        
        result = func(*args, **kwargs)
        
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        
        print(f"[TIMER] '{func.__name__}' took {execution_time:.6f} seconds to run.")
        return result
    return wrapper