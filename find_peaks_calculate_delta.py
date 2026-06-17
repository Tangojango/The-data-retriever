import pandas as pd
import numpy as np
import os
import matplotlib.pyplot as plt


folder_path = "/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/A NEW DATA FOLDER/Automate FX/Automate V2/Test runs April 2023"
file_name = os.path.join(folder_path, "trombona.parquet")

deltaSlope = 1
deltaOffset = 0


df = pd.read_parquet(file_name)
threshold = 70

# Plot the 12CO2 values
#plt.plot(df['12CO2'])
#plt.xlabel('Time')
#plt.ylabel('12CO2')
#plt.title('12CO2 values over time')
#plt.show()


df = pd.read_parquet(file_name)
threshold = 70


def plot_12CO2_with_threshold(df, start_indices, end_indices):
    plt.plot(df.index, df['12CO2'], color='blue')

    for start_idx, end_idx in zip(start_indices, end_indices):
        plt.axvspan(df.index[start_idx], df.index[end_idx], color='red', alpha=0.3)

    plt.xlabel('Time')
    plt.ylabel('12CO2')
    plt.title('12CO2 values over time')

    plt.show()


# Example usage:
df = pd.read_parquet(file_name)
threshold = 70

# Calculate the start and end indices
start_indices = np.where((df['12CO2'].shift(1) < threshold) & (df['12CO2'] >= threshold))[0]
end_indices = np.where((df['12CO2'].shift(1) >= threshold) & (df['12CO2'] < threshold))[0]

# Check if the first or last value is above the threshold
if df['12CO2'].iloc[0] >= threshold:
    start_indices = np.insert(start_indices, 0, 0)
if df['12CO2'].iloc[-1] >= threshold:
    end_indices = np.append(end_indices, len(df)-1)


peak_areas_12CO2 = []
peak_areas_13CO2 = []
peak_start_times = []
peak_end_times = []

for start_idx, end_idx in zip(start_indices, end_indices):
    # Calculate the area under the peak for 12CO2 using the trapezoidal rule
    area_12CO2 = np.trapz(df['12CO2'][start_idx:end_idx + 1], df.index[start_idx:end_idx + 1])
    area_seconds_12CO2 = (area_12CO2.astype('timedelta64[ns]').view('int64') / int(1e9)).item()  # Convert timedelta to seconds
    peak_areas_12CO2.append(area_seconds_12CO2)

    # Calculate the area under the peak for 13CO2 using the trapezoidal rule
    area_13CO2 = np.trapz(df['13CO2'][start_idx:end_idx + 1], df.index[start_idx:end_idx + 1])
    area_seconds_13CO2 = (area_13CO2.astype('timedelta64[ns]').view('int64') / int(1e9)).item()  # Convert timedelta to seconds
    peak_areas_13CO2.append(area_seconds_13CO2)

    # Store the starting and ending times of the peak
    start_time = df.index[start_idx]
    end_time = df.index[end_idx]
    peak_start_times.append(start_time)
    peak_end_times.append(end_time)

area_df = pd.DataFrame({
    'Peak Start Index': start_indices,
    'Peak End Index': end_indices,
    'Area 12CO2': peak_areas_12CO2,
    'Area 13CO2': peak_areas_13CO2,
    'Start Time': peak_start_times,
    'End Time': peak_end_times
})

# Calculate delta13C
area_df['Delta 13C'] = (((area_df['Area 13CO2'] / area_df['Area 12CO2']) - 0.0111802) / 0.0111802) * 1000

# Apply slope and offset
area_df['Delta 13C'] = deltaOffset + area_df['Delta 13C'] * deltaSlope



#print(area_df)

# Call the function to plot the graph
plot_12CO2_with_threshold(df, start_indices, end_indices)
