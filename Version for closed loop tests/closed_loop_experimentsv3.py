import h5py
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker


#region Define the folder path
folder_path = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/'

# Read the CSV file into a DataFrame
csv_file_path = folder_path + 'experiments.csv'
experiments_df = pd.read_csv(csv_file_path)

# Ensure datetime conversion for start and end columns
experiments_df['start'] = pd.to_datetime(experiments_df['start'])
experiments_df['end'] = pd.to_datetime(experiments_df['end'])

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


def process_experiments(data, experiments_df):
    """Process experiments to calculate slopes for the second 5-minute interval."""
    results = []
    for index, experiment in experiments_df.iterrows():
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

       # Calculate slopes using least squares method
        slopes = {}
        slope_lines = {}
        for col in ['CO2', 'CH4', 'N2O', 'ALI_PRESSURE', 'ALI_FLOW']:
            x = second_5_min_data['temp_time'].astype(int)
            y = second_5_min_data[col]
            slope, intercept, line_values = calculate_least_squares_line(x, y)
            slopes[col] = slope
            slope_lines[col + '_line'] = line_values

        # Append the results
        result = {
            "title": title,
            "description": description,
            "start_time": start,
            "end_time": end,
            **slopes,
            **slope_lines  # Add slope lines to the results
        }

        results.append(result)
    
    return results



def write_results_to_csv(results, output_file):
    df = pd.DataFrame(results)
    df.to_csv(output_file, index=False)
    print(f"Results written to {output_file}")



from reportlab.graphics.charts.lineplots import ScatterPlot, LinePlot
from reportlab.lib import colors


from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate
from reportlab.graphics.shapes import Drawing, String 

import matplotlib.pyplot as plt
import numpy as np

def generate_pdf_report(results, data):
    # Create a PDF document
    doc = SimpleDocTemplate("/path/to/experiment_report.pdf", pagesize=letter)
    Story = []

    # Add scatter plot for each experiment
    for result in results:
        # Create a Drawing to hold the scatter plot
        drawing = Drawing(400, 200)

        # Extract experiment start and end times
        start_time = result["start_time"]
        end_time = result["end_time"]

        # Filter data for the current experiment
        exp_data = data[(data['test_nr'] == 1)]

        # Plot scatter plot
        plt.scatter(exp_data['temp_time'], exp_data['CO2'], label='CO2 (Noisy data)')
        
        # Add light grey background for the first five minutes
        plt.axvspan(start_time, start_time + timedelta(minutes=5), color='lightgrey', alpha=0.5)
        
        # Add labels and legend
        plt.xlabel('Time')
        plt.ylabel('CO2')
        plt.legend()
        plt.title('Scatter plot for CO2')

        # Show the plot
        plt.show()

        # Add the Drawing to the Story
        Story.append(drawing)

    # Build the PDF document
    doc.build(Story)







# Open the large HDF5 file
with h5py.File(f"{folder_path}/closed_loop_tests_202405141938-202405231528_Sync2000.h5", 'r+') as f:
    # Assuming the data is stored in a dataset called 'results'
    data = pd.DataFrame(f['results'][:])

    # Create a temporary column for processing with datetime conversion
    data['temp_time'] = data['timestamp'].apply(timestamp_to_datetime)
    
    # Initialize the 'test_nr' column with zeros
    data['test_nr'] = 0

    # Iterate over the experiments and assign the test numbers
    for i, row in experiments_df.iterrows():
        start = row['start']
        end = row['end']
        mask = (data['temp_time'] >= start) & (data['temp_time'] <= end)
        data.loc[mask, 'test_nr'] = i + 1  # Adding 1 to maintain the original enumeration starting at 1

print(data.head())
  
results = process_experiments(data, experiments_df)

# Print results for debugging purposes
for result in results:
    print(result)

write_results_to_csv(results, '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments_results.csv')

# Filter out rows where test_nr is 0 (i.e., not part of any experiment)
data = data[data['test_nr'] != 0]

generate_pdf_report(results,data)

data.drop(columns=['temp_time'], inplace=True)

output_filename = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments_data_debug8.h5'

with h5py.File(output_filename, 'w') as out_f:
    out_f.create_dataset('data', data=data.to_records(index=False))

print(f"Data processing complete. New file '{output_filename}' created.")


