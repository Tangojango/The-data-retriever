import h5py
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np

#region Define the folder path
folder_path = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/'

# Read the CSV file into a DataFrame
csv_file_path = folder_path + 'experiments.csv'
experiments_df = pd.read_csv(csv_file_path)

print(experiments_df)

#endregion

def timestamp_to_datetime(timestamp_ms):
    # Convert milliseconds to seconds
    timestamp_seconds = timestamp_ms / 1000.0
    
    # Assuming the epoch starts at 1-1-1
    epoch = datetime(1, 1, 1)
    
    # ----- This offset is a surprise, still need to solve why its there!!!
    # Add the timestamp to the epoch and subtract two hours
    result_datetime = epoch + timedelta(seconds=timestamp_seconds) + timedelta(hours=2)
    
    return result_datetime

def calculate_least_squares_line(x, y):
    """
    Calculate the least squares regression line for the given data.
    
    Parameters:
    x (array-like): Independent variable values (time).
    y (array-like): Dependent variable values (data).
    
    Returns:
    slope (float): Slope of the regression line.
    intercept (float): Intercept of the regression line.
    line_values (array-like): y-values of the regression line for plotting.

    Example usage:
    x = np.arange(0, 300, 2)  # e.g., 5 minutes of data with a 2-second interval
    y = np.random.normal(size=len(x))  # some noisy data
    slope, intercept, line_values = calculate_least_squares_line(x, y)
    """
    # Ensure x is in the right format (e.g., seconds or minutes)
    x = np.array(x)
    y = np.array(y)
    
    # Calculate the slope (m) and intercept (c) using numpy's lstsq method
    A = np.vstack([x, np.ones(len(x))]).T
    m, c = np.linalg.lstsq(A, y, rcond=None)[0]
    
    # Generate the line values for plotting
    line_values = m * x + c
    
    return m, c, line_values

def generate_experiment_graphs(data, experiments, columns_to_plot):
    # Convert string time pairs to datetime objects for easier comparison
    experiments = [(datetime.strptime(start, "%Y-%m-%d %H:%M:%S"), datetime.strptime(end, "%Y-%m-%d %H:%M:%S"))
                   for start, end in experiments]

    # Create a temporary column for processing with datetime conversion
    data['temp_time'] = data['timestamp'].apply(timestamp_to_datetime)

    # Iterate over the experiments
    for i, (start, end) in enumerate(experiments, 1):
        exp_data = data[(data['temp_time'] >= start) & (data['temp_time'] <= end)]
        
        if exp_data.empty:
            continue
        
        # Iterate over the columns to plot
        for col in columns_to_plot:
            # Calculate the least squares line for the current column
            x = (exp_data['temp_time'] - exp_data['temp_time'].min()).dt.total_seconds().values
            y = exp_data[col].values
            m, c = calculate_least_squares_line(x, y)
            
            # Plotting the data and the least squares line
            plt.figure(figsize=(10, 6))
            plt.plot(exp_data['temp_time'], exp_data[col], label=f'{col} Values', color='b')
            plt.plot(exp_data['temp_time'], m * x + c, label='Least Squares Line', color='r', linestyle='--')
            plt.xlabel('Time')
            plt.ylabel(f'{col} Value')
            plt.title(f'Experiment {i} - {col}')
            plt.legend()
            plt.grid(True)
            plt.show()

def process_experiments(data, experiments):
    """Process experiments to calculate slopes for the second 5-minute interval."""
    results = []
    for experiment in experiments:
        title = experiment["title"]
        description = experiment["description"]
        start = experiment["start"]
        end = experiment["end"]
        
        # Filter data for the given experiment
        mask = (data['temp_time'] >= start) & (data['temp_time'] <= end)
        exp_data = data[mask]
        
        # Calculate the start and end time for the second 5 minutes
        second_5_min_start = start + timedelta(minutes=5)
        second_5_min_end = second_5_min_start + timedelta(minutes=5)
        
        # Filter data for the second 5 minutes
        second_5_min_data = exp_data[(exp_data['temp_time'] >= second_5_min_start) & (exp_data['temp_time'] <= second_5_min_end)]

        # Calculate slopes for each required column
        slopes = {}
        for col in ['CO2', 'CH4', 'N2O', 'ALI_PRESSURE', 'ALI_FLOW']:
            slopes[col] = calculate_slope(second_5_min_data['temp_time'].astype(int), second_5_min_data[col])
        
        # Append the results
        result = {
            "title": title,
            "description": description,
            "start_time": start,
            "end_time": end,
            **slopes
        }
        results.append(result)
    
    return results

def write_results_to_csv(results, output_file):
    df = pd.DataFrame(results)
    df.to_csv(output_file, index=False)
    print(f"Results written to {output_file}")




# Convert string time pairs to datetime objects for easier comparison
for experiment in experiments:
    experiment['start'] = datetime.strptime(experiment['start'], "%Y-%m-%d %H:%M:%S")
    experiment['end'] = datetime.strptime(experiment['end'], "%Y-%m-%d %H:%M:%S")

# Open the large HDF5 file
with h5py.File('/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/closed_loop_tests_202405141938-202405231528_Sync2000.h5', 'r+') as f:
    # Assuming the data is stored in a dataset called 'data'
    data = pd.DataFrame(f['results'][:])

    # Create a temporary column for processing with datetime conversion
    data['temp_time'] = data['timestamp'].apply(timestamp_to_datetime)
    
    print(data.head())

    # Initialize the 'test_nr' column with zeros
    data['test_nr'] = 0

    # Iterate over the experiments and assign the test numbers
    for i, experiment in enumerate(experiments, 1):
        start = experiment['start']
        end = experiment['end']
        title = experiment['title']
        description = experiment['description']
        
        mask = (data['temp_time'] >= start) & (data['temp_time'] <= end)
        data.loc[mask, 'test_nr'] = i

        # For debugging: print the length of each mask and corresponding times
        print(f"Experiment {i}: {title}")
        print(f"Description: {description}")
        print(f"Start time: {start}, End time: {end}")
        print(f"Number of rows: {mask.sum()}")


    # Drop the temporary column before saving
    data['timestamp_int'] = data['temp_time'].astype('int64') // 10**6  # convert to milliseconds
    
  
    results = process_experiments(data, experiments)

    # Print results for debugging purposes
    for result in results:
        print(result)
    
    write_results_to_csv(results, '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments_results.csv')

    data.drop(columns=['temp_time'], inplace=True)

    # Filter out rows where test_nr is 0 (i.e., not part of any experiment)
    data = data[data['test_nr'] != 0]

output_filename = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments_data_debug7.h5'

with h5py.File(output_filename, 'w') as out_f:
    out_f.create_dataset('data', data=data.to_records(index=False))

print(f"Data processing complete. New file '{output_filename}' created.")

