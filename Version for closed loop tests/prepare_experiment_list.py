import h5py
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt


# Define the list of time pairs for each experiment
experiments = [
    ("2024-05-18 21:26:24", "2024-05-18 21:54:30"),
    ("2024-05-18 21:56:00", "2024-05-18 22:19:00"),
    ("2024-05-18 22:54:00", "2024-05-18 23:18:00"),
    ("2024-05-18 23:36:00", "2024-05-18 23:54:30"),
    ("2024-05-20 18:54:30", "2024-05-20 19:15:00"),
    ("2024-05-21 22:55:00", "2024-05-21 23:13:00"),
    ("2024-05-21 23:23:00", "2024-05-21 23:35:30"),
    ("2024-05-21 23:40:00", "2024-05-21 23:58:00"),
    ("2024-05-22 00:01:50", "2024-05-22 00:07:20"),
    ("2024-05-22 00:18:00", "2024-05-22 00:32:00"),
    ("2024-05-22 00:40:30", "2024-05-22 00:52:30"),
    ("2024-05-22 00:56:00", "2024-05-22 02:30:00"),
    # Add more time pairs as needed
]

def timestamp_to_datetime(timestamp_ms):
    # Convert milliseconds to seconds
    timestamp_seconds = timestamp_ms / 1000.0
    
    # Assuming the epoch starts at 1-1-1
    epoch = datetime(1, 1, 1)
    
    # ----- This offset is a surprise, still need to solve why its there!!!
    # Add the timestamp to the epoch and subtract two hours
    result_datetime = epoch + timedelta(seconds=timestamp_seconds) + timedelta(hours=2)
    
    return result_datetime


# Convert string time pairs to datetime objects for easier comparison
experiments = [(datetime.strptime(start, "%Y-%m-%d %H:%M:%S"), datetime.strptime(end, "%Y-%m-%d %H:%M:%S")) for start, end in experiments]

# Open the large HDF5 file
with h5py.File('/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/closed_loop_tests_202405141938-202405231528_Sync2000.h5', 'r+') as f:
    # Assuming the data is stored in a dataset called 'data'
    data = pd.DataFrame(f['results'][:])

    # Create a temporary column for processing with datetime conversion
    data['temp_time'] = data['timestamp'].apply(timestamp_to_datetime)
    

    print(data.head())

    # Initialize the 'test_nr' column with zeros
    data['test_nr'] = 0

    # Iterate over the experiments and generate a graph for each
    for i, (start, end) in enumerate(experiments, 1):
        mask = (data['temp_time'] >= start) & (data['temp_time'] <= end)
        
        # Filter data for the current experiment
        experiment_data = data[mask]
        mask_length = len(data[mask])
        data.loc[mask, 'test_nr'] = i
        print(f"Experiment {i}: Start Time: {start}, End Time: {end}, Mask Length: {mask_length}")

        # Plot CO2 values against time
        #plt.figure(figsize=(10, 6))
        #plt.plot(experiment_data['temp_time'], experiment_data['ALI_FLOW'], label=f'Experiment {i}')
        #plt.xlabel('Time')
        #plt.ylabel('CO2 Value')
        #plt.title(f'Experiment {i} - CO2 vs. Time')
        #plt.xticks(rotation=45)
        #plt.legend()
        #plt.grid(True)
        #plt.tight_layout()
        #plt.show()

    # Iterate over the experiments and assign the test numbers
    #for i, (start, end) in enumerate(experiments, 1):
    #    mask = (data['temp_time'] >= start) & (data['temp_time'] <= end)
    #    mask_length = len(data[mask])
    #    print(f"Experiment {i}: Start Time: {start}, End Time: {end}, Mask Length: {mask_length}")
    #   data.loc[mask, 'test_nr'] = i

    # Drop the temporary column before saving
    data['timestamp_int'] = data['temp_time'].astype('int64') // 10**6  # convert to milliseconds
    data.drop(columns=['temp_time'], inplace=True)

    # Filter out rows where test_nr is 0 (i.e., not part of any experiment)
    #data = data[data['test_nr'] != 0]

output_filename = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments_data_debug5.h5'

with h5py.File(output_filename, 'w') as out_f:
    out_f.create_dataset('data', data=data.to_records(index=False))

print(f"Data processing complete. New file '{output_filename}' created.")