import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime, timedelta
import numpy as np

def timestamp_to_datetime_with_timedelta(timestamp_ms):
    # Convert milliseconds to seconds
    timestamp_seconds = timestamp_ms / 1000.0
    
    # Assuming the epoch starts at 1-1-1
    epoch = datetime(1, 1, 1)
    
    # ----- This offset is a surprise, still need to solve why its there!!!
    # Add the timestamp to the epoch and subtract two hours
    result_datetime = epoch + timedelta(seconds=timestamp_seconds) + timedelta(hours=2)
    
    return result_datetime

def read_data(h5_file, csv_file):
    """Read the HDF5 and CSV files."""
    data = pd.read_hdf(h5_file, 'results')
    experiments_df = pd.read_csv(csv_file)
    return data, experiments_df

def generate_pdf_report(data, experiments_df, output_pdf):
    data['temp_time'] = data['timestamp'].apply(timestamp_to_datetime_with_timedelta)

    with PdfPages(output_pdf) as pdf:
        for index, experiment in experiments_df.iterrows():
            start_time = pd.to_datetime(experiment["start"])
            end_time = pd.to_datetime(experiment["end"])
            title = experiment["title"]
            description = experiment["description"]

            # Filter data for the current experiment
            exp_data = data[(data['temp_time'] >= start_time) & (data['temp_time'] <= end_time)]

            # Determine the end of the first 5 minutes
            first_5_min_end = start_time + pd.Timedelta(minutes=5)

            # Data after the first 5 minutes
            post_5_min_data = exp_data[exp_data['temp_time'] > first_5_min_end]

            if len(post_5_min_data) > 1:  # Check if there's enough data to calculate a trend line
                # Prepare data for linear regression
                x = (post_5_min_data['temp_time'] - post_5_min_data['temp_time'].min()).dt.total_seconds().values.reshape(-1, 1)
                y = post_5_min_data['CO2'].values

                # Perform linear regression
                A = np.vstack([x.flatten(), np.ones(len(x))]).T
                m, c = np.linalg.lstsq(A, y, rcond=None)[0]

                # Calculate trend line
                trend_line = m * x + c

            # Plot scatter plot for CO2 values
            plt.figure(figsize=(10, 6))
            plt.scatter(exp_data['temp_time'], exp_data['CO2'], label='CO2', color='blue', s=10)

            # Highlight the first 5 minutes in light grey
            first_5_min_data = exp_data[(exp_data['temp_time'] >= start_time) & (exp_data['temp_time'] <= first_5_min_end)]
            plt.scatter(first_5_min_data['temp_time'], first_5_min_data['CO2'], color='lightgrey', s=10)

            if len(post_5_min_data) > 1:
                # Plot the trend line
                plt.plot(post_5_min_data['temp_time'], trend_line, color='red', label=f'Trend line (slope={m:.2f})')

            # Add title and labels
            plt.title(f"{title}\n{description}")
            plt.xlabel("Time")
            plt.ylabel("CO2")
            plt.legend()

            # Save the plot to the PDF
            pdf.savefig()
            plt.close()


if __name__ == "__main__":
    # File paths
    h5_file = "/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/closed_loop_tests_202405141938-202405231528_Sync2000.h5"
    csv_file = "/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiments.csv"
    output_pdf = "/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/experiment_report.pdf"

    # Read data
    data, experiments_df = read_data(h5_file, csv_file)



    # Generate PDF report
    generate_pdf_report(data, experiments_df, output_pdf)
