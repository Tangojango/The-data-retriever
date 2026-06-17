# This version adds custom output path for the exported files and a function to calculate the Picarro timestamp
# h5 files for the dat viewer need time and timestamp (to be tested which is being used as x axis)

import os
import sys
import zipfile
import configparser
import pandas as pd
import h5py
from datetime import datetime, timedelta
import tempfile
import shutil
from tqdm import tqdm
#import pyarrow as pa
#import pyarrow.parquet as pq
import warnings

# Get the directory path of the script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Define the default configuration file as the full path
DEFAULT_CONFIG_FILE = os.path.join(script_dir, "data_retriever_settings.ini")
config_file = DEFAULT_CONFIG_FILE

def timestamp_Unix_to_Picarro(unix_timestamp_seconds):
    # Define the origin of the custom timestamp (midnight UTC, 1 January 1 AD) in Unix timestamp format.
    custom_timestamp_origin_seconds = -62135596800  # Seconds since Unix epoch to 1 January 1 AD

    # Calculate the custom timestamp in milliseconds.
    custom_timestamp_ms = int((unix_timestamp_seconds - custom_timestamp_origin_seconds) * 1000)

    return custom_timestamp_ms

def browse_zipped_archives(folder_path):
    file_list = []

    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".zip"):
                zip_path = os.path.join(root, file)
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_contents = zip_ref.namelist()
                    hdf5_files = [f for f in zip_contents if f.endswith(".h5")]
                    
                    for hdf5_file in hdf5_files:
                        file_path = os.path.join(zip_path, hdf5_file)
                        creation_time = zip_ref.getinfo(hdf5_file).date_time
                        creation_date = datetime(*creation_time[:6])
                        
                        file_info = {
                            "zip_path": zip_path,
                            "file_path": file_path,
                            "file_name": hdf5_file,
                            "creation_date": creation_date,
                            "hdf5_file": hdf5_file
                        }
                        file_list.append(file_info)

    if not file_list:
        print("No files found within the specified path.")
        exit()

    # Sort the file list by creation date in ascending order
    file_list = sorted(file_list, key=lambda x: x["creation_date"])

    # Filter the file list by date range if provided
    if date_from:
        file_list = [file for file in file_list if file["creation_date"] >= date_from]

    if date_to:
        file_list = [file for file in file_list if file["creation_date"] <= date_to]

    return file_list

def filter_files_by_dates(files_list, date_from, date_to):
    filtered_files_list = []
    
    for file_info in files_list:
        creation_date = file_info['creation_date']
        
        # Check if date_from is specified and filter based on it
        if date_from is not None and creation_date < date_from:
            continue
        
        # Check if date_to is specified and filter based on it
        if date_to is not None and creation_date > date_to:
            continue
        
        filtered_files_list.append(file_info)
    
    if not filtered_files_list:
        print("No files found within the specified date range.")
        exit()  

    return filtered_files_list


def get_columns_list_h5(columns_list, files_list, time_precision=2):
    first_time = True
    counter = 0
    return_df = pd.DataFrame()

    # Hushing the warnings since the h5 files are created with an old version of h5
    warnings.filterwarnings("ignore", category=pd.io.pytables.IncompatibilityWarning)

    for file_info in tqdm(files_list, desc='Processing files'):
        zip_path = file_info['zip_path']
        hdf5_file = file_info['hdf5_file']

        # Extract the HDF file to a temporary location
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = os.path.join(temp_dir, hdf5_file)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extract(hdf5_file, path=temp_dir)

            # Read the HDF file from the temporary location
            hdf_path = temp_path
             # Open the HDF file in iterator mode
            hdf_iterator = pd.read_hdf(hdf_path, key='results', iterator=True)

            # Iterate over the iterator and retrieve specific columns within each chunk
            chunk_dfs = []
            for chunk in hdf_iterator:
                if columns_list is None:
                    chunk_dfs.append(chunk)
                else:
                    chunk_df = chunk[columns_list]
                    chunk_dfs.append(chunk_df)
        
            # Concatenate the chunk DataFrames
            columns_df = pd.concat(chunk_dfs)

            if first_time:
                return_df = columns_df
                first_time = False
                max_counter = len(files_list)
            else:
                return_df = pd.concat([return_df, columns_df])



            # Print progress update
            #counter += 1
            #tqdm.write(f'Processing file {counter}/{len(files_list)}')
    # Reset the warning filter to its original state (optional)
    warnings.resetwarnings()
    # Parse 'time' column as a timestamp and set it as the index
    #return_df['time'] = pd.to_datetime(return_df['time'], unit='s').round(f'{time_precision}ms')
    #return_df.set_index('time', inplace=True)

    return return_df

def average_data_by_interval_old_time(data_df, sync_interval=None):
    if sync_interval is not None:
  
        # Print the length of the original data
        print("Original Data Length:", len(data_df))

        # Define the bin size based on sync_interval (assumed to be in milliseconds)
        bin_size = sync_interval

        # Create a new 'bin' column based on bin_size
        data_df['bin'] = (data_df['time'] / bin_size).astype(int) * bin_size

        # Print the number of unique bins
        print("Number of Unique Bins:", len(data_df['bin'].unique()))

        # Group the data by the 'bin' column and calculate the mean for all columns
        data_df = data_df.groupby('bin').mean().reset_index()

        # Print the length of the averaged data
        print("Averaged Data Length:", len(data_df))
        
        # Replace the averaged time column with the bin values, keeping the float formatting
        data_df['time'] = (data_df['bin'] * 1000).astype('float64') / 1000



        # Replace the 'timestamp' column with recalculated timestamps
        if 'timestamp' in data_df.columns:
            data_df['timestamp'] = ((data_df['bin'] - -62135596800) * 1000).astype('uint64')

        hundred_year_seconds = 365 * 24 * 60 * 60 * 100 * 1000 # Number of seconds in one hundred years (miliseconds now)
        data_df['timestamp'] += hundred_year_seconds            
        
    return data_df

def average_data_by_interval(data_df, sync_interval=None):
    if sync_interval is not None:
  
        # Print the length of the original data
        print("Original Data Length:", len(data_df))

        # Define the bin size based on sync_interval (assumed to be in milliseconds)
        bin_size = sync_interval

        # Create a new 'bin' column based on bin_size, using the 'timestamp' column
        data_df['bin'] = (data_df['timestamp'] / bin_size).astype('uint64') * bin_size

        # Print the number of unique bins
        #print("Number of Unique Bins:", len(data_df['bin'].unique()))

        # Group the data by the 'bin' column and calculate the mean for all columns
        data_df = data_df.groupby('bin').mean().reset_index()

        # Print the length of the averaged data
        print("Averaged Data Length:", len(data_df))
        
        # Replace the 'timestamp' column with the bin values (integer format)
        data_df['timestamp'] = (data_df['bin'])

        # Replace the 'time' column with recalculated timestamps (float format)
        if 'time' in data_df.columns:
            data_df['time'] = ((data_df['bin'] + -62135596800)).astype('float64') / 1000000 
        
    return data_df







# Check if the configuration .ini file path is provided as a command-line argument
#if len(sys.argv) < 2:
#    print("No configuration .ini file path provided. Using the default file: " + DEFAULT_CONFIG_FILE)
#    config_file = DEFAULT_CONFIG_FILE
#else:
#    config_file = sys.argv[1]

# Create a ConfigParser object and read the .ini file
config = configparser.ConfigParser()
config.read(config_file)

# Retrieve the necessary arguments from the .ini file
input_folder_path = config.get('Settings', 'input_folder_path')
output_folder_path = config.get('Settings', 'output_folder_path')
output_filename = str(config.get('Settings', 'output_filename'))
zipped = config.getboolean('Settings', 'zipped')
extension = config.get('Settings', 'extension')
columns_string = config.get('Settings', 'columns')

# Check if all columns should be selected
if columns_string.lower() in ['all', '*']:
    columns = None  # Indicates selecting all columns
else:
    columns = columns_string.split(', ') 

date_from_str = config.get('Settings', 'date_from')
date_from = datetime.strptime(date_from_str, "%Y-%m-%d %H:%M:%S") if date_from_str else None

date_to_str = config.get('Settings', 'date_to')
date_to = datetime.strptime(date_to_str, "%Y-%m-%d %H:%M:%S") if date_to_str else None

sync_interval = config.get('Settings', 'sync_interval')


export_parquet = config.getboolean('Settings', 'export_parquet')
export_csv = config.getboolean('Settings', 'export_csv')
export_hdf5 = config.getboolean('Settings', 'export_hdf5')

if sync_interval is not None:
    try:
        sync_interval = int(sync_interval)
        if sync_interval <= 0:
            sync_interval = None  # Set to None if not a positive integer
    except ValueError:
        sync_interval = None  # Set to None if not a valid integer


# --------------------------------------- Here we start using all the functions

pd.set_option('display.max_columns', None)
# Get the list of all the files within the path
files_list = browse_zipped_archives(input_folder_path)

# Filter the list of the files with the time
files_list = filter_files_by_dates(files_list, date_from, date_to)

#print(len(files_list))
results_df = get_columns_list_h5(columns, files_list)
results_df = average_data_by_interval(results_df, sync_interval)
#print(results_df)

# Get the minimum and maximum values from the time column
min_time = results_df['time'].min()
max_time = results_df['time'].max()

# Convert the min and max time values to datetime format with minutes precision
start_date = pd.to_datetime(min_time, unit='s').strftime("%Y%m%d%H%M")
end_date = pd.to_datetime(max_time, unit='s').strftime("%Y%m%d%H%M")

# Append the dates to the filename when you need to save the file
output_filename = f"{output_filename}_{start_date}-{end_date}_Sync{sync_interval}"
output_file = output_folder_path + '/' + output_filename


# Export to HDF5 if specified in settings
if export_hdf5:
    hdf5_output_file = output_file + '.h5'
    #hdf5_output_file = os.path.join(folder_path, hdf5_output_file)

    # Convert the DataFrame to a structured NumPy array
    results_array = results_df.to_records(index=False)  # Use index=False to exclude the index
     
    # Create an HDF5 file
    with h5py.File(hdf5_output_file, 'w') as hf:
        # Create a table dataset named 'results' and store the data
        hf.create_dataset('results', data=results_array)
        
    print(f"Exported to HDF5: {hdf5_output_file}")

#print(f"Columns: {columns}, Date From: {date_from}, Date To: {date_to}, Sync Interval: {sync_interval}s)")
#print(f"Number of Rows: {results_df.shape[0]}")

