from datetime import datetime, timedelta

def timestamp_to_datetime(timestamp_ms):
    # Convert milliseconds to seconds
    timestamp_seconds = timestamp_ms / 1000.0
    
    # Assuming the epoch starts at 1-1-1
    epoch = datetime(1, 1, 1)
    
    # Add the timestamp to the epoch
    result_datetime = epoch + timedelta(seconds=timestamp_seconds)
    
    return result_datetime

# Example usage:
timestamp_ms = 63851312318000
result_datetime = timestamp_to_datetime(timestamp_ms)
print(result_datetime)
