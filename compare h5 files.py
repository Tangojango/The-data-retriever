import h5py

def compare_h5_files(file1, file2):
    differences = []

    # Open both H5 files
    with h5py.File(file1, 'r') as h5_file1, h5py.File(file2, 'r') as h5_file2:
        # Compare dataset names
        names1 = set(h5_file1.keys())
        names2 = set(h5_file2.keys())

        if names1 != names2:
            differences.append("Dataset names differ")

        # Compare dataset shapes and types
        for name in names1.intersection(names2):
            dataset1 = h5_file1[name]
            dataset2 = h5_file2[name]

            if dataset1.shape != dataset2.shape or dataset1.dtype != dataset2.dtype:
                differences.append(f"Dataset {name}: Shape or data type differs")

            # Compare dataset values (you can set a threshold here)
            threshold = 1e-6
            diff_values = (dataset1[:] - dataset2[:])
            if (diff_values > threshold).any():
                differences.append(f"Dataset {name}: Values differ")

    return differences

# Usage
differences = compare_h5_files("/Users/jwozniak/Downloads/EDF_LOANER/07/18/LBDS2003-20230718-034247Z-DataLog_Private.h5", "/Users/jwozniak/Downloads/EDF_LOANER/YeOldeShip.h5")
if differences:
    print("Differences found:")
    for diff in differences:
        print(diff)
else:
    print("No differences found")
