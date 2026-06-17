import csv

# Define the folder path
folder_path = '/Users/jwozniak/Library/CloudStorage/OneDrive-Picarro,Inc/PROJECTS/CLOSED LOOP TESTS/'

# Define the experiments data
experiments = [
    {
        "start": "2024-05-18 21:26:24",
        "end": "2024-05-18 21:54:30",
        "title": "Experiment 1",
        "description": "Description for experiment 1"
    },
    {
        "start": "2024-05-18 21:56:00",
        "end": "2024-05-18 22:19:00",
        "title": "Experiment 2",
        "description": "Description for experiment 2"
    },
    {
        "start": "2024-05-18 22:54:00",
        "end": "2024-05-18 23:18:00",
        "title": "Experiment 3",
        "description": "Description for experiment 3"
    },
    {
        "start": "2024-05-18 23:36:00",
        "end": "2024-05-18 23:54:30",
        "title": "Experiment 4",
        "description": "Description for experiment 4"
    },
    {
        "start": "2024-05-20 18:54:30",
        "end": "2024-05-20 19:15:00",
        "title": "Experiment 5",
        "description": "Description for experiment 5"
    },
    {
        "start": "2024-05-21 22:55:00",
        "end": "2024-05-21 23:13:00",
        "title": "Experiment 6",
        "description": "Description for experiment 6"
    },
    {
        "start": "2024-05-21 23:23:00",
        "end": "2024-05-21 23:35:30",
        "title": "Experiment 7",
        "description": "Description for experiment 7"
    },
    {
        "start": "2024-05-21 23:40:00",
        "end": "2024-05-21 23:58:00",
        "title": "Experiment 8",
        "description": "Description for experiment 8"
    },
    {
        "start": "2024-05-22 00:01:50",
        "end": "2024-05-22 00:07:20",
        "title": "Experiment 9",
        "description": "Description for experiment 9"
    },
    {
        "start": "2024-05-22 00:18:00",
        "end": "2024-05-22 00:32:00",
        "title": "Experiment 10",
        "description": "Description for experiment 10"
    },
    {
        "start": "2024-05-22 00:40:30",
        "end": "2024-05-22 00:52:30",
        "title": "Experiment 11",
        "description": "Description for experiment 11"
    },
    {
        "start": "2024-05-22 00:56:00",
        "end": "2024-05-22 02:30:00",
        "title": "Experiment 12",
        "description": "Description for experiment 12"
    },
]

# Write the experiments to a CSV file
csv_file_path = folder_path + 'experiments.csv'
with open(csv_file_path, 'w', newline='') as csvfile:
    fieldnames = ['start', 'end', 'title', 'description']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

    writer.writeheader()
    for exp in experiments:
        writer.writerow(exp)

print(f"Data written to {csv_file_path}")
